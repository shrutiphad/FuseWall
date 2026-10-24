# Live deployment — 24 October 2026

- Public application: https://fusewall.vercel.app
- Repository: https://github.com/shrutiphad/FuseWall (main). PR #1 was merged by the fast-forward publication.
- Deployed source: `52afe3d8d0fcdcc44bf04712b55736faea09be8e`; Vercel deployment `dpl_EGTp8SRrQ87P1c39ETAoQffrjNXY`, READY, production, Mumbai (`bom1`). Later documentation/evidence commits do not change this running application.
- Supabase project `hfvgbffnhcohcbygmkpp`, Mumbai, organization Personal Projects on Free. Private `fusewall` and `fusewall_preview` schemas use separate restricted runtime roles, secrets, RLS and TLS transaction-pooler connections. No public/anonymous schema access; cross-schema runtime reads and ledger changes are rejected. Vercel team is Hobby; no trial or paid service was activated.
- Public production HTTP and nine-route desktop/mobile browser checks passed. Tests cover owner unlock, keys, synthetic workloads, streaming, previews without traffic, request pagination/search, keyboard receipts, replay, insights, integrity, mobile navigation and startup latency. No browser console errors or horizontal page overflow. Initial session validation now completes before the token field is enabled, fixing a real startup race.
- Preview sessions and records survived redeployment. Production retained 26 requests from before its final redeployment. Final accounting integrity agreed at 149200 micro-USD simulated cost with no scope/request mismatches. Disconnected hosted streams completed and settled; server cancellation is not claimed.
- Queried available error logs for the final deployment using a 15-minute lookback; no error records returned. This is a release-time scan, not continuous monitoring. No external monitoring or uptime guarantee is claimed.
- Temporary production test links were revoked or confirmed absent. Verification workload keys were revoked. Demo keys remain usable. Synthetic demonstration records are retained; no real provider was contacted.

## Access and operations

The owner token is private and is not included in Git, public evidence or release archives. The user receives a local owner-access file. Vercel uses the legacy Standard Protection scope: the current production URL is public, while previews and deployment URLs remain restricted. Dashboard/API authentication, HTTPS origin checks and the explicit host allowlist remain enforced.

Automatic Git deployment remains disabled in vercel.json so code pushes do not bypass validation. To release: migrate/check only if required, build the exact Git commit, verify a protected preview, deploy production with production secrets, verify the actual production domain, then record the source SHA and evidence. Do not assume generated team aliases are public; query the project's configured domain. The actual domain is fusewall.vercel.app.

A consistent production metadata backup was saved privately outside the repository. Preserve owner/fingerprint secrets separately. Restore requires an empty migrated private schema and accounting validation. The previous Vercel deployment `dpl_DHLDYS74pfbmvDJDmnhnPussZPzJ` is retained; it predates the startup race fix, so prefer redeploying the current verified commit for runtime recovery. Stop rollout on readiness failure, state loss, privilege failure or accounting mismatch; do not release uncertain holds to force success.

Supabase performance advisors reported only informational items: the small rolling login-attempt table has no primary key and new request indexes had not yet been used. Their [primary-key guidance](https://supabase.com/docs/guides/database/database-linter?lint=0004_no_primary_key) and [unused-index guidance](https://supabase.com/docs/guides/database/database-linter?lint=0005_unused_index) are references for future measured tuning. Security advisors returned no findings at setup; this is not a certification or penetration test.

Single-owner simulation only. Real LLM adapters, company multi-user access, live billing protection, load testing, high availability and customer validation remain incomplete. Vercel Hobby personal/noncommercial restrictions apply. No additional spending was authorized or activated.

The earlier preparation records below are historical; current status is above.

---

# Hosted preview verified — 24 October 2026

Git commit 685dc5a14b3fbcc71edde0ebda485ea84b16ba59 built successfully on Vercel at the target recorded in evidence/hosted-preview/. Hosted HTTP checks passed login, bounded synthetic workloads, SSE, conservative disconnect accounting, replay, revocation and accounting integrity. The proxy completed the disconnected stream and the full simulated cost settled; cancellation is not claimed. Nine-route desktop/mobile browser checks passed without console errors or page overflow.

Short-lived preview OIDC headers are scoped to the exact test origin. Verification scripts accept a separate evidence output directory so hosted runs preserve native evidence. Final text updates remove inaccurate local/offline labels in hosted views. Production promotion remains pending in this commit. The earlier progress/preparation records below are historical.

---

# Supabase deployment progress — 24 October 2026

The separate Fusewall project is active on the verified Free organization plan in Mumbai. Private preview/production schemas and dedicated restricted runtime roles are installed. RLS is enabled and Supabase security advisors returned no findings. Actual TLS transaction-pooler connections and real-database API workflow checks passed (evidence/supabase-workflow-results.json), including shared sessions/data across application instances, SSE, metadata backup, revocation and accounting.

Vercel secrets and database connections are configured separately for preview/production; compute region is Mumbai. The first Git-backed build exposed a Python package-discovery error; explicit package selection fixes the source packaging. A local wheel build passed and packaged static assets/migration hashes match the source (evidence/package-build-results.json). No successful hosted verification is claimed by this progress record. The original preparation instructions below remain a rollout/runbook reference, with their earlier access status historical.

---

# Vercel / Supabase preparation: 0.3.0

Status: implemented and tested on isolated PostgreSQL 16. The user's Supabase project is not connected; no successful Vercel deployment is claimed. Additional-spending budget remains zero.

## Evidence

With `FUSEWALL_PG_TEST_URL` pointing at disposable loopback PostgreSQL, `python verify.py` passed 103 tests with zero failures/errors/skips, including SQLite and real PostgreSQL cases. Browser checks passed nine routes at desktop/mobile on an isolated native 0.3 instance. These are not hosted Supabase/Vercel results.

GitHub and Vercel are connected. Separate encrypted owner/fingerprint secrets and schema names have been configured for Preview and Production. `FUSEWALL_DATABASE_URL` is missing. Automatic Git deployment is disabled in `vercel.json` until the actual database and a preview pass validation; deployment from the Git commit can then be triggered explicitly.

## Architecture

`PostgresStore` reuses common admission/settlement rules through a narrow adapter for fixed parameterized SQL. Every write uses a transaction-scoped advisory lock per schema. Snapshots use repeatable-read read-only transactions. Transaction-pooler compatibility uses `SET LOCAL` and disables prepared statements. No provider generation occurs inside a transaction. This prioritizes correctness over high write throughput.

Owner sessions, failed-login counters and the lab guard are shared in PostgreSQL. Secrets are stable environment values, not temporary files. Worker startup never recovers another worker's requests. A 120-second request lease exceeds the configured 60-second function limit; dispatch rechecks expiry. Owner-triggered recovery cancels expired undispatched reservations but retains uncertain dispatched holds. Hosted batches allow up to 20 calls and 4 parallel operations.

Native SQLite remains available. Vercel refuses SQLite fallback. The cloud entrypoint requires durable secrets, shared storage and an explicit HTTPS host allowlist. Cloud and local UI labels/export formats differ accordingly.

## Connection and migration

Connect Supabase to the chat so the intended project and free-plan constraints can be verified. Alternatively, set `FUSEWALL_DATABASE_URL` in Vercel's encrypted environment-variable settings for Preview and Production. Do not paste credentials into chat or commit them. Use the actual Supabase Connect dialog's transaction-pooler hostname/username, with `sslmode=require` or stricter verified TLS.

Required environment values:

- `FUSEWALL_DATABASE_URL`: actual server-side PostgreSQL connection string.
- `FUSEWALL_OWNER_TOKEN`: generated owner credential, at least 32 characters.
- `FUSEWALL_FINGERPRINT_KEY`: stable private fingerprint secret, at least 32 characters.
- `FUSEWALL_DATABASE_SCHEMA`: `fusewall_preview` for preview; `fusewall` for production.
- Exact hostnames from `FUSEWALL_ALLOWED_HOSTS` and/or Vercel's `VERCEL_URL`, `VERCEL_PROJECT_PRODUCTION_URL`, `VERCEL_BRANCH_URL`. Wildcards are not accepted.

Migration requires schema-owner permissions and is run explicitly from a trusted environment, never on every worker import. Prefer a dedicated runtime role restricted to the Fusewall schemas; use an owner/admin connection for migrations and grant the runtime role only required table/sequence access. Do not reset an existing project password. The migration refuses reserved schemas and unrecognized nonempty schemas, and never modifies `public`, `auth`, `storage` or other application schemas. Tables are not granted to PUBLIC.

```powershell
python scripts/cloud-admin.py migrate
python scripts/cloud-admin.py check
```

`app.py` is the Vercel FastAPI entrypoint; SQL migration data is included in the Python package. The actual Supabase pooler/TLS/role permissions must be exercised before deployment readiness is established.

## Rollout gates

1. Verify the intended Supabase project/plan without activating paid services. Configure credentials privately; migrate the preview schema.
2. Keep destructive integration tests restricted to loopback disposable schemas. Run labeled, non-destructive workflow checks against actual Supabase using separate app instances.
3. Deploy the Git commit as a Vercel preview. Verify readiness, login, keys, admission, streaming/disconnect, previews, lab, history, export, recovery and integrity. Verify persistent sessions/data across worker changes or redeploys.
4. Migrate/check production separately, then deploy/promote and verify the final URL. Only then enable automatic Git deployment intentionally.
5. Stop rollout for failing readiness, lost state, accounting mismatch or privilege failures. Do not release uncertain holds to force a passing result.

## Export, restore and rollback

Hosted metadata JSON exports are consistent snapshots, including accounting metadata, hashed workload keys and events. They exclude owner sessions and owner/fingerprint/database secrets, which must be preserved privately. HTTP exports cap serialized data at 4 MB; larger exports use the trusted CLI. File exports refuse to overwrite an existing file.

```powershell
python scripts/cloud-admin.py export --file private-backup.json
python scripts/cloud-admin.py restore --file private-backup.json
python scripts/cloud-admin.py check
```

Restore requires a newly migrated empty destination schema. It checks columns and accounting before commit; corrupt data rolls back. It never deletes/overwrites an existing installation. Retain the prior Git commit and compatible metadata/database snapshot before upgrades. Rollback requires schema compatibility. No deletion of the user's Supabase project or other schemas is part of deployment.

Single owner and simulated inference only. This is not multi-tenant company access, live-provider billing protection, verified savings, high availability, certification or load-tested production service. Vercel Hobby personal/noncommercial restrictions apply. No paid API, subscription, trial or new database account is activated by this code.
