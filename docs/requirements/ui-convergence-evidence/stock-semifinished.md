# Stock / Semifinished List Adoption

## Scope and contract

Only list reads, query submission, pagination, retry, request ownership and mutation refresh were changed. Business quantity/ratio/safety-stock calculations and parent-owned feedback/status/money/layout changes are retained. No production data, deployment, commit or push was used.

Server lists use `useListPage`: drafts submit on Query/Reset; paging, sorting, tool refresh and mutation refresh consume submitted snapshots. Page sizes are 20/50/100. Initial failure has an in-table retry; refresh failure retains successful rows with their data-page marker. Main FilterBars have at most 4 controls; secondary stock dimensions are advanced. Selected material tab and ledger material ID enter submitted resource scope and clear the previous resource's rows. Local metadata writes require current request ownership.

Stock read API methods and semifinished read methods accept trailing optional config, pass signal/suppressToast and keep their previous response shape. Stock returns the backend success envelope; semifinished returns its payload. Production progress / print-card reads also accept config, preserving parent's other production API changes.

Parent explicitly authorized a narrow core addition: `handleReset({ sortParams } = {})` sets sorting only when explicitly supplied and performs one query. Existing reset callers retain current sorting. Stock reset callers restore their original default sorting using this argument.

## Resource coverage

| File | Resource | Implementation / verified behavior |
| --- | --- | --- |
| StockOverview | stock overview server page | snapshot arrays -> comma query, server sorting, guarded summary, stale/first-error retry, default sort reset |
| StockOverview | filter dimension options | useAsyncResource, visible failure/retry, unmount/late guard |
| StockOverview | row stock_items | embedded server response, no separate read/page required |
| StockOverview | production progress | useAsyncResource by item ID; old dialog data clears on switch; retry; only 404 may initialize |
| SafetyConfig | safety stock server page | snapshots, advanced controls, sorting/reset, unchanged suggested_qty math; save refreshUpdate |
| SafetyConfig | filter dimension options | same guarded options loader + visible retry |
| SafetyConfig | AI row / page suggestions | stale row/page response cannot apply suggestions to replacement list; business formulas retained |
| SafetyConfig | row stock_items | embedded server response, no separate query/page required |
| SafetyConfig | production progress | same guarded progress loader, failure/retry |
| SafetyConfig / useProductionCart | per-user cart | complete nonpaged response via useAsyncResource; retained cart on failure; visible retry; reconcile selected IDs after current success |
| SafetyConfig | generate production order | refresh current stock list after success; cart reload remains in cart composable |
| ProductionOrderManage | production order server page | independent submitted filters/sort, guarded visible-page counts, empty/stale errors; update/remove effective-page refresh |
| ProductionOrderManage | production item server page | independent submitted filters/sort; update/remove refresh items plus order aggregate |
| ProductionOrderManage | order detail/items | useAsyncResource by order ID; opens before read, clear on switch, failure/retry and late guard |
| ProductionOrderManage | inline / dialog progress | one active progress resource with item-ID result/cache; current success only; retry; 404-only initialization; process reset clears prior cache and reloads active matching scope |
| ProductionOrderPrint | print order server page | 3 primary controls + paired query/reset, paging, initial/stale failure/retry |
| ProductionOrderPrint | expanded print categories | per-row AbortController, current row identity guard, failure/retry, independent expanded rows; replaced main rows cancel prior categories and clear expanded IDs |
| ProductionOrderPrint | print preview/log | StimulsoftViewer owns rendering; existing log failure does not prevent print. Successful log refreshes current print filter/page (newly printed rows may leave an unprinted query). No invented pagination/filter on category collection |
| PublicInventory | public inventory server page | useListPage with English native controls/status (brand exception), Search/Reset pair, submitted filters, retry/stale page and 20/50/100 size choice |
| DailyReport | report by submitted date / latest | useAsyncResource; paired date query/reset, scope clear, 404 empty distinguished from network failure, retry uses submitted date |
| DailyReport | shortage / warning SKU arrays | complete embedded report arrays with original local sorts, no invented server pagination |
| MaterialManage | materials server page | snapshots, selection reset on resource change, current query refresh after sync/related order create |
| MaterialManage | product mappings server page | same controller with submitted resource discriminator, clears prior rows, retry stays on selected mappings scope |
| MaterialManage | sync preview/examples | useAsyncResource, drawer opens before read, visible error/retry, late guard |
| MaterialManage | mapping material options | full catalog pages100 via guarded loader, visible failure/retry; does not reset user's mapping edits on retry |
| OrderManage | semifinished order server page | snapshots, first/stale errors, create -> first page; terminate/receive -> refreshUpdate effective page |
| OrderManage | create material options | full catalog loader + useAsyncResource, visible failure/retry; quantities unchanged |
| OrderManage | order detail/items | useAsyncResource keyed by order ID; scope clear/late guard, retry; receiving an old order does not reload a newly opened detail |
| InventoryManage | inventory server page | snapshots and current query refresh after adjustment; initial/stale errors |
| InventoryManage | material inventory ledger | separate scoped useListPage with 20/50/100 server paging (formerly first100 only), clear on material switch, retry; drawer label independent of adjustment material |
| ProductionOrderDialog | quote / semifinished plan | existing quote parsing retained; optional signal/suppressToast; retry; disable/close/product switch and quantity debounce invalidate prior reads; submission disabled while loading |

## Real response evidence and exceptions

- Backend `stock/router.py`, `stock/public_router.py` and `semifinished/router.py` confirm total/page/page_size responses. Semifinished ledger is a true server page and now exposes all pages.
- Stock print categories, per-user cart, report SKU arrays and full selector catalogs are collections/options rather than artificial main-page lists. Print categories have independent concurrent row ownership; select catalogs aggregate actual pages until current scope expires. There is no cursor-only endpoint in this directory inventory.
- PublicInventory is explicitly public, all-English and follows its customer brand; shared FilterBar/ListPageStatus contain Chinese copy. It consumes the shared controller while retaining native English paired controls and error/retry UI.
- Production progress initialization is allowed only after a real 404; network/5xx failures display retry rather than creating progress. Missing route/initialization errors stay visible.

## Validation

- `node --test tests/stockListAdoption.test.mjs tests/listAdoption.test.mjs tests/useListPage.test.mjs` passed **72/72** after explicit-reset/quote regressions were added (26 stock/semifinished adoption cases, 36 earlier adoption cases, 10 shared controller cases).
- Mounted inventory template test exercises the real empty slot + real ListPageStatus: first failure renders retry, retry loads fixture rows, tool refresh failure retains rows and shows the error.
- Real source adapters exercise snapshots/page-size/first failure/stale recovery across 9 main list entries; additional fixtures cover guarded summary, safety calculation/late AI, mappings switch, ledger race, last-page delete, categories retry/race, date404/network distinction, selector aggregation cancellation, progress404-only initialization, cart selection, detail race and API read config.
- Browser brand/layout/Element Plus interactions, actual Stimulsoft report rendering and backend mutation integrations remain for parent-wide integration verification. Unit/mounted fixtures do not claim production verification.

## Parent integration

- Include new `stockResources.js`, `materialOptions.js`, this report and `stockListAdoption.test.mjs` alongside the changed pages/APIs and authorized core-reset fragment.
- Parent owns DESIGN/handoff synchronization, full site build/gates and git_sweep. No additional component registration is required; parent already globally registered FilterBar/ListPageStatus.

- Final scoped SFC compile: **10 files / 0 failures**. `git diff --check` on owned stock/semifinished/API/core/test paths exited **0** (only configured LF-to-CRLF notices).
