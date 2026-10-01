# Asset / Expo / Report / SOP Resource Adoption

## Completed scope and actual API contracts

Assigned asset views, four Expo library views, ReportCenter and SopManagement are implemented. The main asset library is the only assigned server-paged collection; `getAssetList` supplies items/total and query-wide available_tag_ids. It now uses `useListPage`, page sizes 20/50/100, detached query/sort snapshots, effective-page delete refresh, first-error retry and retained successful rows after a failed refresh. Other main endpoints actually return complete arrays (SOP wraps its full collection in data.items), so they use `useAsyncResource`; no artificial pagination or fixed first-page claims were introduced.

Professional asset sidebar remains a deliberate exception: tag/family clicks commit the selected tag group immediately, parent/child cascade and progressive dimension sections remain intact. A tag click uses the already committed keyword and cannot submit a typed keyword draft. The top keyword has a paired FilterBar Query/Reset. Search-tag text only narrows the local sidebar and does not issue a server query. An empty committed query keeps the original guide and does not fetch the full asset library. Tree management retains per-dimension local tag search and hierarchy instead of manufacturing one flat main FilterBar.

Wig/HairColor keyword and Script type filters now have explicit draft/applied boundaries with paired FilterBar controls. Refresh/retry/mutation reload never submits an edited draft. Hair colors explicitly retain only_active=0; wigs retain the management endpoint's default only_active=0. Scripts keep inactive management values. Scene images retain mode=tryon and local category grouping. Kiosk config/auth recovery remains intact, including shared getHairColors/getScenes options.

## Per-resource ledger

| Resource | Real shape / bound | Change and actual evidence |
| --- | --- | --- |
| AssetLibrary results | P items/total | shared core, keyword/tag/sort snapshot; first/stale error; actual facet/paging/sort/controller regression; delete last-page backoff |
| AssetLibrary facets | S available_tag_ids from the same paged response, query-wide | current-request-only assignment; failed/newer/old responses cannot overwrite current facet IDs; scope/reset clears IDs |
| AssetLibrary sidebar dimensions/values | F tree | own async error/retry, preserves parent cascade/advanced grouping; existing assetTagFilters domain tests passed |
| AssetLibrary favorite-folder chooser | F array | separate async loader, dialog opens before read; own error/retry; no failure-as-empty |
| AssetLibrary preview AI suggestions | S analysis response | only current preview/analysis sequence can apply suggestions; preview/user switch invalidates metadata; existing write/download flow retained |
| AssetFavorites folder navigation | F array | independent error/stale/retry, defaults/reconciles current folder only from current collection; actor switch clears previous folder data |
| AssetFavorites folder items | F array by folderId | changed folder clears old items, same folder retry retains rows; old request ignored; successful remove reload reads same folder only |
| TagDimensionManage dimensions/values | F tree by internal/customer scope | clear/cancel before scope switch; include_hidden=true preserved; failed new scope cannot retain old tree; retry uses submitted scope |
| AssetUpload tag options | F dimensions/values | own error/retry, current metadata initializes selections only after current read; failed/loading options disable submit and folder-open action |
| AssetUpload AI suggestions | S file-name analysis | independent async error/retry, file context snapshot; old file suggestions cannot auto-accept tags; clear cancels |
| FolderUpload validation result | S matched/ambiguous/unmatched collections | cancellation/sequence, inline error/retry; reset/close cannot receive old metadata; original matching/resolution fields retained |
| FolderUpload preview result | S prepared preview collection | same validation context guard or own retry context; prior preview survives a read failure until explicit reset; failed preview retries that step |
| FolderUpload job status/report | C-like polling of jobId (not a page) | prior three-failure/reconnect rule preserved; signal/sequence rejects old job and close/unmount replies; successful report retained on reconnect failure |
| AssetStats summary | S object | one async resource, first/stale retry; errors do not masquerade as successful zeros |
| AssetStats top_assets | B embedded top 10 (backend stats_service.py) | documented ranking cap retained; shares stats request/error/current ownership; no full-library claim |
| AssetStats trend | B embedded 14-day series (same backend) | documented time-window bound retained; shares stats request; chart maximum derives from current collection |
| WigLibrary wigs | F array including inactive | independent async error/retry, applied local keyword; mounted first-error/retry/retained-row fixture test |
| WigLibrary color matrix | F array by wigId | separate clear/cancel/current/error/retry; preserves dirty/photos/business upsert; create/close rejects prior edit reads |
| HairColorLibrary colors | F array, only_active=0 | applied local keyword and retry/stale controller tests; swatch upload/delete-impact behavior retained |
| ScriptLibrary script cards | F array including inactive | applied local type and retry/stale controller tests; forbidden-word/backend write rules retained |
| SceneImages scenes | F mode=tryon array | own retry/stale controller; categories/image upload/delete retained; no ordinary filter or pagination invented |
| ReportCenter templates | F array | errors retained separately from successful collection; retry; write success/read failure separation via boolean resource load |
| ReportCenter version history | F array by report_code | clear/cancel on code/open/close, independent status/retry; actual two-code race regression |
| ReportCenter designer template content/startup | S detail by report_code plus external designer instance | current code/sequence/close checks at read and async startup; stale created instance is disposed; same-code double-start regression |
| SopManagement versions | F full data.items | async first/stale/retry; upload/activation success does not become a write failure when reload fails; existing parsing completeness rule retained |

## Changed files / integration contract

List reads and state/template fragments in AssetLibrary, AssetFavorites, TagDimensionManage, AssetUpload, AssetStats, FolderUploadDialog/useFolderUpload; WigLibrary/useWigLibraryTable, HairColorLibrary, ScriptLibrary, SceneImages; ReportCenter; SopManagement. Parent feedback/status/money/layout changes are retained. AssetTagEditor/tag hierarchy calculations, upload/download bodies, file transfer protocol, scene mode and inactive management semantics are retained.

Read-only API config added only to corresponding asset reads (tag dimensions, asset page, folder collections, stats, validation/preview/analysis metadata and job status), Expo library/matrix reads, ReportCenter template/version/detail reads and SOP version read. Explicit params override config.params. Existing Expo getStoreQuota/listQuotaRecords changes by parent were preserved. No shared core hook changes were made by this worker.

New tests: `frontend/tests/assetExpoListAdoption.test.mjs` (23 cases). New report is in gitignored tmp and must be integrated by parent into DESIGN/handoff/full resource inventory. No new dependency, commit, push, production request or deployment.

## Actual verification and boundaries

- `node --test frontend/tests/assetExpoListAdoption.test.mjs frontend/tests/assetTagFilters.test.mjs frontend/tests/expoKioskIsolationRegression.test.mjs frontend/tests/expoKioskAuth.test.mjs frontend/tests/expoPublicUrl.test.mjs`: **36/36 passed** (23 new, 13 existing).
- Tests execute actual page/controller sources and real shared hooks with fixture APIs. Mounted WigLibrary uses actual FilterBar and ListPageStatus and verifies usable first-error retry, paired controls and successful row retention after refresh failure.
- Scoped SFC compiler: **12 components, 0 failures**. Scoped `git diff --check`: **exit 0**, only Git LF/CRLF conversion notices.
- The test does not claim browser geometry, actual file upload/download, external Stimulsoft runtime, backend writes, permission matrices or production behavior were exercised. Those are unified parent/browser gates.
- Stats top10/trend14 are actual backend bounds, not complete library collections. Folder validation/preview/job polling are workflow resources, not page-based ordinary lists. Local upload queues, selected assets, tag editor selection, scene grouping and tree parent candidates derive from already loaded state and do not get new server pagination.
- Temporary adoption scripts are removed at worker handoff; this report and the meaningful regression file remain.
