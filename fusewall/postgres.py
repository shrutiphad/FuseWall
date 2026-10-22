"""Shared PostgreSQL authority. No filesystem state, process lock or startup recovery.

The small SQL bridge only adapts the application's fixed, parameterized queries.
All write operations share one transaction-scoped advisory lock per schema.
"""

import hashlib
import json
import re
import secrets
import sqlite3
import time
from contextlib import contextmanager
from decimal import Decimal

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from .store import Fault, Store, digest, uid

LEASE_SECONDS = 120  # Longer than the deployed function's 60-second maximum.
TABLES = ("settings", "keys", "buckets", "sessions", "requests", "ledger", "events")


class Row(dict):
    def __getitem__(self, key):
        return list(self.values())[key] if isinstance(key, int) else super().__getitem__(key)


class Cursor:
    def __init__(self, cursor):
        self.cursor = cursor
        self.rowcount = cursor.rowcount

    @staticmethod
    def adapt(row):
        return None if row is None else Row({k: (int(v) if v == v.to_integral_value() else float(v)) if isinstance(v, Decimal) else v for k, v in row.items()})

    def fetchone(self):
        return self.adapt(self.cursor.fetchone())

    def fetchall(self):
        return [self.adapt(r) for r in self.cursor.fetchall()]

    def __iter__(self):
        return iter(self.fetchall())


class Connection:
    def __init__(self, raw, schema):
        self.raw, self.schema = raw, schema

    @property
    def in_transaction(self):
        return self.raw.info.transaction_status != psycopg.pq.TransactionStatus.IDLE

    def begin(self, snapshot=False):
        try:
            self.raw.execute("BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY" if snapshot else "BEGIN")
            self.raw.execute(sql.SQL("SET LOCAL search_path TO {}, pg_catalog").format(sql.Identifier(self.schema)))
            self.raw.execute("SET LOCAL statement_timeout='10s'")
            self.raw.execute("SET LOCAL lock_timeout='5s'")
        except psycopg.Error as exc:
            raise sqlite3.OperationalError("Shared database transaction unavailable") from exc

    def execute(self, query, params=()):
        try:
            if query in ("COMMIT", "ROLLBACK"):
                return Cursor(self.raw.execute(query))
            if not self.in_transaction:
                self.begin()
            ignore = "INSERT OR IGNORE INTO" in query
            query = query.replace("INSERT OR IGNORE INTO", "INSERT INTO")
            if ignore:
                query += " ON CONFLICT DO NOTHING"
            query = query.replace("?", "%s").replace("instr(", "strpos(")
            query = query.replace("json_each(r.scopes)", "jsonb_array_elements_text(r.scopes::jsonb) AS j(value)")
            query = query.replace("substr(datetime(created,'unixepoch'),1,13)", "to_char(to_timestamp(created) AT TIME ZONE 'UTC','YYYY-MM-DD HH24')")
            return Cursor(self.raw.execute(query, params or None))
        except psycopg.IntegrityError as exc:
            raise sqlite3.IntegrityError("Shared database constraint rejected the operation") from exc
        except psycopg.Error as exc:
            raise sqlite3.OperationalError("Shared database authority unavailable") from exc

    def close(self):
        try:
            if not self.raw.closed and self.in_transaction:
                self.raw.execute("ROLLBACK")
        except psycopg.Error:
            pass
        finally:
            self.raw.close()


class PostgresStore(Store):
    hosted = True

    def __init__(self, dsn, owner_token, fingerprint_key, schema="fusewall", migrate=False):
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,62}", schema) or not schema.startswith(("fusewall", "fw_test_")):
            raise ValueError("Use a dedicated fusewall-prefixed schema, never public/auth/storage")
        if len(owner_token) < 32 or len(fingerprint_key) < 32:
            raise ValueError("Cloud owner and fingerprint secrets must each contain at least 32 characters")
        self.dsn, self.schema = dsn, schema
        self.admin_hash = digest(owner_token)
        self.fingerprint_secret = fingerprint_key.encode()
        self.owner_epoch = digest(self.admin_hash + fingerprint_key)
        if migrate:
            self.migrate()

    def connect(self):
        try:
            # Prepared statements are disabled for Supabase's transaction pooler.
            raw = psycopg.connect(self.dsn, autocommit=True, row_factory=dict_row, prepare_threshold=None, connect_timeout=8)
            return Connection(raw, self.schema)
        except psycopg.Error as exc:
            raise sqlite3.OperationalError("Shared database connection unavailable") from exc

    @contextmanager
    def transaction(self):
        conn = self.connect()
        try:
            conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(?,0))", ("fusewall-write:" + self.schema,))
            yield conn
            conn.execute("COMMIT")
        except BaseException:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()

    @contextmanager
    def snapshot(self):
        conn = self.connect()
        try:
            conn.begin(snapshot=True)
            yield conn
        finally:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            conn.close()

    def migrate(self):
        from pathlib import Path
        conn = self.connect()
        try:
            conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(?,0))", ("fusewall-migration:" + self.schema,))
            tables = conn.execute("SELECT table_name FROM information_schema.tables WHERE table_schema=?", (self.schema,)).fetchall()
            if tables and "schema_version" not in {r["table_name"] for r in tables}:
                raise ValueError("Refusing to initialize an existing unrecognized schema")
            conn.raw.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(self.schema)))
            conn.raw.execute(sql.SQL("REVOKE ALL ON SCHEMA {} FROM PUBLIC").format(sql.Identifier(self.schema)))
            conn.raw.execute(sql.SQL("SET LOCAL search_path TO {}, pg_catalog").format(sql.Identifier(self.schema)))
            conn.raw.execute((Path(__file__).parent / "migrations" / "postgres_001.sql").read_text(encoding="utf8"))
            conn.raw.execute(sql.SQL("REVOKE ALL ON ALL TABLES IN SCHEMA {} FROM PUBLIC").format(sql.Identifier(self.schema)))
            conn.execute("COMMIT")
        finally:
            conn.close()

    def assert_ready(self):
        result = self.read("SELECT version FROM schema_version WHERE id=1")
        if not result or result[0]["version"] != 1:
            raise sqlite3.OperationalError("Unsupported shared database schema")

    def dispatch(self, request_id):
        rejected = False
        with self.transaction() as conn:
            row = conn.execute("SELECT r.*,k.active FROM requests r JOIN keys k ON k.id=r.key_id WHERE r.id=?", (request_id,)).fetchone()
            if not row or row["status"] != "reserved":
                raise Fault(409, "invalid_state", "Request cannot be dispatched in its current state.")
            expired = conn.execute("SELECT extract(epoch FROM clock_timestamp()) >= ? AS expired", (row["lease_expires"],)).fetchone()[0]
            if expired or not row["active"] or conn.execute("SELECT paused FROM settings WHERE id=1").fetchone()[0]:
                for scope in json.loads(row["scopes"]):
                    conn.execute("UPDATE buckets SET held=held-? WHERE scope=?", (row["reserved"], scope))
                conn.execute("UPDATE requests SET status='canceled',reason=?,finished=? WHERE id=?",
                             ("lease_expired_before_dispatch" if expired else "authority_changed", time.time(), request_id))
                self.event(conn, "canceled", "Request authority expired or changed before dispatch", request_id)
                rejected = True
            else:
                conn.execute("UPDATE requests SET status='dispatching' WHERE id=?", (request_id,))
        if rejected:
            raise Fault(402, "authority_changed", "Request authority expired or changed before dispatch.")

    def recover(self):
        """Owner-triggered recovery only, using DB time; never called at worker startup."""
        with self.transaction() as conn:
            rows = conn.execute("SELECT * FROM requests WHERE status IN ('reserved','dispatching') AND lease_expires < extract(epoch FROM clock_timestamp())").fetchall()
            canceled = unknown = 0
            for row in rows:
                if row["status"] == "reserved":
                    for scope in json.loads(row["scopes"]):
                        conn.execute("UPDATE buckets SET held=held-? WHERE scope=?", (row["reserved"], scope))
                    conn.execute("UPDATE requests SET status='canceled',reason='lease_expired_before_dispatch',finished=? WHERE id=?", (time.time(), row["id"]))
                    canceled += 1
                else:
                    conn.execute("UPDATE requests SET status='outcome_unknown',reason='expired_dispatch_lease' WHERE id=?", (row["id"],))
                    unknown += 1
            if rows:
                self.event(conn, "recovery", f"Expired leases: {canceled} undispatched holds canceled; {unknown} uncertain holds retained")
            return {"canceled": canceled, "unknown": unknown}

    def login(self, token):
        import hmac
        invalid = False
        with self.transaction() as conn:
            now = conn.execute("SELECT extract(epoch FROM clock_timestamp()) AS now").fetchone()[0]
            conn.execute("DELETE FROM login_attempts WHERE created<?", (now-60,))
            if conn.execute("SELECT count(*) FROM login_attempts").fetchone()[0] >= 10:
                raise Fault(429, "login_rate_limit", "Too many unlock attempts. Wait one minute.")
            conn.execute("INSERT INTO login_attempts(created) VALUES(?)", (now,))
            invalid = not hmac.compare_digest(digest(token), self.admin_hash)
            raw = None
            if not invalid:
                conn.execute("DELETE FROM owner_sessions WHERE expires<=? OR epoch!=?", (now, self.owner_epoch))
                if conn.execute("SELECT count(*) FROM owner_sessions").fetchone()[0] >= 20:
                    conn.execute("DELETE FROM owner_sessions WHERE token_hash=(SELECT token_hash FROM owner_sessions ORDER BY expires LIMIT 1)")
                raw = secrets.token_urlsafe(32)
                conn.execute("INSERT INTO owner_sessions VALUES(?,?,?)", (digest(raw), now+8*3600, self.owner_epoch))
        # Invalid attempts must commit their counter before the rejection is raised.
        if invalid:
            raise Fault(401, "invalid_owner_token", "Owner token did not match.")
        return raw

    def owner_valid(self, raw):
        return bool(raw and self.read("SELECT 1 FROM owner_sessions WHERE token_hash=? AND epoch=? AND expires>extract(epoch FROM clock_timestamp())", (digest(raw), self.owner_epoch)))

    def logout(self, raw):
        with self.transaction() as conn:
            conn.execute("DELETE FROM owner_sessions WHERE token_hash=?", (digest(raw),))

    def acquire_lab(self):
        token = uid("lab_")
        with self.transaction() as conn:
            row = conn.execute("SELECT * FROM lab_lease WHERE id=1").fetchone()
            now = conn.execute("SELECT extract(epoch FROM clock_timestamp()) AS now").fetchone()[0]
            if row and row["expires"] > now:
                raise Fault(409, "lab_busy", "A laboratory run is already active. Wait for it to complete.")
            conn.execute("INSERT INTO lab_lease VALUES(1,?,?) ON CONFLICT(id) DO UPDATE SET token=excluded.token,expires=excluded.expires", (token, now+LEASE_SECONDS))
        return token

    def release_lab(self, token):
        with self.transaction() as conn:
            conn.execute("DELETE FROM lab_lease WHERE id=1 AND token=?", (token,))

    def export_snapshot(self):
        with self.snapshot() as conn:
            return {"format": "fusewall-postgres-export-v1", "schema_version": 1, "mode": "simulation",
                    "tables": {table: [dict(r) for r in conn.execute("SELECT * FROM " + table)] for table in TABLES},
                    "integrity": self._integrity(conn),
                    "note": "Metadata export; no owner/fingerprint/database secrets or owner sessions. Restore with a matching schema and preserve identity secrets separately."}

    def restore_snapshot(self, payload):
        """Restore only into an empty schema; no deletion/overwrite path exists."""
        if (payload.get("format") != "fusewall-postgres-export-v1" or payload.get("schema_version") != 1
                or set(payload.get("tables", {})) != set(TABLES)):
            raise ValueError("Unsupported export format")
        with self.transaction() as conn:
            if any(conn.execute("SELECT count(*) FROM " + t).fetchone()[0] for t in TABLES if t != "settings"):
                raise ValueError("Restore requires a newly migrated empty schema")
            for table in TABLES:
                records = payload["tables"][table]
                if not isinstance(records, list) or len(records) > 150_001:
                    raise ValueError("Invalid export table bounds")
                columns = [r["column_name"] for r in conn.execute("SELECT column_name FROM information_schema.columns WHERE table_schema=? AND table_name=? ORDER BY ordinal_position", (self.schema, table))]
                for record in records:
                    if not isinstance(record, dict) or set(record) != set(columns):
                        raise ValueError("Export columns do not match this schema")
                    if table == "settings":
                        conn.execute("UPDATE settings SET budget_micro=?,paused=?,version=? WHERE id=1", (record["budget_micro"], record["paused"], record["version"]))
                    else:
                        # Identifiers come from PostgreSQL metadata, not submitted export data.
                        conn.execute("INSERT INTO " + table + " (" + ",".join(columns) + ") VALUES(" + ",".join("?" for _ in columns) + ")", tuple(record[c] for c in columns))
            if len(payload["tables"]["settings"]) != 1 or payload["tables"]["settings"][0]["id"] != 1 or not self._integrity(conn)["ok"]:
                raise ValueError("Export failed accounting validation; restore rolled back")
            conn.execute("SELECT setval(pg_get_serial_sequence('events','id'),coalesce((SELECT max(id) FROM events),1),EXISTS(SELECT 1 FROM events))")
        return {"restored": True, "tables": {t: len(payload["tables"][t]) for t in TABLES}}
