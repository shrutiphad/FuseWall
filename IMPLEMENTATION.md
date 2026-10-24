# Deployment verified — 24 October 2026

The single-owner simulation is live at https://fusewall.vercel.app with persistent Supabase PostgreSQL. Actual public HTTP, desktop/mobile browser, accounting, privileges and redeployment persistence checks passed. Deployed source: 52afe3d8d0fcdcc44bf04712b55736faea09be8e. See docs/VERCEL-SUPABASE.md and evidence/production/ for scope and evidence. No real LLM provider or company production-readiness claim is included. Earlier implementation notes below are historical.

---

# 0.3.0 shared-storage preparation

22 October 2026. Supabase was selected by the user. The PostgreSQL adapter, private-schema migration, durable owner sessions/rate counters, cross-instance lab lease, expiry-gated recovery, explicit HTTPS cloud entrypoint and metadata export/empty-schema restore are implemented. Native SQLite stays supported. Vercel refuses SQLite fallback.

Verification: 103 tests passed with no failures/errors/skips using isolated local PostgreSQL plus the native backend; nine desktop/mobile browser routes passed on a separate native 0.3 instance. The user's Supabase project is not connected, the database URL is absent from Vercel, and public deployment remains incomplete. Preview/production owner and fingerprint secrets/schema names are configured encrypted on the existing Hobby project. No paid services were activated. See docs/VERCEL-SUPABASE.md for actual rollout gates and limitations.

The earlier version records below are historical evidence, not current hosted-deployment claims.

---

# Release 0.2.0 review update

Date: 22 October 2026. Canonical working source: `C:\Users\ADMIN\Documents\RELAY\codebase`. Additional spending: INR 0. Scope remains local, single-owner, simulation only.

## Implemented in this pass

- Shared pure admission rules and a non-mutating, single-request advisory preview with scope headroom.
- Current UTC admission-month usage insights by workload/client/model, failed-work usage, released allowance and deterministic suggested checks. No quality/savings claims.
- Server-side all-history search, status/workload filtering, snapshot count/page queries, keyboard-accessible full receipts and pagination.
- One-transaction owner reconciliation plus evidence event; racing duplicate reconciliation rejected; consistent integrity snapshot with per-request ledger verification and missing-scope detection.
- Host parsing safely rejects malformed input; authentication session mutation stays on the event loop; booleans and reconciliation reasons are validated strictly.
- Database dispatch/settlement waits off the event loop. Repeated caller cancellation waits for the database operation, then performs safe cleanup. Lab orchestration cancels and awaits owned children on unexpected failure before releasing its single-batch guard.
- UI text contrast/readability, 44-pixel mobile action targets, skip link, named dialogs, menu expansion/Escape state, preserved focused search drafts, precise micro-USD display, date-aware records and stale-connection feedback. Preview inputs invalidate old estimates.
- Versioned packaging, no duplicate/stale manifest, member hash verification and explicit runtime-secret exclusions.
- Architecture, orchestration and product decisions recorded in docs/. Original RELAY plans and Notion are preserved.

## Evidence and limits

The final test results and browser/live HTTP JSON in evidence/ are authoritative. The expanded suite reports 61 passing tests with JavaScript syntax verification. Live HTTP checks cover SSE, an actual socket disconnect, revocation, replay and accounting on isolated synthetic data. Browser checks cover nine routes, previews, pagination/search, keyboard receipts, draft preservation, menu controls and mobile overflow. Screenshots are generated from the application, not mockups.

The review instance is separate at `http://127.0.0.1:8766`, data in `test-results/review-server`. Its credentials/database are excluded from the source release. No live provider, paid API, model download, public deployment, customer installation, independent security certification or validated market demand is claimed. Docker packaging remains unverified. The original implementation record below is historical.

---

# Implementation and evidence

Date: 21 October 2026. Budget: no additional money spent. Scope: runnable local, single-owner simulation product.

## Completed

- Static responsive frontend: unlock, overview, keys, sessions, request log and receipts, traffic lab, policy replay, reliability and settings. No frontend package/build/runtime server dependency.
- FastAPI backend, typed contracts, bounded requests, owner-cookie/workload-key authority separation, origin/host checks, error handling and rate/concurrency controls.
- SQLite schema/migration version 1 with integer budget buckets, policy/rate/period snapshots, reservations, sessions, usage records, append-only ledger and event inbox.
- Transactional parent/key/session reservations, idempotent settlement, owner pause/revocation revalidation before dispatch, uncertain-hold recovery, manual reconciliation and consistent backup/restore path.
- Deterministic asynchronous provider/lab orchestration, standard and streaming completion subset, real HTTP disconnect accounting, controlled failure fixtures and offline replay.
- Native local hosting at http://127.0.0.1:8765; dependency pins, start script, verification command, installation/API/architecture/operations documentation and portable source packaging.

## Verification evidence

- `evidence/automated-test-results.json` and `evidence/verification.log`: authoritative automated run count and pass/failure results. The test suite includes concurrent admission, duplicate settlement, randomized sequences, actual process exit and restart, cancellation, privilege separation and backup restore.
- `evidence/live-http-results.json`: loopback login, generated synthetic demo workloads, SSE completion, actual socket disconnect, invariant check, replay with no new traffic, and revocation.
- `evidence/browser-results.json`: Playwright/Edge flow through login, key creation, lab, receipt, replay and integrity; all eight navigation routes checked at mobile width. Desktop/mobile screenshots accompany the result.

All visible usage in the build instance is synthetic and labeled. The test run does not establish production performance, a fixed RPS target, real-provider pricing accuracy, full OpenAI SDK support or high availability.

## Review findings addressed during implementation

- Reservations snapshot fixture rates rather than reading a mutable current rate book during settlement.
- Revocation/pause is rechecked at dispatch, releasing known-undispatched holds on rejection.
- An interrupted await during reservation waits for the database operation and cancels the undispatched hold; it does not leak an untracked authorization.
- A per-directory OS lock prevents two server owners from recovering one another's active work.
- Ledger and hold integrity is checked in one pass over request scopes, avoiding one full history scan per bucket.
- Credential-validation errors do not echo inputs, exports neutralize spreadsheet formula prefixes, and UI-rendered names/reasons are escaped.
- Browser verification identified an invalid HTML pattern under modern regex rules; it was fixed and the browser suite rerun.
- Mobile cost-chart width/axis typography was adjusted following screenshot inspection. Tables scroll within their own containers.

## Deliberately not enabled or not verified

- Real LLM/provider calls, paid inference, provider credentials, BYOK, embeddings, tool calls, semantic caching, LLM agents and model downloads.
- Prepaid funds, payments, subscription checkout, currency conversion and provider-bill reconciliation.
- Public hosting, a public domain, HTTPS proxy configuration, remote/shared-company access and high availability. The running local computer is the host.
- PostgreSQL/shared storage, multiple application instances, Kubernetes, external notifications, automatic hosted CI and cloud deployments.
- Docker image/Compose runtime: packaging files are supplied but were not built/run because the Docker daemon was unavailable. Native execution was verified.
- Independent third-party security review. This is an implementation self-review with automated checks, not certification.

## Next integration boundary

A future live pilot needs an explicitly selected upstream, supported billing bounds, credentials funded by that company, compatibility/quality tests, deployment ownership and security assessment. These are not secretly activated by the simulator. Retain the original RELAY plans as the educational/commercial backlog; the zero-budget architecture review and 96-task mapping explain the changed sequence.
