# Product decisions for release 0.2

Reviewed: 22 October 2026. This document records the implementation choices for this release, not validated product-market fit.

## What the product does today

Fusewall lets a developer rehearse AI spending controls without buying inference or configuring a provider. They can create a bounded workload, preview one request, run concurrent/failure scenarios, inspect decision receipts, attribute synthetic usage and check that accounting survived interruption. It does not evaluate answer quality, LLM citations or provider invoice accuracy.

The initial audience is a technical builder who needs to understand or demonstrate policy behavior. A company's headcount alone does not establish this need. The commercial audience remains a hypothesis: teams with agent workloads and difficulty explaining or enforcing shared spending boundaries.

## Current competitive evidence

[LiteLLM's budgets documentation](https://docs.litellm.ai/docs/proxy/users) describes personal, team, member and agent budgets, including session caps. It lists a database requirement. This overlaps Fusewall's intended spending-control space; it is not evidence that competitors lack agent budgets or that Fusewall is uniquely capable.

[Portkey's budget documentation](https://portkey.ai/docs/product/ai-gateway/virtual-keys/budget-limits) describes cost/token limits and links to workspace-wide enforcement. The page is under deprecated virtual-key navigation and describes plan-specific availability; verify packaging with the vendor before comparing price. It establishes existing control capabilities, not a demonstrated reliability defect.

[Helicone's custom-rate-limit documentation](https://docs.helicone.ai/features/advanced-usage/custom-rate-limits) describes limits by request count, cost and custom properties. Its documentation also exposes sessions, cost tracking and reports. These are established adjacent capabilities; basic cost visibility is insufficient differentiation.

These primary sources confirm an active product category and substantial overlap. They do not measure demand for Fusewall, prove a competitor fails under concurrency, establish customer willingness to switch, or validate any market-size number. No customer interviews, installations, revenue or measured savings were obtained in this review.

## Why this version adds value

- A no-mutation preview explains the organization, workload and session ceilings using the same rule evaluator as admission. The real request still reserves atomically.
- Search and pagination make older rejected requests inspectable rather than hiding them outside a latest-100 sample. Receipts distinguish active, uncertain, undispatched-canceled and settled work.
- Usage insights explain attribution and failed-work usage from records. Suggested checks are deterministic and linked to observed conditions, without paid AI analysis or invented savings.
- Transactional resolution evidence, coherent integrity checks and explicit child-task ownership improve confidence in demonstrations of failure behavior.

These are useful evaluation features, not proof of a commercial moat. The positioning to test is: "Rehearse and explain budget boundaries before exposing a live AI workload." A live spending-protection claim requires a validated real adapter first.

## Deferred ideas and why

Do not add a paid LLM judge, autonomous supervisor, semantic cache, multi-provider routing, Kubernetes, payments or hosted notifications to make the feature list larger. Quality evaluation needs task-specific ground truth; caching/routing can change output quality; live billing needs supported bounds; public multi-user operation needs a different security and deployment assessment.

## Evidence needed before selling live protection

1. Observe at least five target teams' current workflow, example spend incidents and existing alternatives. Ask what their current gateway cannot explain, and whether they can demonstrate the problem.
2. Have three technical users run a fresh local package unaided. Observe time to first key/preview/receipt, onboarding failures and whether the controls are understood. These are proposed targets, not achieved metrics.
3. Select one real provider only after a pilot owner can fund their own usage. Define supported request shapes, price/token bounds, usage uncertainty and failure reconciliation. Test adapter contracts with fixtures before any authorized live usage.
4. Validate a customer-controlled deployment, access model, backup/restore and rollout/rollback. Make no uptime, multi-tenant isolation or savings guarantee from local simulator evidence.

No outreach, paid service, credential purchase or public publication is initiated by this document. The next major uncertainty is customer usefulness, not another infrastructure layer.
