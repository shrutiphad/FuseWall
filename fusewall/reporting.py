"""Read-only evaluation and reporting. Never dispatch or mutate budget authority."""

import hashlib
import hmac
import json
import time

from .policy import evaluate
from .store import Fault, RATES, RATE_VERSION, month, tokens

STATUSES = ("settled", "blocked", "failed", "reserved", "dispatching", "outcome_unknown", "canceled")
JOIN = "FROM requests r JOIN keys k ON k.id=r.key_id JOIN sessions s ON s.id=r.session_id"


def rows(conn, sql, params=()):
    return [dict(row) for row in conn.execute(sql, params)]


def sanitize(records):
    for row in records:
        row.pop("fingerprint", None)
        row.pop("idempotency", None)
    return records


def request_page(store, limit=50, offset=0, status=None, key_id=None, search=""):
    clauses, params = [], []
    if status:
        if status not in STATUSES:
            raise Fault(400, "invalid_status", "Unknown request status.")
        clauses.append("r.status=?")
        params.append(status)
    if key_id:
        clauses.append("r.key_id=?")
        params.append(key_id)
    if search:
        # instr treats %, _ and quotes literally, with SQL parameters throughout.
        clauses.append("instr(lower(r.id||' '||k.name||' '||k.client||' '||s.external_id),lower(?))>0")
        params.append(search)
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    with store.snapshot() as conn:
        total = conn.execute("SELECT count(*) " + JOIN + where, params).fetchone()[0]
        records = rows(conn, "SELECT r.*,k.name AS key_name,k.client,s.external_id " + JOIN + where +
                       " ORDER BY r.created DESC,r.id DESC LIMIT ? OFFSET ?", (*params, limit, offset))
    return {"requests": sanitize(records), "total": total, "limit": limit, "offset": offset}


def receipt(store, request_id):
    with store.snapshot() as conn:
        records = rows(conn, "SELECT r.*,k.name AS key_name,k.client,s.external_id " + JOIN + " WHERE r.id=?", (request_id,))
        if not records:
            raise Fault(404, "not_found", "Request not found.")
        result = sanitize(records)[0]
        result["events"] = rows(conn, "SELECT created,kind,message FROM events WHERE reference=? ORDER BY id", (request_id,))
    return result


def preview(store, key_id, session_id, body, now=None):
    now = time.time() if now is None else now
    model, units = body["model"], tokens(body["messages"])
    if units > 8192:
        raise Fault(413, "context_limit", "Synthetic input token limit exceeded.")
    required = units * RATES[model]["input_micro"] + body["max_tokens"] * RATES[model]["output_micro"]
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    fingerprint = hmac.new(store.fingerprint_secret, canonical.encode(), hashlib.sha256).hexdigest()
    with store.snapshot() as conn:
        key = conn.execute("SELECT * FROM keys WHERE id=?", (key_id,)).fetchone()
        if not key or not key["active"]:
            raise Fault(401, "invalid_key", "The workload key is invalid or revoked.")
        if conn.execute("SELECT count(*) FROM requests").fetchone()[0] >= 50_000:
            raise Fault(503, "history_capacity", "Local history capacity reached. Back up and archive this installation.")
        policy = json.loads(key["policy"])
        config = conn.execute("SELECT * FROM settings WHERE id=1").fetchone()
        session = conn.execute("SELECT * FROM sessions WHERE key_id=? AND external_id=?", (key_id, session_id)).fetchone()
        session = dict(session) if session else {"id": None, "started": now, "status": "active", "calls": 0,
                                                "policy": key["policy"], "repetitions": 0, "last_fingerprint": None}
        session_policy = json.loads(session["policy"])
        buckets = []
        scopes = [("organization", "org:" + month(now), config["budget_micro"]),
                  ("key", "key:" + key_id + ":" + month(now), policy["budget_micro"]),
                  ("session", "session:" + str(session["id"]), session_policy["session_budget_micro"])]
        for kind, scope, ceiling in scopes:
            found = conn.execute("SELECT * FROM buckets WHERE scope=?", (scope,)).fetchone()
            b = dict(found) if found else {"ceiling": ceiling, "spent": 0, "held": 0}
            remaining = b["ceiling"] - b["spent"] - b["held"]
            buckets.append({"kind": kind, "ceiling": b["ceiling"], "spent": b["spent"], "held": b["held"],
                            "remaining": remaining, "fits": required <= remaining})
        active = conn.execute("SELECT count(*) FROM requests WHERE key_id=? AND status IN ('reserved','dispatching','outcome_unknown')", (key_id,)).fetchone()[0]
        recent = conn.execute("SELECT count(*) FROM requests WHERE key_id=? AND created>? AND status!='blocked'", (key_id, now-60)).fetchone()[0]
        repetitions = session["repetitions"]+1 if fingerprint == session["last_fingerprint"] else 1
        reason, status = evaluate(config, policy, session, session_policy, now, repetitions, active, recent, buckets, required, model)
    return {"mode": "advisory_preview", "allowed": status == 200, "reason": reason, "status": status,
            "required_micro": required, "input_tokens": units, "max_output_tokens": body["max_tokens"],
            "rate_version": RATE_VERSION, "scopes": buckets,
            "assumption": "One request against current state. Reserves nothing; actual admission rechecks every rule. Parallel calls can change the result."}


def insights(store):
    period = month(time.time())
    where = " WHERE EXISTS (SELECT 1 FROM json_each(r.scopes) WHERE value=?)"
    params = ("org:" + period,)
    with store.snapshot() as conn:
        totals = rows(conn, """SELECT count(*) AS requests,coalesce(sum(actual),0) AS actual_micro,
            coalesce(sum(CASE WHEN status IN ('failed','canceled') THEN actual ELSE 0 END),0) AS failed_cost_micro,
            coalesce(sum(CASE WHEN status IN ('settled','failed','canceled') THEN reserved-actual ELSE 0 END),0) AS released_micro,
            sum(CASE WHEN status='blocked' THEN 1 ELSE 0 END) AS blocked,
            sum(CASE WHEN status='outcome_unknown' THEN 1 ELSE 0 END) AS uncertain
            FROM requests r""" + where, params)[0]
        totals = {k: v or 0 for k, v in totals.items()}
        breakdown = {}
        for dimension, column in (("workloads", "k.name"), ("clients", "k.client"), ("models", "r.model")):
            group = "r.key_id" if dimension == "workloads" else column
            breakdown[dimension] = rows(conn, f"""SELECT {column} AS name,count(*) AS requests,sum(r.actual) AS actual_micro,
                sum(CASE WHEN r.status='blocked' THEN 1 ELSE 0 END) AS blocked
                FROM requests r JOIN keys k ON k.id=r.key_id {where}
                GROUP BY {group} ORDER BY actual_micro DESC,name LIMIT 20""", params)
        reasons = rows(conn, "SELECT reason,count(*) AS count FROM requests r" + where + " AND status='blocked' GROUP BY reason ORDER BY count DESC LIMIT 10", params)
        bucket = conn.execute("SELECT * FROM buckets WHERE scope=?", params).fetchone()
        capacity = conn.execute("SELECT count(*) FROM requests").fetchone()[0]
    actions = []
    if totals["uncertain"]:
        actions.append({"title": "Reconcile retained holds", "detail": "Uncertain outcomes retain budget. Inspect receipts and record evidence before releasing exposure.", "route": "requests"})
    if totals["failed_cost_micro"]:
        actions.append({"title": "Inspect failed-work usage", "detail": "Partial or canceled synthetic generations used allowance. Check failure scenarios before changing budgets.", "route": "requests"})
    if bucket and bucket["spent"] + bucket["held"] >= bucket["ceiling"] * .8:
        actions.append({"title": "Review committed allowance", "detail": "At least 80% is spent or held. Preview a request and inspect its limiting scope before increasing limits.", "route": "lab"})
    if reasons:
        actions.append({"title": "Explain the leading block", "detail": reasons[0]["reason"].replace("_", " ") + " is the most frequent stop. Preview the same session to inspect current rules.", "route": "lab"})
    if not actions:
        actions.append({"title": "Validate a failure scenario", "detail": "Use the traffic lab to exercise partial usage and concurrent caps. No measured savings or output quality is inferred.", "route": "lab"})
    return {"mode": "simulation", "period": period, "totals": totals, **breakdown, "block_reasons": reasons,
            "actions": actions, "history_used": capacity, "history_limit": 50_000,
            "assumption": "Current UTC admission month; top 20 groups per breakdown. Released allowance is unused authorization, not money saved. No output-quality evaluation."}
