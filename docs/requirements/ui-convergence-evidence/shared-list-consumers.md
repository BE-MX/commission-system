# List adoption worker — resource checklist

Updated: 2026-10-02. Worktree: `C:/Users/windb/.codex/worktrees/list-filter-behavior/commission-system`. Scope: existing frontend useListPage consumers, customer hub bridges, and the four requested color/insight resources. Phase I invoice/receipt/domestic-orders and parent financial resources are excluded. No commit/push/deploy.

## Contract delivered

- Read adapters reject into useListPage; failed reads retain successful rows only in the same resource scope. Initial failure and stale refresh both expose `ListPageStatus` with retry. Table empty slots always mount status; retained-data banners are separate.
- FilterBar pairs search/reset, limits primary controls to four, advanced controls retain draft values. Ordinary field changes do not submit. Domain scope/tab shortcuts remain intentional submits. Pagination/retry/writes use applied snapshots.
- External mine flag, order-review report/team/member/day, selected gateway app and salary/table sorting are captured; sort uses parent `handleSortChange` and never submits pending text filters.
- Added `useListResourceScope.js`: watches only submitted scope fields, clears old scope rows/metadata before a new read. Used by operations/evidence/mail panel, directory/workbench, domestic owner scope and aftersales route/scope. Timeline retains its explicit prop scope watcher.
- Read API wrappers accept optional config and pass `signal`/`suppressToast`; existing permissions, polling and route query scopes remain.
- Creates use refreshCreate, row edits/reviews use refreshUpdate, deletes use refreshRemove. Announcement saved payload includes `{ created }`; workspace exposed refresh is update-aware, plus explicit refreshCreate.
- Color/insight backend uses `app.core.response.ok` (`{code,message,data}`) and API client returns that whole body. Replaced erroneous `res.data.code`/`res.data.data` checks in the four requested views, including their option loads and successful write responses.

## Resource coverage

Verification labels: **controller** = executes actual source with real useListPage and fixture API timing; **mounted** = compiles and mounts real template/status and clicks retry; **compile** = SFC script/template compilation. No live/production data used.

| Resource / consumer | Implemented contract | Actual evidence | Remaining verification |
| --- | --- | --- | --- |
| MailOutreachQueue jobs | No swallowed error; paired filters, status/empty retry; cancel update refresh | controller + compile | live permissions/mailbox options |
| WorkspaceTimeline | customer scope snapshot/clear, status/retry | controller scope failure + mounted first-error/stale retry + compile | browser presentation |
| useOperationsList bridge | signal, suppressToast, current metadata, scope reset, lifecycle activation refresh | controller first failure/stale/late metadata | browser keep-alive activation |
| useCustomerHub customers | Direct bridge, error/stale/empty, shared toolbar/status | controller + compile | browser detail flows |
| useCustomerHub acquisition | Same bridge + status filter, preserves polling; create remount remains first page | shared bridge controller + compile | browser polling lifecycle |
| useCustomerHub research | Same bridge + quality filter; update refresh exposed; batch create refreshCreate | shared bridge controller + compile | browser review permissions |
| useCustomerHub opportunities | Unfiltered resource, no empty FilterBar; status/retry; update refresh | shared bridge controller + compile | live domain transitions |
| useCustomerHub radar | Unfiltered resource, no empty FilterBar; status/retry | shared bridge controller + compile | live domain transitions |
| CustomerDirectory | API throw propagation, metadata guard, URL c_ scope, <=4 main fields, shared retry | controller race/stale + mounted actual table empty retry + compile | browser scope/URL navigation |
| WorkbenchList | API throw/contract guard, metadata guard, customer/ownership scope clearing, w_ URL, four+advanced, retry | controller race/stale + compile | browser admission/work-item flows |
| QualificationPanel | operations bridge, filter/status/retry, update refresh | shared operations controller + compile | browser decision drawer |
| EvidencePicker | snapshots customer/kind/opportunity/target status, clear previous rows/selection, query/reset, page size, retry | actual evidence scope/reset controller + compile | browser multi-selection reference semantics |
| MailOutreachPanel drafts | operations bridge, customer snapshot, stale table visible, empty retry, create refresh | actual mail dual-scope controller + compile | mounted full drawer flow |
| MailOutreachPanel jobs | operations bridge, customer snapshot, stale table visible, empty retry, saved update refresh | actual mail dual-scope controller + compile | mounted full drawer flow |
| AgentTaskCenter tasks | filters/status/retry and config | controller first-error/stale/snapshot/page + compile | live evaluation workflows excluded |
| AfterSalesList cases | four+advanced, route review flag/date range snapshot, scope clearing, status/retry | controller first-error/stale/snapshot/page + compile | live reviewer permissions |
| AnnouncementList documents | filters/status/retry/config; create/update/remove semantic refresh | controller first-error/stale/snapshot/page + compile | editor saved-event UI |
| ReportDaily order review | report/team/member/day snapshot, scope clear, metadata guard, four filters/reset, status/retry | existing race tests 4/4 + compile | matrix/detail are separate read resources |
| TrainingList digests | mine belongs to snapshot, query/reset, status/retry, delete adjust | controller mine/page/reset + compile | live edit permissions |
| CardButler customerPage | paired filters/status/retry, create/update/remove/entry update refresh | controller first-error/stale/snapshot/page + compile | non-hook salesperson/entry tables excluded |
| CardButler inquiryPage | paired filters/status/retry, handled update refresh | controller first-error/stale/snapshot/page + compile | live assignment permissions |
| DomesticCustomers | four+advanced, owner scope clearing, province draft cascade, scope-preserving reset, semantic writes | controller first-error/stale/snapshot/page; existing controls 6/6 + compile | ledger read excluded |
| DomesticCustomerRequests | filters/status/retry; review update refresh | controller first-error/stale/snapshot/page + compile | voucher read excluded |
| DomesticProducts products | four filters/status/retry; price/route updates refreshUpdate | controller first-error/stale/snapshot/page + compile | craft-route mapping auxiliary list excluded |
| StoreManagement stores | offset/limit adapter retained, filters/status/retry; save create/edit split | controller first-error/stale/snapshot/offset + compile | users/quota resources excluded |
| ExpoLeads | filters/status/retry/config; delete remove refresh; detail polling retained | controller first-error/stale/snapshot/page + compile | live detail polling |
| PromptVersions | keyword/status/retry; create/edit/default refresh | controller first-error/stale/snapshot/page + compile | editor preview read excluded |
| BeautifyPromptVersions | keyword/status/retry; create/edit/publish/archive refresh | controller first-error/stale/snapshot/page + compile | editor preview read excluded |
| SearchJobs | status/status retry; polling preserved; create/requeue refresh semantics | controller first-error/stale/snapshot/page + compile | live polling lifecycle |
| PublicPoolResearch batches | cards status/retry; local task filters now draft/applied + paired reset; generation refreshCreate | controller first-error/stale/snapshot/page + compile + API forwarding | browser batch generation |
| PublicPoolResearch nested tasks | per-batch current guard/AbortController/errors/retry; preserves full-batch operation semantics | controller per-batch race/stale/retry/local filter + compile + API forwarding | browser batch actions; existing 300 cap unchanged |
| AiGatewayApps apps | filters/status/retry/config, page-size handler, create/edit/rotation/toggle refresh | controller first-error/stale/snapshot/page + compile | live permission/keys flows |
| AiGatewayApps requests | app scope snapshot clears prior rows; reset preserves selected app; status/retry/page size | controller scope failure/reset + compile | live resolution mutation |
| SalaryProfiles | filters/status/retry; sort snapshot without draft submission; create/edit refresh split | controller sort/create/update + compile | live private fields excluded |
| OutboundRecords | filters/status/retry/config; delete Remove, allow/recovery Update | controller first-error/stale/snapshot/page; actual remove controller domain tests + compile | print/download own flow |
| InspectionRecords | four+advanced/date snapshots/status/retry/config; recall Update | controller first-error/stale/snapshot/page; existing PDF boundary tests + compile | print drawer own flow |
| PaletteView | shared hook, four filters/reset, status/retry, envelope, create/update/remove | controller real envelope/stale page + compile | live detail/generation flow |
| BlendView | shared hook, filters/reset/status/retry, submitted sort, envelope, create/update/remove | controller real envelope/stale page + compile | live blend constraints preserved |
| SwatchGenerator history | unfiltered shared hook/status/retry, sort/page sizes, envelope, completed generation Create refresh | controller real envelope/stale page + compile | live generation/polling behavior |
| IntelligenceOverview reports | unfiltered shared hook/status/retry, envelope, create/remove/pin refresh | controller real envelope/stale page + compile | schedule options/generation flows |

## Verification run results

- `node --test tests/listAdoption.test.mjs`: **36/36 passed**. Includes actual API wrapper forwarding across 37 read entry points (config, params, signal), real adapters/controllers and two mounted UI surfaces.
- `node --test tests/battleReportRace.test.mjs tests/shippingPdfDownload.test.mjs tests/domesticCustomerControls.test.mjs tests/outboundQueueActions.test.mjs`: **18/18 passed**.
- SFC script/template compilation: **43 list-related Vue consumers passed, zero errors** (including parent and Phase I pages in read-only compile snapshot).
- Updated obsolete fixtures only to pass the new adapter context or execute the real Remove controller; original permissions/date/cancellation/error assertions retained.
- Combined focused domain/controller/component suite: **108/108 passed** (listAdoption, battleReportRace, shippingPdfDownload, domesticCustomerControls, outboundQueueActions, customerHubBehavior, customerWorkbenchV2, publicPoolRules, listPageComponents).
- Template AST audit: **34 FilterBar surfaces**, every one pairs search/reset with <=4 primary fields; **zero hasData-guarded table empty status slots**. Scoped `git diff --check` passed (only existing line-ending notices).
- Parent owns full all-site tests/build/conventions/git_sweep and DESIGN/handoff integration. The checklist remains a worker verification record, not a claim of full production/browser validation.

## Explicit excluded resources

- Phase I: invoiceManage/useInvoiceManagePage, ReceiptManage/useReceipts, DomesticOrders/useDomesticOrders and useListPage.js itself.
- Parent financial: CommissionBatch, CommissionDetail, SalesCommission, PaymentSync, CustomerSnapshot (banner relocation observed fixed).
- Other hand-written lists and options/detail-only reads were not silently declared migrated. `CustomerWorkbench` uses useCustomerHub with `immediate:false` for detail only; no extra FilterBar/table was added.
