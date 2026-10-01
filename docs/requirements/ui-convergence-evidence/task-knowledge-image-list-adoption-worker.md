# Task / knowledge / image library list adoption

## Scope and contract

- Worker owns only task center/detail read and list fragments, KnowledgeWorkbench/sidebar/member/approval read fragments, the three image library dialogs and their thumbnail URL helper, related read API configs, and focused tests. Parent edits to status, feedback, layout, money and other modules were preserved.
- All resources below are complete collections, bounded search results or details. No server pagination was invented. Task hierarchy and knowledge parent_id trees stay intact.
- Shared `useAsyncResource` provides first failure, stale retained data, retry of the submitted read, abort and latest-response guard. Each ListPageStatus explicitly has `paged=false`.
- Task filters (keyword, module, priority group, hide-closed) and inactive-template filter use draft/applied snapshots and paired FilterBar query/reset. Knowledge full-text search records submitted query and retries that query; its sidebar preserves collapse/focus and paired query/reset.
- Scope navigation (public/private gallery, knowledge library/tree, task actor, image actor/permissions) clears old resource data and aborts outstanding requests. Ordinary knowledge library/document navigation still calls the existing dirty guard. Forced actor/permission change discards inaccessible old actor data.
- Read failure returns false, so a confirmed successful status write, template save/enable/disable/seed, knowledge document save/submit/CRUD/member replacement, or reference upload/delete is not reported as a failed write because its reread failed.

## Resource ledger

| Resource | Real API / boundary | Implementation and evidence |
|---|---|---|
| task.tree | GET items, complete nested task tree | treeResource; filters applied locally without flattening; ancestor-preservation, stale error, actor switch and late read fixtures |
| task.stats | GET stats, independent counts | statsResource; failed first read shows em dash, failure never erases a successful task tree |
| task.modules | GET modules, complete built-in + personal categories | modulesResource; independent retry; custom add/remove rereads current complete collection |
| task.brief | GET brief/today, summary detail, original 90 second timeout | briefResource; independent retry and stale retained brief; no fake list/page |
| task.trash | GET trash, complete deleted task collection | trashResource; retry inside popover; empty only after successful empty read; restore refreshes tree and trash independently |
| task.detail.children/events/links | GET items/:id, one task detail containing related arrays | detailResource owns task ID; switching/closing clears and aborts; first failure leaves drawer open; current-only form hydration; real controller test |
| knowledge.libraries | GET libraries, role-filtered complete accessible libraries | librariesResource; first/stale/retry; reconciliation clears removed library tree/document; forced actor clears old role data |
| knowledge.library-tree | GET libraries/:id/tree, complete folder/document array | treeResource; retains parent_id/nestedTree; library switch clears first, rejects late tree; dirty-guard cancellation fixture |
| knowledge.document | GET documents/:id, current editor detail | documentResource; latest ID + library scope, clear on ordinary selection after dirty confirmation; same-document internal reload does not ask discard; editor save callbacks unchanged |
| knowledge.approvals | GET approvals, complete accessible approval queue | approvalsResource; drawer opens before request, first failure shown with retry; actual mounted queue retry event tested |
| knowledge.approval-review | GET approvals/:id, frozen revision detail | reviewResource; separate identity, dialog opens before read, old frozen response rejected; buttons unavailable during failed/loading detail |
| knowledge.members | GET libraries/:id/members, complete editable member set | membersResource; opens on first failure, retry clicked library ID, close aborts; replacement locked while reading/error/unloaded; invalid member/protected admin rules preserved |
| knowledge.member-candidates | GET libraries/:id/member-candidates, q + actual limit 20 | candidatesResource; remote dropdown query is explicit submission boundary; new query/library clears, repeated query retains stale matches on failure; retry reuses last submitted query |
| knowledge.search | GET search, q + actual limit 20 | searchResource; no pagination; appliedSearchQuery, paired query/reset, stale matches and retry of submitted query instead of draft fixture |
| image.reference-library | GET library-assets, complete items in public/private scope | listResource; scope clears selection/items/URL registry; stale collection retained within scope; upload finishing in old scope cannot prepend into current scope |
| image.reference-thumbnails | GET library-assets/:id/content?thumbnail=true, one authenticated Blob per item | thumbnailResource batch exposes read error/retry; URL helper generation + abort prevent object URL creation after scope/close; pending same ID cache remains safe |
| image.prompt-template-manager | GET prompt-templates include_inactive, complete items; admin inactive access | listResource; draft/applied switch, reset defaults includeInactive=true, preserves inactive management; successful save survives failed reread fixture |
| image.prompt-library | GET prompt-templates, active complete items | listResource; local category chips remain explicit navigation exception; reread reconciles selected template to latest metadata and current category; close/actor abort |
| image.pantone-library | GET pantone-colors, complete color items | independent pantoneResource/cache; read retry; local picker search remains immediate specialized choice behavior; rendering cap remains 240 with actual total displayed, not pagination |

## API changes

`api/task.js`: listTasks/getTask/listTrash/getTaskStats/listTaskModules/getTodayBrief accept optional trailing config, preserve quiet read and brief timeout.
`api/designImage.js`: listPromptTemplates and listLibraryAssets trailing config; listPantoneColors config; getLibraryAssetBlob preserves thumbnail option and forwards remaining read config. Other session/generation/blob APIs were preserved.
Knowledge uses its existing shared client directly with signal, suppressToast=true, showLoading=false. No dependencies or backend changes.

## Validation

- New `tests/taskKnowledgeImageListAdoption.test.mjs`: 19 real controller/API/URL-lifecycle/mounted tests. Fixtures only, no production requests.
- New tests cover hierarchy + submitted local filters, independent stats failure, actor clear/late response, successful write vs failed reread, dirty cancel vs confirmed library switch, submitted bounded search retry, members first failure/library race/candidate stale and close, frozen review identity, gallery scope/thumbnail failure and URL cleanup, late upload, inactive reset, color render cap, task detail identity, and actual retry clicks in mounted queue/template manager.
- Existing knowledge static assertions were updated to the resource/paired-filter contract, preserving permission, invalid member, protected admin, single-flight save, editor hydration, dirty confirmation, accessibility and layout assertions. Behavior is also exercised by the new controller tests.
- `compileScript` + `compileTemplate`: all 10 touched SFCs passed, 0 errors.
- Final focused command, from frontend cwd:
  `node --test tests/taskKnowledgeImageListAdoption.test.mjs tests/taskCenter.test.mjs tests/knowledgeState.test.mjs tests/knowledgeSidebar.test.mjs tests/knowledgeEditor.test.mjs tests/designImageState.test.mjs tests/designImageInteraction.test.mjs tests/designImageConcurrency.test.mjs`
- Final stdout retained in `frontend/tmp/task-knowledge-image-final-test-output.txt`. Running the existing in-memory Vite API test from repository root uses the wrong resolution root; frontend cwd passes its unchanged actual import/build check.

## Limits / parent integration

- These are fixture/controller and in-memory mounted tests, not live backend/browser QA. No full-site build, global gates, commit, push or deployment was run by worker.
- Parent should integrate these 19 resource rows into full-list-resource-inventory, DESIGN/handoff and global gate results. This ledger is scoped delivery evidence; other domains and portal/editor/generation/streaming business are outside this batch.

Final result: 104/104 focused tests passed (19 new + 85 existing); scoped git diff --check exited 0. Only Node's localStorage availability experimental notice appeared; no test was skipped.
