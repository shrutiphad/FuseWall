import asyncio
import json
import random
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
import threading
import time
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from fusewall import engine
from fusewall.models import KeyCreate
from fusewall.runtime import InstanceLock
from fusewall.store import Fault, RATES, Store
from tests.support import WorkspaceDirectory


def body(max_tokens=10):
    return {"model":"fusewall/mini", "messages":[{"role":"user", "content":"Hello world"}], "max_tokens":max_tokens, "stream":False}


class AccountingTests(unittest.TestCase):
    def setUp(self):
        scratch = Path(__file__).resolve().parent.parent / 'test-results' / 'tmp'
        scratch.mkdir(parents=True, exist_ok=True)
        self.tmp = WorkspaceDirectory(dir=scratch)
        self.store = Store(self.tmp.name)
        self.key = self.store.create_key(KeyCreate(name="Test", budget_micro=10_000_000,
            session_budget_micro=5_000_000, max_calls=10_000, rpm=10_000, max_concurrent=32))

    def tearDown(self):
        self.tmp.cleanup()

    def reserve(self, **kwargs):
        return self.store.reserve(self.key["id"], "test", body(), **kwargs)

    def test_parallel_calls_cannot_double_spend_parent_budget(self):
        self.store.update_settings(3000, False)
        def attempt(i):
            try:
                return self.store.reserve(self.key["id"], f"session-{i}", body())
            except Fault as error:
                self.assertEqual(error.status, 402)
                return None
        with ThreadPoolExecutor(max_workers=16) as pool:
            accepted = [t for t in pool.map(attempt, range(32)) if t]
        self.assertEqual(len(accepted), 2)
        self.assertLessEqual(sum(t["reserved_micro"] for t in accepted), 3000)
        self.assertTrue(self.store.integrity()["ok"])

    def test_parent_budget_applies_across_keys_and_sessions(self):
        self.store.update_settings(1500, False)
        self.reserve()
        other = self.store.create_key(KeyCreate(name="Other"))
        with self.assertRaises(Fault) as context:
            self.store.reserve(other["id"], "new-session", body())
        self.assertEqual(context.exception.code, "organization_budget")

    def test_settlement_releases_unused_allowance_exactly_once(self):
        ticket = self.reserve()
        self.store.dispatch(ticket["id"])
        first = self.store.finish(ticket["id"], 3)
        self.store.finish(ticket["id"], 9)
        self.assertEqual(len(self.store.read("SELECT * FROM ledger")), 1)
        self.assertEqual(self.store.overview()["held_micro"], 0)
        self.assertEqual(self.store.overview()["spent_micro"], first["actual"])
        self.assertTrue(self.store.integrity()["ok"])

    def test_usage_overrun_retains_original_hold(self):
        ticket = self.reserve()
        self.store.dispatch(ticket["id"])
        with self.assertRaises(Fault):
            self.store.finish(ticket["id"], 99999)
        self.assertEqual(self.store.overview()["held_micro"], ticket["reserved_micro"])
        self.assertEqual(len(self.store.read("SELECT * FROM ledger")), 0)

    def test_idempotency_under_race_admits_only_one_request(self):
        def submit(i):
            try:
                return self.reserve(idempotency="same-request")
            except Fault as error:
                self.assertEqual(error.code, "idempotency_replay")
                return None
        with ThreadPoolExecutor(max_workers=8) as pool:
            result = list(pool.map(submit, range(8)))
        self.assertEqual(sum(bool(t) for t in result), 1)
        self.assertEqual(len(self.store.request_list()), 1)

    def test_idempotency_mismatched_payload_is_conflict(self):
        self.reserve(idempotency="same")
        with self.assertRaises(Fault) as context:
            self.store.reserve(self.key["id"], "test", body(20), idempotency="same")
        self.assertEqual(context.exception.code, "idempotency_conflict")

    def test_same_session_label_on_different_keys_is_isolated(self):
        other = self.store.create_key(KeyCreate(name="Other"))
        a = self.reserve()
        b = self.store.reserve(other["id"], "test", body())
        self.assertNotEqual(a["session_id"], b["session_id"])

    def test_revocation_between_reserve_and_dispatch_releases_hold(self):
        ticket = self.reserve()
        self.store.patch_key(self.key["id"], False)
        with self.assertRaises(Fault):
            self.store.dispatch(ticket["id"])
        self.assertEqual(self.store.overview()["held_micro"], 0)
        self.assertTrue(self.store.integrity()["ok"])

    def test_pause_blocks_and_can_resume(self):
        self.store.update_settings(10_000_000, True)
        with self.assertRaises(Fault) as context:
            self.reserve()
        self.assertEqual(context.exception.code, "organization_paused")
        self.store.update_settings(10_000_000, False)
        self.assertTrue(self.reserve())

    def test_cannot_lower_budget_below_committed_exposure(self):
        self.reserve()
        with self.assertRaises(Fault):
            self.store.update_settings(0, False)

    def test_recovery_releases_only_known_undispatched_work(self):
        self.reserve()
        dispatched = self.reserve()
        self.store.dispatch(dispatched["id"])
        self.assertEqual(self.store.recover(), {"canceled":1, "unknown":1})
        self.store.recover()
        self.assertEqual(self.store.overview()["held_micro"], dispatched["reserved_micro"])
        self.store.resolve(dispatched["id"], 200, "Confirmed synthetic failure in test")
        self.assertEqual(self.store.overview()["held_micro"], 0)
        self.assertTrue(self.store.integrity()["ok"])

    def test_real_process_exit_preserves_uncertain_reservation(self):
        code = "from fusewall.store import Store; import sys,os,json; s=Store(sys.argv[1]); t=s.reserve(sys.argv[2],'crash',json.loads(sys.argv[3])); s.dispatch(t['id']); os._exit(0)"
        process = subprocess.run([sys.executable,"-c",code,self.tmp.name,self.key["id"],json.dumps(body())],capture_output=True,timeout=20)
        self.assertEqual(process.returncode, 0, process.stderr.decode())
        restarted = Store(self.tmp.name)
        self.assertEqual(restarted.recover()["unknown"], 1)
        self.assertGreater(restarted.overview()["held_micro"], 0)
        self.assertTrue(restarted.integrity()["ok"])

    def test_rate_card_snapshot_survives_changed_global_rates(self):
        ticket = self.reserve()
        old = RATES["fusewall/mini"]["output_micro"]
        try:
            RATES["fusewall/mini"]["output_micro"] = 999999
            result = self.store.finish(ticket["id"], 1)
            self.assertEqual(result["actual"], ticket["input_tokens"]*20 + old)
        finally:
            RATES["fusewall/mini"]["output_micro"] = old

    def test_month_snapshot_keeps_old_hold_in_original_bucket(self):
        jan = datetime(2026,1,31,23,59,59,tzinfo=timezone.utc).timestamp()
        first = self.reserve(now=jan)
        second = self.reserve(now=jan+2)
        self.store.finish(first["id"], 1)
        a = self.store.read("SELECT * FROM buckets WHERE scope='org:2026-01'")[0]
        b = self.store.read("SELECT * FROM buckets WHERE scope='org:2026-02'")[0]
        self.assertEqual(a["held"], 0)
        self.assertEqual(b["held"], second["reserved_micro"])
        self.assertTrue(self.store.integrity()["ok"])

    def test_loop_guard_stays_tripped_after_restart(self):
        k = self.store.create_key(KeyCreate(name="Repeater", loop_threshold=3))
        for _ in range(2):
            t = self.store.reserve(k["id"], "repeated", body())
            self.store.finish(t["id"], 1)
        with self.assertRaises(Fault) as context:
            self.store.reserve(k["id"], "repeated", body())
        self.assertEqual(context.exception.code, "repeat_guard")
        with self.assertRaises(Fault) as context:
            Store(self.tmp.name).reserve(k["id"], "repeated", body())
        self.assertEqual(context.exception.code, "session_tripped")

    def test_expiry_and_call_cap(self):
        k = self.store.create_key(KeyCreate(name="Short", max_calls=1, duration_seconds=1))
        t = self.store.reserve(k["id"], "one", body(), now=100)
        self.store.finish(t["id"], 1)
        with self.assertRaises(Fault) as context:
            self.store.reserve(k["id"], "one", body(), now=100.5)
        self.assertEqual(context.exception.code, "session_call_limit")
        self.store.reserve(k["id"], "two", body(), now=100)
        with self.assertRaises(Fault) as context:
            self.store.reserve(k["id"], "two", body(), now=102)
        self.assertEqual(context.exception.code, "session_expired")

    def test_ledger_rejects_update_and_delete(self):
        self.store.finish(self.reserve()["id"], 1)
        for sql in ("UPDATE ledger SET amount=0", "DELETE FROM ledger"):
            with self.assertRaises(sqlite3.IntegrityError):
                with self.store.transaction() as conn:
                    conn.execute(sql)

    def test_randomized_duplicates_crashes_and_settlement_preserve_invariants(self):
        rand = random.Random(721)
        for i in range(150):
            t = self.store.reserve(self.key["id"], f"random-{i}", body(rand.randint(1,100)))
            if rand.random() < .2:
                self.store.dispatch(t["id"])
                self.store.recover()
                self.store.resolve(t["id"], rand.randint(0,t["reserved_micro"]), "Synthetic randomized reconciliation")
            else:
                self.store.finish(t["id"], 1)
                self.store.finish(t["id"], 1)
            self.assertTrue(self.store.integrity()["ok"])

    def test_backup_restores_consistently(self):
        self.store.finish(self.reserve()["id"], 2)
        backup = self.store.backup()
        with WorkspaceDirectory(dir=Path(self.tmp.name).parent) as target:
            shutil.copyfile(backup, target + "/fusewall.db")
            restored = Store(target)
            self.assertEqual(restored.overview()["spent_micro"], self.store.overview()["spent_micro"])
            self.assertTrue(restored.integrity()["ok"])

    def test_replay_does_not_create_traffic_or_change_budget(self):
        self.store.finish(self.reserve()["id"], 1)
        before = self.store.overview()
        self.assertEqual(self.store.replay(1,100)["allowed"], 0)
        self.assertEqual(self.store.overview(), before)

    def test_two_server_owners_cannot_recover_same_database(self):
        a = InstanceLock(self.store.directory / "server.lock")
        b = InstanceLock(self.store.directory / "server.lock")
        a.acquire()
        try:
            with self.assertRaises(RuntimeError): b.acquire()
        finally:
            a.release()

    def test_stream_cancellation_settles_only_emitted_synthetic_units(self):
        async def scenario():
            t = self.reserve()
            self.store.dispatch(t["id"])
            async def disconnected(): return False
            gen = engine.stream(self.store,t,body(),disconnected)
            await anext(gen)
            await gen.aclose()
            return t
        t = asyncio.run(scenario())
        row = self.store.read("SELECT * FROM requests WHERE id=?",(t["id"],))[0]
        self.assertEqual(row["status"], "canceled")
        self.assertEqual(row["output_tokens"], 1)
        self.assertEqual(self.store.overview()["held_micro"], 0)

    def test_no_prompt_or_raw_key_is_persisted(self):
        payload = body()
        payload["messages"][0]["content"] = "PRIVATE SENTENCE NEVER STORED IN DATABASE"
        self.store.reserve(self.key["id"], "private", payload)
        conn = self.store.connect()
        try: dump = "\n".join(conn.iterdump())
        finally: conn.close()
        self.assertNotIn("PRIVATE SENTENCE",dump)
        self.assertNotIn(self.key["token"],dump)

    def test_cancel_during_reservation_releases_undispatched_hold(self):
        original = self.store.reserve
        started = threading.Event()
        def delayed(*args, **kwargs):
            started.set()
            time.sleep(.05)
            return original(*args, **kwargs)
        async def scenario():
            with patch.object(self.store, 'reserve', delayed):
                task = asyncio.create_task(engine.execute(self.store,self.key['id'],'cancel-reserve',body()))
                await asyncio.to_thread(started.wait)
                task.cancel()
                with self.assertRaises(asyncio.CancelledError): await task
        asyncio.run(scenario())
        self.assertEqual(self.store.overview()['held_micro'],0)
        self.assertEqual(self.store.request_list()[0]['status'],'canceled')
        self.assertTrue(self.store.integrity()['ok'])

    def test_unknown_price_fails_before_reservation(self):
        payload = body()
        payload['model']='not-priced'
        with self.assertRaises(Fault): self.store.reserve(self.key['id'],'unknown',payload)
        self.assertEqual(self.store.overview()['requests'],0)

    def test_rate_and_concurrency_caps(self):
        key = self.store.create_key(KeyCreate(name='Paced',max_concurrent=1,rpm=1))
        ticket = self.store.reserve(key['id'],'one',body())
        with self.assertRaises(Fault) as error: self.store.reserve(key['id'],'two',body())
        self.assertEqual(error.exception.code,'concurrency_limit')
        self.store.dispatch(ticket['id'])
        self.store.finish(ticket['id'],1)
        with self.assertRaises(Fault) as error: self.store.reserve(key['id'],'three',body())
        self.assertEqual(error.exception.code,'rate_limit')


if __name__ == "__main__": unittest.main()
