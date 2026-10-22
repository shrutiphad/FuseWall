# Fusewall implementation rules

- Additional-spend budget is zero. Never activate paid APIs, cloud hosting, model downloads, accounts, subscriptions or uncapped hosted CI without explicit user authorization.
- Preserve source plans in the separate RELAY folder and Notion. Report actual evidence; never mark a simulated/provider-fixture test as a live-provider test.
- Single-owner loopback prototype; one server process per data directory. No real-provider adapter exists in this release.
- Money is integer micro-USD; reserve all applicable scopes transactionally before dispatch. Preserve parent ceilings when session IDs change.
- No network operation in a database transaction. Uncertain dispatched work keeps its hold; never release merely on timeout or blindly replay upstream work.
- Request settlement, held exposure and ledger records must remain idempotent and consistent. Ledger is append-only. Rate/policy/period snapshots belong to the admitted request.
- Workload credentials cannot administer keys or budgets. Never log raw keys, owner tokens, prompts or response bodies. Escape user content in the UI.
- Keep modules small and explicit. Static frontend has no required build tool or external assets.
- Run `python verify.py` after behavior changes. Run live HTTP/browser checks when relevant and label their database mutations. Do not repeatedly run already-passing checks without a changed concern.
- Native hosting is verified; Docker packaging must remain labeled unverified until built and exercised. Public/shared hosting requires separate validation.
