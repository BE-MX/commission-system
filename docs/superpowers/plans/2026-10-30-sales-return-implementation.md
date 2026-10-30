# Sales return implementation

Design: [foreign trade sales returns](../../requirements/2026-10-30-sales-return-order-design.md).

Scope: implement locally in `codex/sales-return-design`; no push, merge, deployment or production writes. Existing unrelated work stays untouched. Tests use the shared Python interpreter with this worktree's source and isolated SQLite/MySQL only; do not copy production `.env`.

## Delivery stages

1. Establish source contracts, local immutable models and migration. Source readers verify exact shipped lines, order currency, goods principal, original receipts and access; unknown evidence blocks activation.
2. Implement preview, draft and atomic activation, original-payment allocations, local negative receipts and net balance integration. Test full/partial payments, concurrent limits, idempotency, rollback, historical orders and permissions.
3. Implement GMV projections across daily reports, goals, battle reports and amount analytics; commission reversal uses original beneficiaries and rules, including batch replay and late adjustments. Test cross-period negatives without changing customer/order counts.
4. Implement main-site page, order/outbound entry links and local negative receipt visibility, with existing UI patterns. Implement receipt inspection and verified stock entry only through an authoritative interface; lack of a verified writer must remain visible.
5. Run impacted backend tests, frontend checks/build, isolated browser acceptance, migration checks and conventions. Independent review covers specification, money/inventory risks and code quality; fix findings and rerun affected checks.
6. Update API/database/handoff and a reviewable acceptance report with actual commands, evidence and any outstanding limitations. Deliver local changes and acceptance entry; no remote actions.

Ownership is partitioned by source readers, analytics/commission integration, frontend and the root's financial transaction/router/migration work. Shared model/API contracts are coordinated before editing consumers; one writer per file.
