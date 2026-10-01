# Dashboard optional read resources — 2026-10-02

Scope: `codex/list-filter-behavior` worktree, dashboard optional summaries and recent records only. The existing dashboard layout, action links, permission gates, greeting cache, and AI text fallback remain. No new backend endpoint or ordinary pagination UI was added.

## Resource ledger

| Resource key | Existing read and true boundary | Permission | Dashboard consumer |
| --- | --- | --- | --- |
| `customerWork` | `/api/dashboard/customer-work-summary`; SQL total plus earliest 5 actionable items | any customer PCW/radar/read/read_all | Todo alerts and deep links; first 5 disclosure |
| `incomplete` | snapshot list, `is_complete=false`, `page_size=1`; server total is the count | `customer:read` | incomplete metric and alert |
| `batches` | commission batches, page 1 size 1; server total plus latest row | `commission:read` | batch metric and status |
| `recentCommissions` | commission batches, page 1 size 5 | `commission:read` | recent activity, at most 3 shown |
| `employees` | employee list, page 1 size 1; server total | `employee:read` | employee metric |
| `trackingCount` | shipments, page 1 size 1; server total | `tracking:read` | shipment metric |
| `trackingStats` | existing tracking stats aggregate | `tracking:read` | abnormal count, alert, preferred donut |
| `recentTrackings` | shipments, page 1 size 5 | `tracking:read` | recent activity, at most 3 shown |
| `recentShipments` | active shipments, updated descending, page 1 size 5 | `tracking:read` | logistics card, explicitly recent 5 |
| `designTasks` | design tasks, page 1 size 1; server total | any design read/audit/manage | shoot count metric and alert; original count semantics retained |
| `approvals` | design requests pending audit, page 1 size 1; server total | `design:audit` | approval metric, badge, alert |
| `designStats` | existing monthly design aggregate, Beijing month | any design audit/manage | donut fallback when tracking has no distribution |
| `recentDesigns` | design requests, page 1 size 5; existing identity scope | any design read/audit/manage | recent activity, at most 3 shown |
| `latestPayment` | synchronized payments in Beijing past 30 days, page 1 size 1 | `payment:read` | latest payment metric |
| `recentPayments` | same 30-day window, page 1 size 5 | `payment:read` | recent activity, at most 3 shown |

Each key has its own `useAsyncResource` controller and retry. A request failure leaves its prior successful value in the same account/permission scope, while the error remains visible. Initial failures leave counts unknown (`—`) and never display a false zero or false empty state. Every request receives an abort signal; account or permission changes clear all resource data and invalidate late responses. The four recent activity sources retain their existing display priority (commission, tracking, design, payment) and navigation links.

## Verification

- `TZ=America/Los_Angeles node --test tests/dashboardResources.test.mjs`: 5 pass. Covers independent failure/retry, same-scope retained data, account/permission clear and late response rejection, mounted logistics and overview failure/empty states, and Beijing month/30-day boundaries.
- `npm run build`: passed; Vite printed existing mixed dynamic/static auth import and large chunk warnings.
- `python scripts/check_conventions.py`: passed, incremental diff without violations.
- `python scripts/git_sweep.py --no-fetch`: exit 0; local snapshot only.

Production API/data flow was not exercised. The dashboard calls existing endpoints, with no database migration or deployment in this task.
