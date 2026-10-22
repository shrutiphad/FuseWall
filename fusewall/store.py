"""SQLite is the authority: authorize + reserve and settle in short transactions.

No network operation happens inside a transaction. One connection per operation;
BEGIN IMMEDIATE serializes writers across threads/processes on one local disk.
"""

import hashlib
import hmac
import json
import secrets
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .models import KeyCreate
from .policy import evaluate

RATES = {
    "fusewall/mini": {"input_micro": 20, "output_micro": 80},
    "fusewall/pro": {"input_micro": 100, "output_micro": 400},
}
RATE_VERSION = "simulation-v1"


class Fault(Exception):
    def __init__(self, status: int, code: str, message: str, details=None):
        self.status, self.code, self.message = status, code, message
        self.details = details or {}
        super().__init__(message)


def uid(prefix=""):
    return prefix + secrets.token_hex(12)


def digest(text):
    return hashlib.sha256(text.encode()).hexdigest()


def month(now):
    return datetime.fromtimestamp(now, timezone.utc).strftime("%Y-%m")


def tokens(messages):
    # A declared synthetic accounting rule, not a real provider tokenizer.
    return 8 + sum(len(m["content"].split()) + 4 for m in messages)


class Store:
    def __init__(self, directory):
        self.directory = Path(directory).resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / "fusewall.db"
        self.admin_path = self.directory / "admin-token.txt"
        self.secret_path = self.directory / "fingerprint.key"
        for path, prefix in [(self.admin_path, "fw_owner_"), (self.secret_path, "")]:
            if not path.exists():
                try:
                    with path.open("x", encoding="utf8") as file:
                        file.write(prefix + secrets.token_urlsafe(36))
                    path.chmod(0o600)
                except FileExistsError:
                    pass
        self.admin_hash = digest(self.admin_path.read_text(encoding="utf8").strip())
        self.fingerprint_secret = self.secret_path.read_bytes()
        self.initialize()

    def connect(self):
        conn = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA synchronous=FULL")
        return conn

    @contextmanager
    def transaction(self):
        conn = self.connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.execute("COMMIT")
        except BaseException:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()

    def read(self, sql, params=()):
        conn = self.connect()
        try:
            return [dict(r) for r in conn.execute(sql, params).fetchall()]
        finally:
            conn.close()

    @contextmanager
    def snapshot(self):
        """One WAL read snapshot; concurrent writers may continue."""
        conn = self.connect()
        try:
            conn.execute("BEGIN")
            yield conn
        finally:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            conn.close()

    def initialize(self):
        conn = self.connect()
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            if version > 1:
                raise RuntimeError("Database was created by a newer Fusewall version")
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS settings (
                    id INTEGER PRIMARY KEY CHECK(id=1),
                    budget_micro INTEGER NOT NULL CHECK(budget_micro>=0),
                    paused INTEGER NOT NULL DEFAULT 0, version INTEGER NOT NULL DEFAULT 1
                );
                INSERT OR IGNORE INTO settings(id,budget_micro) VALUES(1,10000000);
                CREATE TABLE IF NOT EXISTS keys (
                    id TEXT PRIMARY KEY, token_hash TEXT NOT NULL UNIQUE,
                    name TEXT NOT NULL, client TEXT NOT NULL, active INTEGER NOT NULL,
                    policy TEXT NOT NULL, created REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS buckets (
                    scope TEXT PRIMARY KEY, ceiling INTEGER NOT NULL CHECK(ceiling>=0),
                    spent INTEGER NOT NULL DEFAULT 0 CHECK(spent>=0),
                    held INTEGER NOT NULL DEFAULT 0 CHECK(held>=0),
                    CHECK(spent+held<=ceiling)
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY, external_id TEXT NOT NULL, key_id TEXT NOT NULL REFERENCES keys(id),
                    started REAL NOT NULL, status TEXT NOT NULL DEFAULT 'active',
                    policy TEXT NOT NULL, calls INTEGER NOT NULL DEFAULT 0,
                    last_fingerprint TEXT, repetitions INTEGER NOT NULL DEFAULT 0,
                    UNIQUE(key_id,external_id)
                );
                CREATE TABLE IF NOT EXISTS requests (
                    id TEXT PRIMARY KEY, key_id TEXT NOT NULL REFERENCES keys(id),
                    session_id TEXT NOT NULL REFERENCES sessions(id), model TEXT NOT NULL,
                    status TEXT NOT NULL, reason TEXT NOT NULL, reserved INTEGER NOT NULL,
                    actual INTEGER NOT NULL DEFAULT 0, input_tokens INTEGER NOT NULL,
                    output_tokens INTEGER NOT NULL DEFAULT 0, created REAL NOT NULL,
                    finished REAL, elapsed_ms INTEGER, scopes TEXT NOT NULL,
                    fingerprint TEXT NOT NULL, idempotency TEXT, rate_version TEXT NOT NULL,
                    policy_version INTEGER NOT NULL, scenario TEXT NOT NULL, rates TEXT NOT NULL,
                    UNIQUE(key_id,idempotency)
                );
                CREATE INDEX IF NOT EXISTS requests_created ON requests(created DESC);
                CREATE INDEX IF NOT EXISTS requests_key_status ON requests(key_id,status,created);
                CREATE INDEX IF NOT EXISTS requests_session ON requests(session_id,created);
                CREATE TABLE IF NOT EXISTS ledger (
                    id TEXT PRIMARY KEY, request_id TEXT NOT NULL UNIQUE REFERENCES requests(id),
                    amount INTEGER NOT NULL CHECK(amount>=0), created REAL NOT NULL,
                    provenance TEXT NOT NULL CHECK(provenance='simulated')
                );
                CREATE TRIGGER IF NOT EXISTS ledger_no_update BEFORE UPDATE ON ledger
                    BEGIN SELECT RAISE(ABORT,'ledger is append-only'); END;
                CREATE TRIGGER IF NOT EXISTS ledger_no_delete BEFORE DELETE ON ledger
                    BEGIN SELECT RAISE(ABORT,'ledger is append-only'); END;
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, created REAL NOT NULL,
                    kind TEXT NOT NULL, message TEXT NOT NULL, reference TEXT
                );
                PRAGMA user_version=1;
            """)
        finally:
            conn.close()

    @staticmethod
    def event(conn, kind, message, reference=None):
        conn.execute("INSERT INTO events(created,kind,message,reference) VALUES(?,?,?,?)",
                     (time.time(), kind, message, reference))

    def create_key(self, specification: KeyCreate):
        key_id, token = uid("key_"), "fw_test_" + secrets.token_urlsafe(32)
        data = specification.model_dump()
        with self.transaction() as conn:
            if conn.execute("SELECT count(*) FROM keys").fetchone()[0] >= 100:
                raise Fault(409, "key_limit", "This local installation supports up to 100 keys.")
            conn.execute("INSERT INTO keys VALUES(?,?,?,?,?,?,?)",
                         (key_id, digest(token), data["name"], data["client"], 1, json.dumps(data), time.time()))
            self.event(conn, "key_created", f"Created {data['name']}", key_id)
        return {"id": key_id, "token": token, **data, "active": True}

    def authenticate(self, token):
        rows = self.read("SELECT id,active FROM keys WHERE token_hash=?", (digest(token),))
        if not rows or not rows[0]["active"]:
            raise Fault(401, "invalid_key", "The workload key is invalid or revoked.")
        return rows[0]["id"]

    def patch_key(self, key_id, active):
        with self.transaction() as conn:
            if not conn.execute("UPDATE keys SET active=? WHERE id=?", (int(active), key_id)).rowcount:
                raise Fault(404, "not_found", "Key not found.")
            self.event(conn, "key_status", "Key enabled" if active else "Key revoked", key_id)

    def settings(self):
        return self.read("SELECT * FROM settings WHERE id=1")[0]

    def update_settings(self, budget_micro, paused):
        scope = "org:" + month(time.time())
        with self.transaction() as conn:
            row = conn.execute("SELECT * FROM buckets WHERE scope=?", (scope,)).fetchone()
            if row and row["spent"] + row["held"] > budget_micro:
                raise Fault(409, "committed_budget", "The new ceiling is below spent + reserved exposure.")
            conn.execute("UPDATE settings SET budget_micro=?,paused=?,version=version+1 WHERE id=1",
                         (budget_micro, int(paused)))
            conn.execute("UPDATE buckets SET ceiling=? WHERE scope=?", (budget_micro, scope))
            self.event(conn, "policy_changed", "Owner updated organization policy")

    def reserve(self, key_id, session_external, body, scenario="normal", idempotency=None, now=None):
        now = time.time() if now is None else now
        model = body["model"]
        if model not in RATES:
            raise Fault(400, "unpriced_model", "Unknown or unpriced model.")
        input_tokens = tokens(body["messages"])
        if input_tokens > 8192:
            raise Fault(413, "context_limit", "Synthetic input token limit exceeded.")
        reservation = input_tokens * RATES[model]["input_micro"] + body["max_tokens"] * RATES[model]["output_micro"]
        canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        fingerprint = hmac.new(self.fingerprint_secret, canonical.encode(), hashlib.sha256).hexdigest()
        rejection = None
        result = None
        with self.transaction() as conn:
            key = conn.execute("SELECT * FROM keys WHERE id=?", (key_id,)).fetchone()
            if not key or not key["active"]:
                raise Fault(401, "invalid_key", "The workload key is invalid or revoked.")
            policy = json.loads(key["policy"])
            config = conn.execute("SELECT * FROM settings WHERE id=1").fetchone()
            if idempotency:
                old = conn.execute("SELECT * FROM requests WHERE key_id=? AND idempotency=?", (key_id, idempotency)).fetchone()
                if old:
                    raise Fault(409, "idempotency_replay" if old["fingerprint"] == fingerprint else "idempotency_conflict",
                                "This key has already submitted that idempotency key. No new upstream call was made.", {"request_id": old["id"]})
            # Retain a strict local history bound rather than letting an idle laptop fill its disk.
            if conn.execute("SELECT count(*) FROM requests").fetchone()[0] >= 50_000:
                raise Fault(503, "history_capacity", "Local history capacity reached. Back up and archive this installation.")
            session = conn.execute("SELECT * FROM sessions WHERE key_id=? AND external_id=?", (key_id, session_external)).fetchone()
            if not session:
                sid = uid("sess_")
                conn.execute("INSERT INTO sessions(id,external_id,key_id,started,policy) VALUES(?,?,?,?,?)",
                             (sid, session_external, key_id, now, json.dumps(policy)))
                session = conn.execute("SELECT * FROM sessions WHERE id=?", (sid,)).fetchone()
            sid = session["id"]
            session_policy = json.loads(session["policy"])
            scopes = [("org:" + month(now), config["budget_micro"]),
                      ("key:" + key_id + ":" + month(now), policy["budget_micro"]),
                      ("session:" + sid, session_policy["session_budget_micro"])]
            for scope, ceiling in scopes:
                conn.execute("INSERT OR IGNORE INTO buckets(scope,ceiling) VALUES(?,?)", (scope, ceiling))
            reason, status = "authorized", 200
            repetitions = session["repetitions"] + 1 if fingerprint == session["last_fingerprint"] else 1
            active = conn.execute("SELECT count(*) FROM requests WHERE key_id=? AND status IN ('reserved','dispatching','outcome_unknown')", (key_id,)).fetchone()[0]
            recent = conn.execute("SELECT count(*) FROM requests WHERE key_id=? AND created>? AND status!='blocked'", (key_id, now - 60)).fetchone()[0]
            buckets = [dict(conn.execute("SELECT * FROM buckets WHERE scope=?", (scope,)).fetchone(),
                            kind=("organization" if scope.startswith("org:") else "key" if scope.startswith("key:") else "session"))
                       for scope, _ in scopes]
            reason, status = evaluate(config, policy, session, session_policy, now, repetitions, active, recent, buckets, reservation, model)
            rid = uid("req_")
            conn.execute("""INSERT INTO requests(id,key_id,session_id,model,status,reason,reserved,
                input_tokens,created,scopes,fingerprint,idempotency,rate_version,policy_version,scenario,rates)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (rid, key_id, sid, model, "reserved" if status == 200 else "blocked", reason,
                 reservation if status == 200 else 0, input_tokens, now, json.dumps([s for s, _ in scopes]),
                 fingerprint, idempotency, RATE_VERSION, config["version"], scenario, json.dumps(RATES[model])))
            if status != 200:
                if reason in ("repeat_guard", "session_call_limit", "session_expired"):
                    conn.execute("UPDATE sessions SET status='tripped' WHERE id=?", (sid,))
                self.event(conn, "blocked", "Request blocked: " + reason, rid)
                rejection = Fault(status, reason, "The fuse blocked this request before upstream dispatch.",
                                  {"request_id": rid, "session_id": sid, "required_micro": reservation})
            else:
                for scope, _ in scopes:
                    conn.execute("UPDATE buckets SET held=held+? WHERE scope=?", (reservation, scope))
                conn.execute("UPDATE sessions SET calls=calls+1,last_fingerprint=?,repetitions=? WHERE id=?", (fingerprint, repetitions, sid))
                result = {"id": rid, "session_id": sid, "input_tokens": input_tokens,
                          "reserved_micro": reservation, "model": model, "created": now}
        if rejection:
            raise rejection
        return result

    def dispatch(self, request_id):
        rejected = False
        with self.transaction() as conn:
            row = conn.execute("SELECT r.*,k.active FROM requests r JOIN keys k ON k.id=r.key_id WHERE r.id=?", (request_id,)).fetchone()
            if not row or row["status"] != "reserved":
                raise Fault(409, "invalid_state", "Request cannot be dispatched in its current state.")
            if not row["active"] or conn.execute("SELECT paused FROM settings WHERE id=1").fetchone()[0]:
                for scope in json.loads(row["scopes"]):
                    conn.execute("UPDATE buckets SET held=held-? WHERE scope=?", (row["reserved"], scope))
                conn.execute("UPDATE requests SET status='canceled',reason='authority_changed',finished=? WHERE id=?", (time.time(), request_id))
                self.event(conn, "canceled", "Owner paused or revoked access before dispatch", request_id)
                rejected = True
            else:
                conn.execute("UPDATE requests SET status='dispatching' WHERE id=?", (request_id,))
        if rejected:
            raise Fault(402, "authority_changed", "Owner paused or revoked this request before dispatch.")

    def finish(self, request_id, output_tokens, outcome="settled", actual_override=None, *, resolution_reason=None):
        if outcome not in ("settled", "failed", "canceled"):
            raise ValueError("Invalid terminal outcome")
        with self.transaction() as conn:
            row = conn.execute("SELECT * FROM requests WHERE id=?", (request_id,)).fetchone()
            if not row:
                raise Fault(404, "not_found", "Request not found.")
            if resolution_reason is not None and row["status"] != "outcome_unknown":
                raise Fault(409, "not_uncertain", "Only an uncertain request can be resolved.")
            if row["status"] not in ("dispatching", "reserved", "outcome_unknown"):
                return dict(row)
            rates = json.loads(row["rates"])
            actual = actual_override if actual_override is not None else (row["input_tokens"] * rates["input_micro"] + output_tokens * rates["output_micro"])
            if not isinstance(actual, int) or not 0 <= actual <= row["reserved"]:
                raise Fault(409, "usage_exceeds_reservation", "Observed usage cannot be settled within the authorized hold; hold retained.")
            for scope in json.loads(row["scopes"]):
                conn.execute("UPDATE buckets SET held=held-?,spent=spent+? WHERE scope=?", (row["reserved"], actual, scope))
            now = time.time()
            conn.execute("INSERT INTO ledger VALUES(?,?,?,?,?)", (uid("entry_"), request_id, actual, now, "simulated"))
            conn.execute("UPDATE requests SET status=?,reason=?,actual=?,output_tokens=?,finished=?,elapsed_ms=? WHERE id=?",
                         (outcome, outcome, actual, output_tokens, now, max(0, round((now-row["created"])*1000)), request_id))
            if outcome != "settled":
                self.event(conn, outcome, "Synthetic request ended: " + outcome, request_id)
            if resolution_reason is not None:
                self.event(conn, "manual_resolution", resolution_reason, request_id)
            return {"id": request_id, "status": outcome, "actual": actual, "reserved": row["reserved"]}

    def recover(self):
        with self.transaction() as conn:
            reserved = conn.execute("SELECT id FROM requests WHERE status='reserved'").fetchall()
            for row in reserved:
                request = conn.execute("SELECT * FROM requests WHERE id=?", (row[0],)).fetchone()
                for scope in json.loads(request["scopes"]):
                    conn.execute("UPDATE buckets SET held=held-? WHERE scope=?", (request["reserved"], scope))
                conn.execute("UPDATE requests SET status='canceled',reason='restart_before_dispatch',finished=? WHERE id=?", (time.time(), row[0]))
            count = conn.execute("UPDATE requests SET status='outcome_unknown',reason='restart_during_dispatch' WHERE status='dispatching'").rowcount
            if count or reserved:
                self.event(conn, "recovery", f"Restart recovered {len(reserved)} undispatched requests; retained {count} uncertain holds")
            return {"canceled": len(reserved), "unknown": count}

    def resolve(self, request_id, actual, reason):
        return self.finish(request_id, 0, "failed", actual, resolution_reason=reason)

    def list_keys(self):
        result = self.read("SELECT id,name,client,active,policy,created FROM keys ORDER BY created DESC")
        buckets = {b["scope"]: b for b in self.read("SELECT * FROM buckets")}
        for row in result:
            policy = json.loads(row.pop("policy"))
            row.update(policy)
            bucket = buckets.get("key:" + row["id"] + ":" + month(time.time()), {})
            row.update(spent_micro=bucket.get("spent", 0), held_micro=bucket.get("held", 0))
        return result

    def sessions(self):
        return self.read("""SELECT s.id,s.external_id,s.key_id,s.started,s.status,s.calls,s.policy,k.name AS key_name,
            b.spent,b.held,b.ceiling FROM sessions s JOIN keys k ON k.id=s.key_id
            LEFT JOIN buckets b ON b.scope='session:'||s.id ORDER BY s.started DESC LIMIT 200""")

    def request_list(self, limit=100, offset=0, status=None):
        sql = "SELECT r.*,k.name AS key_name,k.client,s.external_id FROM requests r JOIN keys k ON k.id=r.key_id JOIN sessions s ON s.id=r.session_id"
        params = []
        if status:
            sql += " WHERE r.status=?"
            params.append(status)
        sql += " ORDER BY r.created DESC LIMIT ? OFFSET ?"
        rows = self.read(sql, (*params, limit, offset))
        for row in rows:
            row.pop("fingerprint", None)
            row.pop("idempotency", None)
        return rows

    def overview(self):
        config = self.settings()
        current = self.read("SELECT * FROM buckets WHERE scope=?", ("org:" + month(time.time()),))
        b = current[0] if current else {"spent": 0, "held": 0, "ceiling": config["budget_micro"]}
        counts = self.read("SELECT status,count(*) AS n FROM requests GROUP BY status")
        states = {r["status"]: r["n"] for r in counts}
        return {"mode": "simulation", "period": month(time.time()), "budget_micro": b["ceiling"],
                "spent_micro": b["spent"], "held_micro": b["held"],
                "remaining_micro": b["ceiling"]-b["spent"]-b["held"], "paused": bool(config["paused"]),
                "requests": sum(states.values()), "blocked": states.get("blocked", 0),
                "uncertain": states.get("outcome_unknown", 0), "states": states,
                "clients": self.read("SELECT k.client,count(*) AS requests,sum(r.actual) AS cost FROM requests r JOIN keys k ON k.id=r.key_id GROUP BY k.client ORDER BY cost DESC"),
                "series": self.read("SELECT substr(datetime(created,'unixepoch'),1,13) AS hour,sum(actual) AS cost,count(*) AS requests FROM requests GROUP BY hour ORDER BY hour DESC LIMIT 24")[::-1]}

    def replay(self, budget, limit):
        rows = self.read("SELECT id,reserved,actual,status FROM requests WHERE status!='blocked' ORDER BY created LIMIT ?", (limit,))
        spent, allowed, decisions = 0, 0, []
        for row in rows:
            authorized = spent + row["reserved"] <= budget
            settled = row["status"] in ("settled", "failed", "canceled")
            exposure = row["actual"] if settled else row["reserved"]
            if authorized:
                spent += exposure
                allowed += 1
            decisions.append({"request_id": row["id"], "allowed": authorized, "reserved_micro": row["reserved"], "exposure_micro": exposure})
        return {"mode": "offline_replay", "budget_micro": budget, "exposure_micro": spent,
                "allowed": allowed, "blocked": len(rows)-allowed, "decisions": decisions,
                "assumption": "Sequential replay; unresolved requests consume their full reservation. No provider calls or policy changes."}

    def backup(self):
        folder = self.directory / "backups"
        folder.mkdir(exist_ok=True)
        path = folder / (uid("fusewall-") + ".db")
        source, target = self.connect(), sqlite3.connect(path)
        try:
            source.backup(target)
            if target.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise RuntimeError("Backup integrity check failed")
        finally:
            source.close()
            target.close()
        path.chmod(0o600)
        return path

    def integrity(self):
        with self.snapshot() as conn:
            return self._integrity(conn)

    def _integrity(self, conn):
        def read(sql):
            return [dict(row) for row in conn.execute(sql)]
        buckets = read("SELECT * FROM buckets")
        ledger = read("SELECT coalesce(sum(amount),0) AS total FROM ledger")[0]["total"]
        actual = read("SELECT coalesce(sum(actual),0) AS total FROM requests")[0]["total"]
        violations = []
        sums = {}
        for row in read("SELECT reserved,actual,status,scopes FROM requests"):
            for scope in json.loads(row["scopes"]):
                total = sums.setdefault(scope, [0, 0])
                total[0] += row["actual"]
                if row["status"] in ("reserved", "dispatching", "outcome_unknown"):
                    total[1] += row["reserved"]
        for bucket in buckets:
            spent, held = sums.get(bucket["scope"], [0, 0])
            if bucket["spent"] != spent or bucket["held"] != held:
                violations.append(bucket["scope"])
        missing = sorted(set(sums) - {b["scope"] for b in buckets})
        mismatches = read("""SELECT r.id FROM requests r LEFT JOIN ledger l ON l.request_id=r.id
            WHERE (l.request_id IS NOT NULL AND (l.amount!=r.actual OR r.status NOT IN ('settled','failed','canceled')))
            OR (r.actual>0 AND l.request_id IS NULL)
            OR (r.status IN ('settled','failed') AND l.request_id IS NULL)""")
        return {"ok": not violations and not missing and not mismatches and ledger == actual, "ledger_micro": ledger,
                "request_micro": actual, "inconsistent_scopes": violations + missing,
                "inconsistent_requests": [r["id"] for r in mismatches]}
