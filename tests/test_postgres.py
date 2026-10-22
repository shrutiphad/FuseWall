"""Actual PostgreSQL integration, never customer data. Requires a loopback test DSN."""

import asyncio
import json
import os
import sqlite3
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit
from unittest.mock import patch

from fastapi.testclient import TestClient
from fusewall.app import create_app
from fusewall.models import KeyCreate
from fusewall.store import Fault
from tests.test_accounting import body
import tests.test_api as api_cases

DSN = os.environ.get("FUSEWALL_PG_TEST_URL")
OWNER, FINGERPRINT = "test-owner-" + "o"*40, "test-fingerprint-" + "f"*40


class Fixture:
    def setup_database(self):
        if urlsplit(DSN).hostname not in ("127.0.0.1", "localhost", "::1"):
            raise RuntimeError("Integration tests may only create/drop schemas on loopback PostgreSQL")
        from fusewall.postgres import PostgresStore
        self.schema = "fw_test_" + uuid.uuid4().hex
        self.store = PostgresStore(DSN, OWNER, FINGERPRINT, schema=self.schema, migrate=True)

    def another_store(self, owner=OWNER):
        from fusewall.postgres import PostgresStore
        return PostgresStore(DSN, owner, FINGERPRINT, schema=self.schema)

    def cleanup_database(self):
        from psycopg import sql
        assert self.schema.startswith("fw_test_") and len(self.schema) == 40
        conn = self.store.connect()
        try:
            conn.raw.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(self.schema)))
        finally:
            conn.close()


@unittest.skipUnless(DSN, "Set FUSEWALL_PG_TEST_URL to an isolated loopback PostgreSQL server")
class PostgresAPITests(Fixture, api_cases.APITests):
    def setUp(self):
        self.setup_database()
        self.app = create_app(store=self.store, allowed_hosts={"testserver"})
        self.client = TestClient(self.app, base_url="https://testserver")
        self.client.__enter__()
        self.token = OWNER

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.cleanup_database()

    def test_backup_integrity_and_csv_formula_safety(self):
        key = self.key(name='=HYPERLINK("example")')
        self.completion(key)
        self.assertIn("'=HYPERLINK", self.client.get('/api/export').text)
        r = self.client.post('/api/backup',headers=api_cases.HEADERS)
        self.assertEqual(r.json()['format'], 'fusewall-postgres-export-v1')
        self.assertTrue(r.json()['integrity']['ok'])
        self.assertNotIn('owner_sessions', r.json()['tables'])

    def test_cloud_limits_recovery_and_secure_cookie(self):
        key=self.key()
        self.assertTrue(self.client.cookies.get('fusewall_owner'))
        self.assertEqual(self.client.post('/api/lab',json={'key_id':key['id'],'session_id':'bounded','calls':21},headers=api_cases.HEADERS).status_code,422)
        self.assertEqual(self.client.post('/api/recovery',headers=api_cases.HEADERS).json(),{'canceled':0,'unknown':0})
        self.client.cookies.clear()
        self.assertEqual(self.client.post('/api/recovery',headers=api_cases.HEADERS).status_code,401)

    def test_cloud_host_allowlist_is_explicit(self):
        self.assertEqual(self.client.get('/health/live',headers={'Host':'different.vercel.app'}).status_code,400)


@unittest.skipUnless(DSN, "Set FUSEWALL_PG_TEST_URL to an isolated loopback PostgreSQL server")
class PostgresTests(Fixture, unittest.TestCase):
    def setUp(self):
        self.setup_database()
        self.key = self.store.create_key(KeyCreate(name="PG concurrency", session_budget_micro=5_000_000,
            budget_micro=10_000_000, max_calls=1000, max_concurrent=32, rpm=10000))

    def tearDown(self):
        self.cleanup_database()

    def reserve(self, store=None, session="run", **kwargs):
        return (store or self.store).reserve(self.key['id'], session, body(), **kwargs)

    def expire(self, request_id):
        with self.store.transaction() as conn:
            conn.execute("UPDATE requests SET lease_expires=extract(epoch FROM clock_timestamp())-1 WHERE id=?", (request_id,))

    def test_separate_instances_share_one_parent_budget(self):
        self.store.update_settings(3000, False)
        def attempt(i):
            try:
                return self.reserve(self.another_store(), session=str(i))
            except Fault as exc:
                self.assertEqual(exc.code, 'organization_budget')
        with ThreadPoolExecutor(max_workers=16) as pool:
            accepted = [r for r in pool.map(attempt, range(24)) if r]
        self.assertEqual(len(accepted),2)
        self.assertTrue(self.store.integrity()['ok'])

    def test_duplicate_admission_and_settlement_across_instances(self):
        def reserve(i):
            try: return self.reserve(self.another_store(), idempotency='same')
            except Fault as exc: self.assertEqual(exc.code,'idempotency_replay')
        with ThreadPoolExecutor(max_workers=8) as pool:
            accepted = [r for r in pool.map(reserve,range(8)) if r]
        self.assertEqual(len(accepted),1)
        t=accepted[0]
        self.store.dispatch(t['id'])
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(lambda i:self.another_store().finish(t['id'],1),range(8)))
        self.assertEqual(len(self.store.read('SELECT * FROM ledger')),1)
        self.assertTrue(self.store.integrity()['ok'])

    def test_owner_session_survives_worker_change_and_logout_is_shared(self):
        raw=self.store.login(OWNER)
        self.assertTrue(self.another_store().owner_valid(raw))
        self.another_store().logout(raw)
        self.assertFalse(self.store.owner_valid(raw))

    def test_owner_rotation_invalidates_old_sessions(self):
        raw=self.store.login(OWNER)
        self.assertFalse(self.another_store(owner='rotated-'+ 'x'*40).owner_valid(raw))

    def test_login_failures_are_durable_and_rate_limit_is_global(self):
        for _ in range(10):
            with self.assertRaises(Fault) as exc:self.another_store().login('wrong-token')
            self.assertEqual(exc.exception.status,401)
        with self.assertRaises(Fault) as exc:self.store.login(OWNER)
        self.assertEqual(exc.exception.status,429)
        self.assertEqual(len(self.store.read('SELECT * FROM login_attempts')),10)

    def test_fresh_worker_does_not_recover_active_peer_requests(self):
        a=self.reserve(session='reserved')
        b=self.reserve(session='dispatching')
        self.store.dispatch(b['id'])
        other=self.another_store()
        with TestClient(create_app(store=other,allowed_hosts={'testserver'}),base_url='https://testserver'):
            self.assertEqual(other.recover(),{'canceled':0,'unknown':0})
        self.assertEqual(self.store.overview()['held_micro'],a['reserved_micro']+b['reserved_micro'])

    def test_expired_reserved_work_cannot_dispatch_and_recovery_retains_uncertainty(self):
        a=self.reserve(session='reserved')
        b=self.reserve(session='dispatch')
        self.store.dispatch(b['id'])
        self.expire(a['id']);self.expire(b['id'])
        self.assertEqual(self.another_store().recover(),{'canceled':1,'unknown':1})
        with self.assertRaises(Fault):self.store.dispatch(a['id'])
        self.assertEqual(self.store.overview()['held_micro'],b['reserved_micro'])
        self.store.resolve(b['id'],100,'Synthetic confirmed final usage')
        self.assertTrue(self.store.integrity()['ok'])

    def test_dispatch_rechecks_expiry_even_without_recovery(self):
        t=self.reserve();self.expire(t['id'])
        with self.assertRaises(Fault):self.another_store().dispatch(t['id'])
        self.assertEqual(self.store.overview()['held_micro'],0)
        self.assertTrue(self.store.integrity()['ok'])

    def test_lab_lease_is_shared_and_old_owner_cannot_release_new_lease(self):
        token=self.store.acquire_lab()
        with self.assertRaises(Fault):self.another_store().acquire_lab()
        with self.store.transaction() as conn:conn.execute('UPDATE lab_lease SET expires=0')
        new=self.another_store().acquire_lab()
        self.store.release_lab(token)
        with self.assertRaises(Fault):self.store.acquire_lab()
        self.store.release_lab(new)
        self.store.release_lab(self.store.acquire_lab())

    def test_resolution_audit_failure_rolls_back_shared_settlement(self):
        t=self.reserve();self.store.dispatch(t['id']);self.expire(t['id']);self.store.recover()
        original=self.store.event
        def fail(conn,kind,*args):
            if kind=='manual_resolution':raise sqlite3.OperationalError('synthetic audit failure')
            original(conn,kind,*args)
        with patch.object(self.store,'event',fail),self.assertRaises(sqlite3.OperationalError):
            self.store.resolve(t['id'],0,'Confirmed synthetic failure')
        self.assertEqual(self.store.request_list()[0]['status'],'outcome_unknown')
        self.assertEqual(self.store.overview()['held_micro'],t['reserved_micro'])
        self.assertTrue(self.store.integrity()['ok'])

    def test_ledger_rejects_update_delete_and_truncate(self):
        self.store.finish(self.reserve()['id'],1)
        for statement in ['UPDATE ledger SET amount=0','DELETE FROM ledger','TRUNCATE ledger']:
            with self.assertRaises(sqlite3.OperationalError):
                with self.store.transaction() as conn:conn.execute(statement)
        self.assertTrue(self.store.integrity()['ok'])

    def test_database_faults_do_not_disclose_connection_strings(self):
        import psycopg
        with patch('psycopg.connect',side_effect=psycopg.OperationalError('password=private')):
            with self.assertRaises(sqlite3.OperationalError) as exc:self.store.connect()
        self.assertNotIn('private',str(exc.exception))

    def test_private_schema_has_no_public_access(self):
        conn=self.store.connect()
        try:
            acl=conn.execute('SELECT nspacl::text AS acl FROM pg_namespace WHERE nspname=?',(self.schema,)).fetchone()['acl']
            self.assertNotIn('=U/',acl or '')
        finally:conn.close()

    def test_migration_rejects_reserved_or_unrecognized_schema(self):
        from fusewall.postgres import PostgresStore
        from psycopg import sql
        with self.assertRaises(ValueError):PostgresStore(DSN,OWNER,FINGERPRINT,schema='public',migrate=True)
        schema='fw_test_'+uuid.uuid4().hex
        conn=self.store.connect()
        try:
            conn.raw.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
            conn.raw.execute(sql.SQL('CREATE TABLE {}.unrelated(id integer)').format(sql.Identifier(schema)))
            with self.assertRaises(ValueError):PostgresStore(DSN,OWNER,FINGERPRINT,schema=schema,migrate=True)
            self.assertTrue(conn.raw.execute('SELECT to_regclass(%s) AS name',(schema+'.unrelated',)).fetchone()['name'])
        finally:
            conn.raw.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))
            conn.close()

    def test_accounting_snapshot_with_concurrent_writer(self):
        t=self.reserve()
        with self.store.snapshot() as conn:
            before=conn.execute('SELECT sum(held) AS held FROM buckets').fetchone()['held']
            self.another_store().finish(t['id'],1)
            after=conn.execute('SELECT sum(held) AS held FROM buckets').fetchone()['held']
        self.assertEqual(before,after)
        self.assertTrue(self.store.integrity()['ok'])

    def test_metadata_restore_is_atomic_validated_and_never_overwrites(self):
        from fusewall.postgres import PostgresStore
        self.store.finish(self.reserve()['id'],2)
        payload=self.store.export_snapshot()
        target_schema='fw_test_'+uuid.uuid4().hex
        target=PostgresStore(DSN,OWNER,FINGERPRINT,schema=target_schema,migrate=True)
        try:
            malformed=json.loads(json.dumps(payload))
            malformed['tables']['buckets'][0]['spent']+=1
            with self.assertRaises(ValueError):target.restore_snapshot(malformed)
            self.assertEqual(target.overview()['requests'],0)
            target.restore_snapshot(payload)
            self.assertEqual(target.overview()['spent_micro'],self.store.overview()['spent_micro'])
            self.assertTrue(target.integrity()['ok'])
            with self.assertRaises(ValueError):target.restore_snapshot(payload)
        finally:
            from psycopg import sql
            conn=target.connect()
            try:conn.raw.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(target_schema)))
            finally:conn.close()


class CloudConfigurationTests(unittest.TestCase):
    def test_vercel_never_falls_back_to_sqlite(self):
        with patch.dict(os.environ,{'VERCEL':'1'}),self.assertRaises(RuntimeError):create_app()

    def test_cloud_requires_durable_secrets_and_explicit_hosts(self):
        from fusewall.cloud import store_from_environment
        with patch.dict(os.environ,{},clear=True),self.assertRaises(RuntimeError):store_from_environment()
