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
