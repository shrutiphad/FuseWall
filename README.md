# Fusewall Local

A working local AI budget gateway, dashboard, and deterministic failure laboratory. No cloud account, model download, frontend build, or paid API is needed to use this version.

**Version 0.3.0 · single-owner prototype · simulated upstream only.** Costs are synthetic USD reference amounts, not real charges or verified savings. This version does not hold prepaid money or call a real LLM. Hosted availability is recorded in docs/VERCEL-SUPABASE.md.

## PostgreSQL / Vercel preparation in 0.3

Shared PostgreSQL storage, durable owner sessions/login counters, cross-worker lab coordination, expired-lease recovery, metadata export/restore, a FastAPI cloud entrypoint and deployment exclusions are implemented. They were tested on isolated local PostgreSQL. **The actual Supabase connection and Vercel preview passed hosted HTTP and desktop/mobile browser checks.** Production publication remains pending in this commit. See evidence/hosted-preview/ for the tested preview target.

See [Vercel/Supabase setup and rollout gates](docs/VERCEL-SUPABASE.md). The deployment requires a real persistent database, stable encrypted secrets and explicit hosts. Automatic Git deployments are disabled until a verified preview exists. The native SQLite mode remains runnable as before.

The expanded suite has 103 cases when `FUSEWALL_PG_TEST_URL` points to an isolated loopback PostgreSQL server. Without it, PostgreSQL-specific tests are explicitly skipped; do not describe that run as full cloud verification. Never point disposable schema tests at customer/Supabase databases.

## New in 0.2

- Preview one request without reserving allowance or generating traffic. Inspect organization, key and session headroom before running the lab.
- Usage insights attribute the current UTC admission month by client, workload and model, with suggested checks derived from actual synthetic records. Released holds are explicitly not labeled savings.
- Search all retained history, filter by workload/status, page through results, and open receipts with keyboard controls. Active receipts accurately show retained exposure.
- Reconciliation and its audit evidence commit atomically; integrity uses one consistent snapshot and checks per-request ledger amounts. Database waits run outside the event loop, and canceled database work is awaited before cleanup.
- Improved small-text contrast, mobile controls, skip navigation, dialog naming, stale-connection feedback and preview invalidation when inputs change.

See [architecture and orchestration](docs/ARCHITECTURE.md), [product decisions and current competitor evidence](docs/PRODUCT-DECISIONS.md), and [review plan](docs/IMPROVEMENT-PLAN.md).

## Start on this computer

Open a terminal in this project folder:

```powershell
python -m fusewall serve
```

Open **http://127.0.0.1:8765**. In a second terminal in the same folder:

```powershell
python -m fusewall token
```

Paste that local owner token into the unlock screen. `start.ps1` is an alternative launcher. The owner token is saved in `.fusewall/admin-token.txt`; treat it as a secret. The app never includes it in a URL. Owner sessions last eight hours and are invalidated when the server restarts.

An older demo may be running from the original build directory. The 0.2 review instance uses port 8766 and test-results/review-server, separate from a normal installation. Use `python -m fusewall token --data-dir test-results/review-server` with that instance. The server may already be running from the build session. Use that instance rather than starting a second server against the same data directory. Stop a foreground instance with Ctrl+C. For another independent instance use a different port **and** a different `--data-dir`.

## Install on another machine

Python 3.12+ is required; the tested environment is Windows x64 with Python 3.14.5. The browser UI uses native JavaScript modules, CSS, and SVG. Node is optional for developer syntax checks, not runtime.

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements-lock.txt
.venv\Scripts\python -m fusewall serve
```

Dependencies are free software; installation may need an internet connection. Nothing automatically downloads dependencies on startup. The lockfile records the resolved Windows test environment; another OS/Python version must be verified before deployment.

## Try it end to end

1. Unlock the workspace and create an API key. Choose a client/team, monthly budget, session budget, model permissions, call count and concurrency limit. Copy the key: only its hash is stored.
2. Open **Traffic lab**, select that key and choose **Preview one request**. This advisory snapshot creates no records or holds. Then run a normal or failure scenario. Use a small session budget and several parallel calls to observe early rejection.
3. Open **Request log**, search across all history and use its status/workload filters and pagination. Select a receipt button or row. Its decision receipt shows the policy version, reservation and settlement. Prompt and response text is not retained.
4. Open **Sessions** to inspect parent/session boundaries. An expired, call-limited or repeat-tripped session stays tripped across restarts. A new session still shares the parent key/organization allowance.
5. Use **Policy replay** to evaluate a different budget against stored records without new traffic or mutations.
6. Open **Usage insights** for current-admission-month attribution and suggested checks. Failed-work cost and unused holds are synthetic reference amounts, not measured savings. In **Reliability**, check accounting and download a consistent database backup. **Settings** provides an organization ceiling and emergency pause.

The running build includes explicitly labeled synthetic demo records generated through the application. A fresh data directory starts empty. The Overview's guided-demo action also creates and runs an actual local demo workload; it is not a static dashboard mockup.

## API

The supported subset is `GET /v1/models` and `POST /v1/chat/completions`, with system/user/assistant text messages, `max_tokens`, and optional SSE `stream`. It is shaped for compatible HTTP clients but does **not** implement the entire OpenAI API: tools, images, embeddings, sampling parameters and Responses are rejected, rather than silently ignored. No live provider/SDK compatibility is claimed from the simulator tests.

Example using Python (set `FUSEWALL_WORKLOAD_KEY` to a key you just created):

```python
import os
import httpx

response = httpx.post(
    "http://127.0.0.1:8765/v1/chat/completions",
    headers={
        "Authorization": "Bearer " + os.environ["FUSEWALL_WORKLOAD_KEY"],
        "X-Fusewall-Session": "my-first-run",
        "Idempotency-Key": "unique-request-001",
    },
    json={
        "model": "fusewall/mini",
        "messages": [{"role": "user", "content": "A synthetic test"}],
        "max_tokens": 64,
    },
)
print(response.status_code, response.json())
```

A repeated idempotency key returns 409 with the existing request ID, and never re-dispatches. The original response body is deliberately not stored/replayed. A changed payload under the same idempotency key also returns 409. Invalid/unknown fields are 422, invalid/revoked keys 401, disallowed models 403, budget/session blocks 402, rate/concurrency limits 429, and unavailable budget storage 503.

Synthetic input tokens are defined as eight overhead units plus the whitespace word count plus four units per message. Synthetic output tokens are emitted words. `fusewall/mini` rates are 20 micro-USD/input unit and 80/output unit; `fusewall/pro` rates are 100 and 400 respectively. These deliberately visible fixture rates do not represent any provider's published pricing. Each request snapshots its rate card; missing output limits default to an enforced maximum of 64 units.

The owner also has `POST /api/preview` with `{key_id, session_id, completion}`, `GET /api/insights`, `GET /api/requests?limit=50&offset=0&status=blocked&key_id=...&search=...`, and `GET /api/requests/{id}`. Search returns a matching total and page from one read snapshot. It treats search text literally. Preview uses current state, reserves nothing, and predicts one request only; concurrent traffic can change actual admission. Strict booleans and integer money are required.

Owner APIs use an HttpOnly SameSite=Strict cookie obtained from `/api/login`. All modifying owner calls require `X-Fusewall-Request: dashboard`; cross-origin writes are rejected. The owner can download the generated schema at `/api/schema` after login. Workload keys cannot use owner APIs or loosen ceilings. Per-key policy is immutable in this release; create a replacement key rather than changing existing session policy silently.

## Architecture and orchestration

```text
Static dashboard ── owner API ─┐
                             │
HTTP workload ── gateway ── policy + accounting ── local simulator
                             │
                          SQLite WAL
                             │
                    receipts / events / replay
```

FastAPI serves the UI and APIs in one process. Logical boundaries live in `models.py`, `policy.py`, `store.py`, `reporting.py`, `engine.py`, `runtime.py` and `app.py`. Preview and admission share a pure policy evaluator; reporting and integrity use bounded snapshot reads where coherence matters. The owner state overview is a live collection of summaries, not a forensic accounting snapshot. The lab coordinates bounded asynchronous workloads. No LLM supervisor, Redis queue, MongoDB, database server, local model, Kubernetes cluster or external notification service is required.

Every accepted call is reserved atomically against organization-month, key-month, and immutable session policy. A short `BEGIN IMMEDIATE` transaction checks `spent + held + proposed <= ceiling` and commits all holds. Generation runs outside transactions. Settlement appends one ledger entry per request and releases unused exposure in a single transaction. Rate/policy snapshots and period scope IDs are retained. All monetary arithmetic is integer micro-USD. Append-only triggers protect ledger entries from application updates/deletes.

SQLite is a local-disk, single-writer store. This is not a distributed gateway or multi-tenant hosted product. The single server lock prevents a second process from mistakenly recovering in-flight work owned by the first. Do not use multiple Uvicorn workers or network-mounted database files. Shared-company/high-availability deployment and a PostgreSQL implementation require separate engineering and validation.

## Reliability and limits

- At restart, undispatched reservations are canceled with no charge. Dispatched but unsettled calls become `outcome_unknown` and retain their full hold. An owner can resolve an uncertain receipt with a bounded amount and an audit reason. Never infer that a real provider billed zero merely because a connection disappeared.
- SSE cancellation settles only observed synthetic units. The live socket-disconnect check exercises this path. A future real provider must reconcile final usage conservatively. No automatic retries or cross-provider stream splicing occur.
- Rate and concurrent-request limits are checked in the same database authority. Repeat detection is optional and explicitly heuristic: repeated prompts can be valid.
- Pending/unknown exposure counts toward concurrency. Resolving a crashed request is an explicit owner action. There is no timed automatic release of uncertain holds.
- Storage is capped at 50,000 request records and 100 keys per installation. When full, new work is refused. Take a backup, stop the server and retain the complete data directory as an archive before starting a fresh one; there is no in-place ledger deletion/archiving command.
- Request bodies are limited to 64 KiB, synthetic context to 8,192 units, output to 1,024 units, and laboratory batches to 50 calls / 8 parallel operations. Only one lab batch runs at a time.
- No arbitrary upstream URLs, provider credentials, automatic downloads, external webhooks or network calls are implemented in the simulator. Host/origin checks and a restrictive script policy protect the loopback UI. Data directories and backups inherit OS access controls; Python's mode bits do not establish a Windows ACL security guarantee. Use an account-private directory.
- This is a prototype with automated evidence, not a certification or guarantee of production safety. Do not use it to protect real provider spending until an actual adapter, supported billing bounds and failure semantics have been validated.

## Verify

```powershell
python verify.py
python -m fusewall check
```

The original 61 backend tests include concurrent overspend attempts, cross-key parent budgets, idempotency races, rate-card and month snapshots, revocation before dispatch, crashes in a separate Python process, cancellation during reservation, stream cancellation, unavailable-authority rejection, randomized accounting sequences, append-only triggers, backup restore, origin/host rejection, validation, CSV formula safety and privilege separation. They use isolated workspace directories and synthetic inputs, not the running user's database.

`python tests/live_smoke.py` exercises the running server, creates labeled demonstration/verification keys and requests, tests an actual socket disconnect, and saves JSON evidence. It changes the local demonstration database; do not run it against a future customer environment.

`scripts/browser-check.cjs` is an optional Playwright/Edge check for owner login, key creation, lab, receipts, replay, integrity and mobile overflow. It requires a separately available Playwright installation; no browser/package download is automatic. Set `FUSEWALL_PLAYWRIGHT` to its module path if not locally installed. The browser check uses the local generated owner token without printing it.

For isolated native testing, use a separate server and directory, then run the mutating HTTP and browser checks **sequentially**:

```powershell
python -m fusewall serve --port 8766 --data-dir test-results/review-server
# In another terminal:
$env:FUSEWALL_TEST_URL = 'http://127.0.0.1:8766'
$env:FUSEWALL_TEST_DATA_DIR = (Resolve-Path test-results/review-server).Path
python tests/live_smoke.py
# Set FUSEWALL_PLAYWRIGHT to an installed Playwright module before this optional check:
node scripts/browser-check.cjs
```

The 0.2 regression cases cover atomic audit rollback, racing reconciliation, integrity during a concurrent settlement, mismatched ledger entries with matching totals, preview non-mutation/admission parity, older-record pagination/search, month attribution, lab child cleanup, repeated cancellation, strict contracts and event-loop responsiveness. This is not a throughput benchmark or accessibility certification.

Evidence is saved in `evidence/`, including JSON outcomes and desktop/mobile screenshots. See `IMPLEMENTATION.md` for implemented scope and remaining work.

## Hosting and deployment

**Verified deployment:** the native single-process HTTP application on this computer at `127.0.0.1:8765`. Its data persists in `.fusewall/`. The computer must remain running for the service to be available. This is the zero-additional-spend hosting arrangement.

**Optional, not verified here:** `Dockerfile` and `compose.yaml` package the same server and publish it only to host loopback. The Docker daemon was unavailable during this build, so no image-build or container-runtime result is claimed. When an appropriately licensed Docker environment is available:

```powershell
docker compose up --build -d
docker compose exec fusewall python -m fusewall token --data-dir /data
```

Public cloud hosting, a public domain, HTTPS reverse-proxy configuration, shared-user access and real provider integration are **not deployed**. They are not prerequisites for using the local product. A company can evaluate this package on existing infrastructure, but its usage and security requirements must be assessed before live production adoption. The builder does not fund provider traffic.

## Backup, restore and rollback

Use the Reliability button or `python -m fusewall backup` for a SQLite-consistent snapshot. Preserve the fingerprint key, owner token and OS access restrictions separately if you need to preserve an installation's identity. A database snapshot alone restores records and hashed workload keys, not the owner's login credential.

Restore only while the destination server is stopped, into a **new** data directory: copy the snapshot as `fusewall.db`, then run `python -m fusewall check --data-dir <new-directory>`. Starting that directory generates a new owner token if absent and conservatively recovers outstanding work. Never overwrite a running database or copy only its active main file while ignoring WAL state. The automated restore test uses a separate directory.

Before upgrading, stop traffic, capture a consistent backup and retain the previous application release. Rollback requires an application/schema-compatible snapshot, not just older source code. Database schema version 1 is checked; a newer schema is refused. Docker volume removal is intentionally absent from normal instructions.

## Costs and future work

No money was spent or new paid account activated to build/test this version. It uses the existing computer, internet, Python packages and current assistant access. Additional users do not receive free third-party inference through it.

Real-provider/BYOK support, supported SDK matrices, PostgreSQL/shared deployment, LLM analyst features and stronger production operations remain future work. A useful next integration can use an already available local inference server or a pilot company's own provider account; neither is automatically connected here.

## Portable source release

`python scripts/package.py` creates `dist/fusewall-local-v0.3.0.zip` and refreshes the source `RELEASE-MANIFEST.json`. Use `--output <path>` for a different destination. It excludes runtime credentials, databases, caches and test scratch data; verifies every archive member against SHA-256; and includes the manifest exactly once. The archive does not migrate an installation's runtime data. Preserve any needed database/identity backup separately.
