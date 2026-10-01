# Design Main List Adoption

## Scope and contract

Completed the assigned MyRequests, AuditQueue, DesignManage (pending/scheduled/completed/designers), CustomerMediaAccounts and CustomerMediaReview lists, including their request-owned detail reads. All changes are limited to list query/paging/error/retry/read ownership and successful mutation refresh. Parent-owned status dictionaries, StatusBadge adoption, feedback, money and drawer/layout changes are retained. No production data, commit, push or deployment was used.

Paged resources use `useListPage`. Query and Reset submit detached drafts; sorting, paging, retry, tool refresh and mutation refresh consume the submitted snapshot. MyRequests has 4 main fields, pending 3, scheduled/completed 4; each task tab has its own submitted dates/filters/sort/page. Page-size choices remain 20/50/100, task initial size remains 50. Initial errors show retry in `#empty`; refresh errors retain successful rows with the data-page marker. AuditQueue has no editable filters, so no artificial FilterBar was added.

The actor key includes authenticated user ID, roles and permissions. Actor changes abort/invalidate prior reads, clear prior rows and task/detail metadata, close old detail contexts, and reload already requested resources using their existing submitted filters. MyRequests forces the real authenticated user ID when the existing self-only permission rule applies; its salesperson control is disabled in that scope. Existing supervisor/design_staff operator fields are preserved; this batch does not alter backend authorization semantics.

Complete-array backend endpoints remain complete-array resources using `useAsyncResource`; they do not invent server pagination. Accounts keep a separate submitted search value. Auxiliary attachments, audit logs, attachment counts, designer options, remote customer options, review dimensions and customer tags have independent error/retry and latest-request guards. A failed attachment count is unknown (`null`), never a fabricated zero. Shared RequestDetailDrawer also watches request ID while open, clears on close and separately retries detail/attachments/logs/dictionary reads.

## Resource coverage

| Entry | Resource | Implementation / evidence |
| --- | --- | --- |
| MyRequests | requests server page | query/sort/date snapshot, forced self scope, first/stale retry; mounted failure/retry/retained row test |
| MyRequests | salesperson choices derived from page | updates only under current request and unchanged actor; clears on actor switch |
| MyRequests | selected request attachments | separate async resource, clear on request switch, abort/late guard, retry |
| MyRequests | selected request audit logs | separate async resource, clear on request switch, abort/late guard, retry |
| AuditQueue | pending audit server page | fixed pending_audit scope, submitted sort/page, first/stale retry; mounted failure/retry/retained row test |
| AuditQueue | summary statistics | writes only when request is current; cleared on actor switch |
| AuditQueue | page attachment counts | independent async collection keyed by current row IDs, count failure remains unknown, retry; old page cannot overwrite counts |
| AuditQueue | selected row attachments | clear before opening a different request, independent failure/retry |
| DesignManage | pending server page | own snapshot/dates/sort/page, paired Query/Reset, semantic update/remove/create refresh |
| DesignManage | scheduled server page | own snapshot/dates/sort/page, complete/cancel remove refresh, start/update preserve effective page |
| DesignManage | completed server page | own snapshot/dates/sort/page, completion creates/refetches page one |
| DesignManage | designers complete array | async collection reused for management and designer selectors; failure/retry, stale retention, actor clear/reload; CRUD reloads submitted collection |
| CustomerMediaAccounts | portal accounts complete array | submitted search, paired Query/Reset, async retry/stale retention; mounted first-error/retry/retained row test |
| CustomerMediaAccounts | remote customer options | async clear on blank/new search/open/create/actor change, latest search guard, independent retry |
| CustomerMediaReview | pending review complete array | async failure/retry/stale retention, actor clear/reload, successful decisions reload collection |
| CustomerMediaReview | tag dimensions | independent async resource and retry, actor clear/reload |
| CustomerMediaReview | current batch customer tags | batch ID snapshot, clear before context switch, late guard, retry; tag write applies only to same batch/asset/actor |
| RequestDetailDrawer | current request detail | watches both open state and ID, clear on close/switch, failure/retry/late guard |
| RequestDetailDrawer | current request attachments | independent request-owned failure/retry/late guard |
| RequestDetailDrawer | current request audit logs | independent request-owned failure/retry/late guard |
| RequestDetailDrawer | shoot/props/customer-level dictionaries + designers | grouped metadata resource, separate error/retry, invalidated on close/switch |

## API and mutation integration

`frontend/src/api/design.js`: trailing optional config added to getRequests/getTaskList/getRequestDetail/getDesigners/getAuditLogs/getAttachments. `frontend/src/api/customerMedia.js`: added to searchMediaCustomers/getPortalAccounts/getMediaReviews/getCustomerTagDimensions/getBatchCustomerTags. All adopted network reads pass signal/suppressToast and preserve the full success envelope; explicit query params override config.params. Existing upload and URL-response normalization stays intact.

Confirmation removes the pending row and refreshes scheduled at page one. Task completion/cancel removes from scheduled; completion refreshes completed at page one. Pending import uses create refresh. Edits use update refresh. MyRequests cancellation and AuditQueue approval/rejection use effective-page refresh. Nonpaged designers/accounts/reviews reread their current collection. Review confirmation snapshots the batch/context before the confirm dialog and refuses an action when the opened context changes; old tag writes cannot replace a newer asset context.

## Actual verification

- `node --test frontend/tests/designListAdoption.test.mjs frontend/tests/designRemark.test.mjs frontend/tests/designAppointmentContract.test.mjs frontend/tests/customerMediaGrouping.test.mjs frontend/tests/customerMediaTags.test.mjs`: **40/40 passed** (19 adoption cases and 21 existing domain cases).
- Adoption tests execute actual page/controller source with fixture APIs and real useListPage/useAsyncResource. They cover independent tab snapshots/date/sort, first/stale failure, forced self/actor switch, task move and effective last page, attachment counts, detail races, remote options, current review tag context, API config and three mounted first-error/retained-row scenarios.
- Existing design remark tests retained their business assertions and now supply the added shared hook/auth dependencies.
- Scoped SFC compilation: **6 files, 0 failures** (MyRequests, AuditQueue, DesignManage, CustomerMediaAccounts, CustomerMediaReview, RequestDetailDrawer).
- Scoped `git diff --check`: **exit 0**; only existing Git LF/CRLF conversion notices. Temporary adoption scripts were removed after verifying their absolute paths stay inside this worktree.

## Explicit boundaries / parent integration

- No backend change was needed: portal accounts, media reviews, designers, remote customer search and tag endpoints actually return complete arrays. Local review grouping/tag filters still operate over that collection.
- DesignCalendarConfig, DesignCapacityConfig, GanttView, SubmitRequest, CustomerMediaWorkspace, AI/image-studio resources and tag-picker internal CRUD are outside this assigned entry list. No claim is made about their resource adoption; preserve parent/other changes there.
- Existing cached `getDictMap` page label helpers were retained. RequestDetailDrawer's combined metadata wrapper guards its own state; dictionary helper internals are unchanged.
- New helper `frontend/src/views/design/designListScope.js` uses page-local actor getters and `clearListResource`; it introduces no global list store or magic event.
- Parent integrates this report with DESIGN/handoff/list ledger, then runs the unified full build/gates/git sweep. This worker does not rerun unrelated full build or deploy.
