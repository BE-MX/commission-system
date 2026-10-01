# Image / Chat / Customer Image Admin / WhatsApp Resource Adoption

## Assigned scope and completion

Implemented the assigned session collections, customer image admin collections and WhatsApp connector collections. Public customer-image portal and streaming/generation/billing business protocols are excluded. No commit, push, deployment or whole-site build was performed. Parent owns full inventory and shared gates.

Real collection bounds are retained: image studio uses backend cursor/default batch 20 and deduplicated append; chat deliberately displays the most recent 30 sessions even though the backend exposes a cursor; WhatsApp continues to display the first 50 conversations and the latest 50 messages, with explicit visible bound/total labels. These bounded resources are not presented as complete arrays or fabricated numbered pagination. Invites and generation usage are actual server-paged resources using useListPage, default20 and 20/50/100 sizes.

No ordinary main list search exists in this scope, so no artificial FilterBar was inserted. Session/account/conversation navigation commits scope immediately. The remote customer picker uses the typed term as its explicit remote-query boundary, is bounded to 20 by the backend, clears when the term changes, and retries its last submitted term. Template copy-library role/position selection and publication validation remain dedicated workflows.

## Per-resource ledger (14 resources)

| Resource | Real shape / bound | Implemented contract and evidence |
| --- | --- | --- |
| image.sessions | C items/next_cursor; server default20 | useImageSessionList owns useAsyncResource read state, load lock, cursor snapshot and ID dedup; append failure retains successful history, retry repeats failed cursor; actor switch clears/cancels before new load; real controller deferred-response tests |
| chat.sessions | B recent30 | independent async collection, exact limit30, first/stale/retry, actor switch aborts read and clears private in-memory drafts/session; actual mounted sidebar first error retry and stale-row visibility |
| image-admin.products | F array | independent async collection; failed reread retains successful products; actor/role scope clears; local write result retained if subsequent read fails; controller tests |
| image-admin.product-covers | D blob per product+cover version | separate error/loading and per-row retry; request AbortSignal, version/desired guard, URL revocation on replace/clear; tests reject late URL creation and recover failed cover |
| image-admin.customer-options | B remote lookup max20 | async term snapshot, same-term failure retains options, changed/empty term clears, close cancels; dedicated picker inline retry; plaintext invite behavior unchanged |
| image-admin.invites | P items/total | useListPage default20, applied page/size retry and successful dataPage metadata; create refreshes page1 while retaining one-time plaintext URL after read failure; revoke retains original in-place update and cancels earlier list read |
| image-admin.generations | P items/total | separate useListPage/default20/20,50,100, first/stale/retry independent of products/invites; unchanged status/usage business; pagination snapshot controller test |
| image-admin.product-assets | F array by productId | editor async resource independent from library; opening/reset/closing clears/cancels scope; read failure is inline retry; successful upload/copy/delete/reorder reread failure does not throw a write failure |
| image-admin.library-assets | F combined public/private items | independent async read and stale retry in copy dialog; close/scope change clears/cancels; does not fabricate page; controller tests |
| image-admin.product-asset-previews | D blob by productId+assetId | existing versioned blob controller preserved with signal/current guard; preview errors/retry remain separate from asset collection status; existing actual domain blob tests pass |
| image-admin.library-previews | D blob by library assetId | existing current blob controller preserved, batch retry of failed preview IDs outside nested selection buttons; close/invalidation rejects late URLs; existing domain blob tests pass |
| whatsapp.accounts | F array | own async first/stale/retry; current read reconciles selected account; auth/role change clears all three resources; missing account clears children |
| whatsapp.conversations | B page1/size50 per account | own async scope/error; account switch clears conversations/messages before fetch; total assigned only current; first50 visible label; exact retry and late-account regression |
| whatsapp.messages | B page1/size50 per account+conversation | own async scope/error; thread switch clears first; current-only total; latest50 visible label and original descending-server/reversed-display order retained; exact retry/stale/late-thread regression |

All full/bounded async statuses use paged=false. Table-empty statuses are unconditional inside the empty slot; stale-data banners are outside it. A read failure is not rendered as successful empty. Write success followed by independent read failure resolves the write and exposes read retry separately.

## API and responsibility changes

Read methods alone accept optional trailing configs forwarding signal and suppressToast: designImage.listSessions, aiChat.listSessions; customerImage.searchCustomers/listProducts/listProductAssets/getProductCoverBlob/listLibraryAssets (existing listInvites/listGenerations configs retained); whatsapp.listWhatsAppAccounts/listWhatsAppConversations/listWhatsAppMessages. Defaults and existing write/stream API contracts are preserved. Actual wrapper tests assert forwarding and query bounds.

useImageSessionList is a coherent extraction of cursor collection state/merge/load/retry/clear from useImageStudio. The main controller remains489lines and retains generation/polling/attachment business. The existing under500 assertion was expanded to include the new helper, not weakened. Image initialization/config/active-jobs/late writes receive actor-generation guards; auth changes cannot repopulate previous actor history. useChatDrafts adds a narrowly scoped clear() for actor changes.

Files: design/image-studio/useImageStudio + new useImageSessionList + ConversationSidebar + ImageStudio; design/ai-chat/useAiChat + useChatDrafts + ChatSidebar + AiChat; customer-image/admin useCustomerImageAdmin, CustomerImageAdmin, ProductTemplateList, ProductTemplateEditor, InviteList, InviteCreateDialog, GenerationUsageList; system/WhatsAppConnector; the four corresponding API modules; focused tests plus existing aiChatState/customerImageAdmin/designImageState harness/contract adjustments.

## Actual verification

- Focused new tests: imageWhatsAppListAdoption.test.mjs (15 tests): actual controllers + deferred fake API responses, actual mounted ChatSidebar retry, and actual API wrapper forwarding. Fixture-only requests; no production reads/writes.
- Domain run: node --test tests/imageWhatsAppListAdoption.test.mjs tests/customerImageAdmin.test.mjs tests/customerImageInvite.test.mjs tests/customerImageApi.test.mjs tests/designImageState.test.mjs tests/designImageStudioRecovery.test.mjs tests/designImageInteraction.test.mjs tests/designImageConcurrency.test.mjs tests/aiChatState.test.mjs. Actual result: 119/119 passed, 0 failed (15 new and104 existing).
- Vue compileScript+compileTemplate: 11 assigned SFCs, 0 errors. Includes both session sidebars, both workspace views, six admin SFCs and WhatsAppConnector.
- Scoped git diff --check: 0 errors.
- Final stdout retained: frontend/tmp/image-whatsapp-final-tests.txt. Whole-site gates/git sweep remain parent-owned; no duplicate global gates run.

## Deliberate bounds and verification limits

Chat has no newly invented load-more UI; its recent30 bound is displayed. WhatsApp backend accepts real pages but existing connector is intentionally a bounded monitor; explicit first/latest50 labels meet this batch contract rather than adding navigation. Customer lookup has a true backend20 cap. Publication eligibility asset read remains an action-specific validation dependency, not a user-browsable collection; original validation/errors/publish operation retained. WhatsApp bind-session polling remains its existing dedicated workflow. Image job polling/config, chat message streaming, generated image billing, and public customer portal are not reworked as collections.

Frontend tests and SFC compilation validate resource state and UI contracts; no live browser, live backend integration, production data, provider generation or connector synchronization was executed. Parent must merge this ledger into the full resource inventory and run shared final gates.
