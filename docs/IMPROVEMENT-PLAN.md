# Fusewall 0.2 review and implementation plan

Date: 22 October 2026. Budget: INR 0 additional spending. Working source: RELAY/codebase.

## Objective

Make the existing local budget gateway easier to evaluate and harder to misinterpret. Retain simulation-only operation and conservative accounting. This is not completion of the commercial SaaS roadmap.

## Execution

1. Establish baseline and inspect accounting, HTTP, orchestration, UI and current competitor documentation.
2. Fix atomic reconciliation/audit, coherent integrity snapshots, malformed-host handling, auth state races and batch failure cleanup.
3. Add a shared policy evaluator with a non-mutating preview, actionable usage insights and searchable paginated request history with full receipts.
4. Improve keyboard access, mobile navigation, form/result states, connection feedback, money precision and in-flight receipt wording.
5. Verify backend invariants, integration contracts and browser workflows on isolated synthetic data. Package a versioned release with fresh evidence.

## Baseline

- Re-ran the existing suite in RELAY/codebase: 44 tests passed, no failures/errors/skips.
- Found integrity reads across separate connections, a non-atomic resolution audit, newest-100-only UI filters, inaccurate active receipt wording and a packager that includes an old manifest and hardcodes its version.
- Market sources confirm established budget/rate-control offerings; demand for Fusewall itself and willingness to adopt remain unvalidated. Focus on explainable decisions and offline evaluation, not invented competitive superiority.

## Boundaries

No paid calls, live-provider credentials, public deployment, model downloads, automatic retries, multi-tenancy or distributed infrastructure. Native SQLite remains the local authority. Preview is advisory and reserves nothing; actual admission always rechecks current state transactionally.

## Verified outcome

- Completed steps 1–4. Expanded backend verification: 61 tests, zero failures/errors/skips, JavaScript syntax checked.
- Native HTTP verification passed after the asynchronous database changes, including real SSE socket-disconnect settlement, revocation, replay and accounting integrity.
- Final browser check passed sequentially: nine routes at desktop/mobile, allowed/blocked non-mutating previews, pagination, search, keyboard receipts, focused-draft preservation, menu Escape state and no page-level horizontal overflow or console/runtime errors.
- Screenshot inspection led to additional small-text contrast/readability changes and a hidden-until-focused skip link. Preview edits invalidate the old estimate.
- Recorded product/competitive decisions and architecture/orchestration in docs/. No external customer validation or live-provider test occurred.
- Packaging now derives the version, excludes runtime secrets/scratch data, writes one fresh manifest and verifies archive-member hashes. See the release archive and manifest for the final artifact evidence.
