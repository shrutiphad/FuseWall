"""Regression cases found in the 0.2 review; isolated synthetic traffic only."""

import asyncio
import json
import sqlite3
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from unittest.mock import patch

from fusewall import engine, reporting
from fusewall.models import KeyCreate, LabRun
from fusewall.store import Fault, Store
from tests.support import WorkspaceDirectory
from tests.test_accounting import body


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp = WorkspaceDirectory()
        self.store = Store(self.tmp.name)
        self.key = self.store.create_key(KeyCreate(name='Review', budget_micro=10_000_000,
            session_budget_micro=5_000_000, max_calls=10_000, rpm=10_000, max_concurrent=32))

    def tearDown(self):
        self.tmp.cleanup()

    def reserve(self, session='review', **kwargs):
        return self.store.reserve(self.key['id'], session, body(), **kwargs)

    def unknown(self):
        t = self.reserve()
        self.store.dispatch(t['id'])
        self.store.recover()
        return t

    def test_resolution_audit_failure_rolls_back_settlement(self):
        t = self.unknown()
        original = self.store.event
        def fail(conn, kind, *args):
            if kind == 'manual_resolution':
                raise sqlite3.OperationalError('audit insert unavailable')
            return original(conn, kind, *args)
        with patch.object(self.store, 'event', fail), self.assertRaises(sqlite3.OperationalError):
            self.store.resolve(t['id'], 100, 'Evidence of confirmed usage')
        self.assertEqual(self.store.request_list()[0]['status'], 'outcome_unknown')
        self.assertEqual(self.store.overview()['held_micro'], t['reserved_micro'])
        self.assertEqual(self.store.read('SELECT * FROM ledger'), [])
        self.assertTrue(self.store.integrity()['ok'])

    def test_racing_resolutions_have_one_settlement_and_one_audit(self):
        t = self.unknown()
        def resolve(amount):
            try:
                return self.store.resolve(t['id'], amount, 'Verified synthetic usage')
            except Fault as exc:
                return exc.code
        with ThreadPoolExecutor(max_workers=2) as pool:
            result = list(pool.map(resolve, [100, 200]))
        self.assertEqual(sum(isinstance(r, dict) for r in result), 1)
        self.assertIn('not_uncertain', result)
        self.assertEqual(len(self.store.read("SELECT * FROM events WHERE kind='manual_resolution'")), 1)
        self.assertEqual(len(self.store.read('SELECT * FROM ledger')), 1)
        self.assertTrue(self.store.integrity()['ok'])

    def test_integrity_uses_a_coherent_snapshot_while_writer_settles(self):
        t = self.reserve()
        with self.store.snapshot() as conn:
            store = self.store
            class ConcurrentWriter:
                changed = False
                def execute(self, sql):
                    if 'sum(amount)' in sql and not self.changed:
                        self.changed = True
                        store.finish(t['id'], 1)
                    return conn.execute(sql)
            result = self.store._integrity(ConcurrentWriter())
        self.assertTrue(result['ok'], result)
        self.assertEqual(result['ledger_micro'], 0)
        self.assertGreater(self.store.integrity()['ledger_micro'], 0)

    def test_integrity_detects_per_request_mismatch_even_when_totals_match(self):
        a, b = self.reserve(), self.reserve()
        self.store.finish(a['id'], 1)
        self.store.finish(b['id'], 1)
        with self.store.transaction() as conn:
            conn.execute('DROP TRIGGER ledger_no_update')
            conn.execute('UPDATE ledger SET amount=amount+1 WHERE request_id=?', (a['id'],))
            conn.execute('UPDATE ledger SET amount=amount-1 WHERE request_id=?', (b['id'],))
        result = self.store.integrity()
        self.assertEqual(result['ledger_micro'], result['request_micro'])
        self.assertFalse(result['ok'])
        self.assertEqual(set(result['inconsistent_requests']), {a['id'], b['id']})

    def dump(self):
        with self.store.snapshot() as conn:
            return '\n'.join(conn.iterdump())

    def test_preview_has_no_persistent_changes_and_matches_admission(self):
        before = self.dump()
        p = reporting.preview(self.store, self.key['id'], 'new', body())
        self.assertEqual(self.dump(), before)
        self.assertTrue(p['allowed'])
        self.assertEqual(len(p['scopes']), 3)
        t = self.reserve(session='new')
        self.assertEqual(t['reserved_micro'], p['required_micro'])
        self.store.update_settings(t['reserved_micro'], False)
        p = reporting.preview(self.store, self.key['id'], 'another', body())
        self.assertFalse(p['allowed'])
        self.assertEqual(p['reason'], 'organization_budget')
        with self.assertRaises(Fault) as blocked:
            self.reserve(session='another')
        self.assertEqual(blocked.exception.code, p['reason'])

    def test_preview_is_advisory_and_does_not_grant_authority(self):
        self.assertTrue(reporting.preview(self.store, self.key['id'], 'new', body())['allowed'])
        self.store.update_settings(0, False)
        with self.assertRaises(Fault):
            self.reserve(session='new')
        self.store.patch_key(self.key['id'], False)
        with self.assertRaises(Fault) as exc:
            reporting.preview(self.store, self.key['id'], 'new', body())
        self.assertEqual(exc.exception.code, 'invalid_key')

    def test_preview_matches_repeat_model_rate_concurrency_and_session_rules(self):
        k = self.store.create_key(KeyCreate(name='Tight', max_calls=1, loop_threshold=2, max_concurrent=1))
        payload = body()
        for mode in ['model', 'active', 'calls', 'paused']:
            session = 'case-' + mode
            if mode == 'model':
                payload = {**body(), 'model': 'fusewall/pro'}
            else:
                payload = body()
            if mode in ('active', 'calls'):
                t = self.store.reserve(k['id'], session, payload)
                if mode == 'calls': self.store.finish(t['id'], 1)
            if mode == 'paused': self.store.update_settings(10_000_000, True)
            p = reporting.preview(self.store, k['id'], session, payload)
            with self.assertRaises(Fault) as exc:
                self.store.reserve(k['id'], session, payload)
            self.assertEqual(p['reason'], exc.exception.code)
            if mode == 'active': self.store.finish(t['id'], 0)

    def test_paginated_search_sees_older_records_and_treats_wildcards_literally(self):
        other = self.store.create_key(KeyCreate(name='100%_literal'))
        self.store.finish(self.store.reserve(other['id'], 'old-session', body())['id'], 1)
        for i in range(105):
            self.store.finish(self.reserve(session=str(i))['id'], 1)
        p = reporting.request_page(self.store, limit=50)
        self.assertEqual(p['total'], 106)
        self.assertEqual(len(p['requests']), 50)
        second = reporting.request_page(self.store, limit=50, offset=50)
        self.assertFalse({r['id'] for r in p['requests']} & {r['id'] for r in second['requests']})
        old = reporting.request_page(self.store, search='%_')
        self.assertEqual(old['total'], 1)
        self.assertEqual(old['requests'][0]['external_id'], 'old-session')
        self.assertEqual(reporting.request_page(self.store, key_id=other['id'])['total'], 1)
        self.assertEqual(reporting.request_page(self.store, search="' OR 1=1 --")['total'], 0)
        self.assertNotIn('fingerprint', old['requests'][0])
        self.assertNotIn('idempotency', old['requests'][0])

    def test_insights_use_admission_month_and_label_released_allowance(self):
        old = datetime(2020, 1, 1, tzinfo=timezone.utc).timestamp()
        self.store.finish(self.reserve(session='old', now=old)['id'], 1)
        t = self.reserve()
        self.store.finish(t['id'], 1, 'failed')
        before = self.dump()
        result = reporting.insights(self.store)
        self.assertEqual(result['totals']['requests'], 1)
        self.assertEqual(result['totals']['actual_micro'], 360)
        self.assertEqual(result['totals']['failed_cost_micro'], 360)
        self.assertEqual(result['totals']['released_micro'], t['reserved_micro'] - 360)
        self.assertEqual(result['workloads'][0]['name'], 'Review')
        self.assertIn('not money saved', result['assumption'])
        self.assertEqual(self.dump(), before)

    def test_receipt_includes_resolution_evidence_but_no_fingerprints(self):
        t = self.unknown()
        self.store.resolve(t['id'], 100, 'Owner verified synthetic receipt')
        r = reporting.receipt(self.store, t['id'])
        self.assertEqual(r['actual'], 100)
        self.assertTrue(any(e['kind']=='manual_resolution' for e in r['events']))
        self.assertNotIn('fingerprint', r)
        with self.assertRaises(Fault): reporting.receipt(self.store, 'missing')

    def test_lab_waits_for_sibling_cleanup_after_unexpected_failure(self):
        active, cleaned = set(), []
        async def fake(*args, **kwargs):
            n = len(active)
            active.add(n)
            try:
                await asyncio.sleep(.01 if n == 0 else 10)
                if n == 0: raise sqlite3.OperationalError('authority lost')
            finally:
                cleaned.append(n)
        async def scenario():
            spec = LabRun(key_id=self.key['id'], session_id='batch', calls=2, parallel=2)
            with patch.object(engine, 'execute', fake):
                with self.assertRaises(sqlite3.OperationalError):
                    await engine.run_lab(self.store, spec)
                self.assertEqual(set(cleaned), {0, 1})
        asyncio.run(scenario())

    def test_repeated_cancellation_does_not_abandon_a_reservation_thread(self):
        started = threading.Event()
        original = self.store.reserve
        def delayed(*args, **kwargs):
            started.set()
            time.sleep(.08)
            return original(*args, **kwargs)
        async def scenario():
            with patch.object(self.store, 'reserve', delayed):
                task = asyncio.create_task(engine.execute(self.store, self.key['id'], 'cancel-twice', body()))
                await asyncio.to_thread(started.wait)
                task.cancel()
                await asyncio.sleep(.01)
                task.cancel()
                with self.assertRaises(asyncio.CancelledError): await task
        asyncio.run(scenario())
        self.assertEqual(self.store.overview()['held_micro'], 0)
        self.assertEqual(self.store.request_list()[0]['status'], 'canceled')
        self.assertTrue(self.store.integrity()['ok'])

    def test_database_dispatch_wait_does_not_block_the_event_loop(self):
        started = threading.Event()
        original = self.store.dispatch
        ticks = []
        def delayed(*args):
            started.set()
            time.sleep(.08)
            return original(*args)
        async def scenario():
            with patch.object(self.store, 'dispatch', delayed):
                task = asyncio.create_task(engine.execute(self.store, self.key['id'], 'responsive', body()))
                await asyncio.to_thread(started.wait)
                for _ in range(3):
                    await asyncio.sleep(.01)
                    ticks.append(not task.done())
                await task
        asyncio.run(scenario())
        self.assertEqual(ticks, [True, True, True])
        self.assertTrue(self.store.integrity()['ok'])


if __name__ == '__main__':
    unittest.main()
