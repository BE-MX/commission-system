# Knowledge deletion and dirty-state design

## Goal

Add safe deletion for knowledge libraries, folders, and documents, and remove false “unsaved changes” prompts during document loading and saving.

## Decisions

- Deletion is soft deletion using the existing `deleted_at` columns.
- Deleting a folder soft-deletes its complete descendant subtree.
- Deleting a library soft-deletes the library and every folder and document inside it.
- Any pending approval for deleted content is cancelled so it disappears from the approval queue.
- Library deletion requires both the platform `knowledge:admin` permission and library `admin` role.
- Folder and document deletion requires platform write permission and library `editor` or `admin` role.
- Reviewer and viewer roles never see delete controls; backend authorization remains authoritative.
- Recovery and a recycle-bin interface are outside this change.

## Backend behavior

### Endpoints

- `DELETE /knowledge/libraries/{library_id}`
- `DELETE /knowledge/documents/{document_id}` for both folders and documents

Both endpoints return a summary containing the deleted object ID and affected counts. They use the existing response envelope and permission dependencies.

### Library deletion

1. Load the active library with `admin` capability.
2. Collect all non-deleted nodes in the library.
3. Mark every collected node and the library with the same deletion timestamp.
4. Cancel pending approvals for collected documents by setting status to `cancelled`, clearing `pending_slot`, recording the actor and time, and clearing each document's `pending_approval_id`.
5. Append one `delete_library` audit event with document, folder, and cancelled-approval counts.
6. Commit atomically.

### Node deletion

1. Load the active node with `write` capability.
2. For a document, target only that node. For a folder, walk parent relationships and collect the complete descendant subtree.
3. Soft-delete every target node and cancel pending approvals as above.
4. Append one `delete_document` or `delete_folder` audit event with affected counts.
5. Commit atomically.

Existing active-record filters keep deleted content out of library lists, trees, document reads, published search, and MCP retrieval. Cancelling approvals keeps it out of the pending approval queue.

## Frontend behavior

### Delete controls

- Each library row shows a compact delete icon for library admins. Clicking it does not select the library.
- Each folder and document tree row shows a delete icon on hover/focus for editors and admins. Clicking it does not open the node.
- The open document header also includes a delete action for editors and admins.
- Confirmation text names the target. Folder and library confirmations explicitly say their contained content will also be deleted.
- After deleting the open document or an ancestor folder, clear the editor and refresh the tree.
- After deleting the selected library, refresh libraries and automatically select the first remaining accessible library.
- Success feedback includes the affected node count. API failures retain the current screen and use the global actionable error feedback.

No decorative entrance or deletion animation is added. Hover and press feedback reuse the existing short, reduced-motion-aware button behavior.

## Dirty-state correction

The current bug has two independent causes:

1. Tiptap v3 requires `setContent(content, { emitUpdate: false })`; the old boolean form does not suppress `onUpdate`, so server hydration marks the document dirty.
2. Save and approval refreshes call the same `selectDocument` function as user navigation. That function invokes the discard guard before the save callback clears dirty state.

The correction is:

- Hydrate editor content with the Tiptap v3 options object so programmatic loads never emit user-change events.
- Keep `selectDocument` exclusively for user navigation and apply the discard guard there.
- Add an internal `reloadDocument` path for save, approval, and other system refreshes; it never asks to discard.
- Ignore selection of the already-open document ID.
- After a successful save, reload the authoritative document, wait for Vue hydration, then call the editor's save-complete callback so the visible saved timestamp remains correct.
- A failed save keeps the dirty state and exposes the existing retry feedback.

The discard prompt remains for genuine edits when switching documents, switching libraries, following search results, leaving the route, or closing the browser tab.

## Verification

Backend tests cover:

- document soft deletion and audit entry;
- recursive folder deletion;
- library deletion;
- pending approval cancellation;
- editor/admin success and viewer/reviewer rejection;
- deleted content absent from tree, direct reads, search, and approval queue.

Frontend tests cover:

- Tiptap hydration suppresses update events with the v3 options form;
- same-document selection skips the guard and reload;
- user navigation still prompts for genuine dirty content;
- save uses internal reload and does not call guarded selection;
- delete controls are role-gated and stop click propagation;
- deleting selected content resets editor and selection correctly.

Completion requires focused backend and frontend tests, the production frontend build, and the repository convention check.
