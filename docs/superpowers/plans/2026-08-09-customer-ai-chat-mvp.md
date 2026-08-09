# Customer AI Chat MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a private, streaming, attachment-aware “方案对话” tab beside the existing AI image studio, backed by TeamRouter `claude-fable-5` through the shared AI facade.

**Architecture:** Keep `design_image` unchanged as a business domain and add `app/ai_chat` for text conversations, messages, private attachments, ownership, and SSE orchestration. Extend `app.ai.service` with provider-neutral streaming, then expose a native-fetch SSE client and a Vue chat workspace that shares only the top-level tab shell with the image studio.

**Tech Stack:** FastAPI, SQLAlchemy 2, Alembic, httpx streaming, Pillow, pypdf, python-docx, openpyxl, python-pptx, Vue 3, Element Plus, marked, DOMPurify, native Fetch/ReadableStream, Node test runner, pytest.

---

## File map

**Create**

- `backend/alembic/versions/100_ai_chat_mvp.py` — three-table persistence migration.
- `backend/app/ai_chat/__init__.py` — domain package marker.
- `backend/app/ai_chat/models.py` — sessions, messages, attachments.
- `backend/app/ai_chat/schemas.py` — request/response validation.
- `backend/app/ai_chat/file_service.py` — private storage, format validation, image normalization, document extraction.
- `backend/app/ai_chat/service.py` — owner-scoped CRUD, context building, idempotent turns, terminal state writes.
- `backend/app/ai_chat/router.py` — permission dependencies, upload/content endpoints, SSE responses.
- `backend/tests/test_ai_chat_models.py` — schema and migration-shaped invariants.
- `backend/tests/test_ai_chat_files.py` — format, extraction, limits, and storage boundary tests.
- `backend/tests/test_ai_chat_stream.py` — provider stream parsing and AI call log tests.
- `backend/tests/test_ai_chat_service.py` — ownership, idempotency, attachment binding, context, and state tests.
- `backend/tests/test_ai_chat_router.py` — permission/envelope/SSE contract tests.
- `frontend/src/api/aiChat.js` — axios CRUD plus authenticated native-fetch SSE client.
- `frontend/src/views/design/ai-workspace/AiWorkspaceTabs.vue` — shared route-backed mode switch.
- `frontend/src/views/design/ai-chat/AiChat.vue` — page shell.
- `frontend/src/views/design/ai-chat/state.js` — pure reducers and SSE frame parser.
- `frontend/src/views/design/ai-chat/composables/useAiChat.js` — page state and effects.
- `frontend/src/views/design/ai-chat/components/ChatSidebar.vue` — sessions and narrow-screen drawer.
- `frontend/src/views/design/ai-chat/components/ChatThread.vue` — safe Markdown messages and stream state.
- `frontend/src/views/design/ai-chat/components/ChatComposer.vue` — prompt, attachment strip, send/stop.
- `frontend/src/views/design/ai-chat/components/StarterCards.vue` — four fixed MVP starters.
- `frontend/tests/aiChatState.test.mjs` — reducer, SSE, starter, retry, and route contract tests.

**Modify**

- `backend/requirements.txt` — add `python-pptx`.
- `backend/app/core/config.py` — add `AI_CHAT_STORAGE_ROOT` and upload/context limits.
- `backend/app/ai/call_service.py` — add provider-neutral streaming and safe log snapshots.
- `backend/app/ai/service.py` — re-export `chat_stream`.
- `backend/app/auth/service.py` — seed `ai_chat:read/write/admin`.
- `backend/app/models/__init__.py` — register new models.
- `backend/app/routers.py` — register `/api/ai-chat`.
- `backend/tests/conftest.py` — import AI chat metadata.
- `frontend/package.json`, `frontend/package-lock.json` — add `marked` and `dompurify`.
- `frontend/src/api/clients.js` — register `aiChatClient`.
- `frontend/src/config/navigation.js` — rename menu entry and add hidden route.
- `frontend/src/views/design/image-studio/ImageStudio.vue` — add shared tabs without changing image flow.
- `docs/api-reference.md`, `docs/database.md`, `docs/module-notes.md` — document API, tables, Provider/Preset setup and limitations.

## Spec coverage map

- Unified `AI 生图 / 方案对话` tabs and a single visible `AI 工作台` menu entry: Task 6.
- Owner-private sessions, messages, attachments, uniform cross-owner 404, and `ai_chat:read/write/admin`: Tasks 1 and 4.
- SSE streaming, stop, retry, actionable failure, partial-content persistence, and AI call logs: Tasks 3–6.
- JPEG/PNG/WebP plus PDF/DOCX/XLSX/PPTX/TXT/Markdown, 4 MiB per file, five attachments, 60,000 chars per file, and 120,000 chars per turn: Tasks 1, 2, and 4.
- Four fixed business starter cards that fill without auto-send, plus unrestricted free chat: Tasks 5 and 6.
- Last 20 nonfailed messages, request-id idempotency, atomic draft binding, and no automatic fallback model: Tasks 3 and 4.
- Safe Markdown, private content access, path/reparse protection, prompt-injection boundary, and no raw secret/error exposure: Tasks 2, 4, and 6.
- Keyboard/streaming motion removal, hover gating, GPU-only transitions, and `prefers-reduced-motion`: Tasks 6 and 7.
- API/database/operations documentation, conventions, full pytest, all Node tests, build, independent adversarial review, and motion review: Task 7.

### Task 1: Persistence, settings, permissions, and registration

**Files:**
- Create: `backend/alembic/versions/100_ai_chat_mvp.py`
- Create: `backend/app/ai_chat/__init__.py`
- Create: `backend/app/ai_chat/models.py`
- Create: `backend/app/ai_chat/schemas.py`
- Modify: `backend/app/core/config.py`
- Modify: `backend/app/auth/service.py`
- Modify: `backend/app/models/__init__.py`
- Modify: `backend/app/routers.py`
- Modify: `backend/tests/conftest.py`
- Test: `backend/tests/test_ai_chat_models.py`

- [ ] **Step 1: Write failing model and schema tests**

```python
def test_message_idempotency_and_attachment_ownership_constraints():
    table = AiChatMessage.__table__
    assert any(c.name == "uq_ai_chat_message_session_request" for c in table.constraints)
    assert AiChatAttachment.__table__.c.message_id.nullable is True

def test_turn_request_rejects_blank_turn_and_more_than_five_attachments():
    with pytest.raises(ValidationError):
        TurnStreamRequest(request_id="turn-0001", content="", attachment_ids=[])
    with pytest.raises(ValidationError):
        TurnStreamRequest(request_id="turn-0001", content="分析", attachment_ids=list(range(6)))
```

- [ ] **Step 2: Run the focused test and verify RED**

Run: `cd backend && pytest tests/test_ai_chat_models.py -q`

Expected: collection fails because `app.ai_chat` does not exist.

- [ ] **Step 3: Add models and request schemas**

```python
class AiChatMessage(Base):
    __tablename__ = "ark_ai_chat_messages"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    session_id = Column(BigInteger, ForeignKey("ark_ai_chat_sessions.id", ondelete="RESTRICT"), nullable=False)
    role = Column(String(16), nullable=False)
    request_id = Column(String(64), nullable=True)
    content = Column(Text, nullable=False, default="")
    status = Column(String(16), nullable=False, default="completed")
    error_message = Column(Text, nullable=True)
    retry_of_message_id = Column(BigInteger, ForeignKey("ark_ai_chat_messages.id", ondelete="RESTRICT"), nullable=True)
    ai_call_log_id = Column(BigInteger, ForeignKey("ark_ai_call_logs.id", ondelete="RESTRICT"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    __table_args__ = (
        UniqueConstraint("session_id", "request_id", name="uq_ai_chat_message_session_request"),
        Index("idx_ai_chat_message_session_created", "session_id", "created_at"),
    )

class TurnStreamRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: str = Field(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    content: str = Field(default="", max_length=12000)
    attachment_ids: list[int] = Field(default_factory=list, max_length=5)
    @model_validator(mode="after")
    def require_content_or_attachment(self):
        if not self.content.strip() and not self.attachment_ids:
            raise ValueError("消息或附件至少填写一项")
        return self
```

Add `AiChatSession` and `AiChatAttachment` exactly as specified in the design, with owner indexes, noload relationships, attachment draft status, and `USER_ID` matching `ark_users.id` unsigned MySQL type.

- [ ] **Step 4: Add migration and registrations**

Create revision `100_ai_chat_mvp`, down revision `099_sales_automation`, the three tables, named constraints/indexes, and complete downgrade in reverse FK order. Register models, router import placeholder, and test metadata import. Add:

```python
AI_CHAT_STORAGE_ROOT: str = r"D:\WORKSOURCE\ai-chat"
AI_CHAT_MAX_UPLOAD_BYTES: int = 4 * 1024 * 1024
AI_CHAT_MAX_ATTACHMENTS: int = 5
AI_CHAT_MAX_ATTACHMENT_CHARS: int = 60_000
AI_CHAT_MAX_TURN_ATTACHMENT_CHARS: int = 120_000
```

Seed permissions:

```python
("ai_chat:read", "ai_chat", "read", "查看 AI 方案对话"),
("ai_chat:write", "ai_chat", "write", "创建会话、上传附件和发送消息"),
("ai_chat:admin", "ai_chat", "admin", "管理 AI 方案对话配置与异常"),
```

- [ ] **Step 5: Run focused tests and migration inspection**

Run: `cd backend && pytest tests/test_ai_chat_models.py -q`

Expected: all tests pass.

Run: `cd backend && alembic heads`

Expected: exactly `100_ai_chat_mvp (head)`.

- [ ] **Step 6: Commit Task 1**

```bash
git add backend/alembic/versions/100_ai_chat_mvp.py backend/app/ai_chat backend/app/core/config.py backend/app/auth/service.py backend/app/models/__init__.py backend/app/routers.py backend/tests/conftest.py backend/tests/test_ai_chat_models.py
git commit -m "feat(ai-chat): add conversation persistence"
```

### Task 2: Private attachment storage and extraction

**Files:**
- Create: `backend/app/ai_chat/file_service.py`
- Modify: `backend/requirements.txt`
- Test: `backend/tests/test_ai_chat_files.py`

- [ ] **Step 1: Write failing extractor and boundary tests**

```python
@pytest.mark.parametrize("name", ["brief.md", "notes.txt"])
def test_text_documents_extract_and_strip_nul(name, tmp_path, monkeypatch):
    monkeypatch.setattr(file_service, "_storage_root", lambda: tmp_path)
    stored = file_service.normalize_and_store(name, "text/plain", b"hello\x00world")
    assert stored.extracted_text == "helloworld"
    assert stored.storage_path.startswith("documents/")

def test_storage_rejects_parent_escape(tmp_path, monkeypatch):
    monkeypatch.setattr(file_service, "_storage_root", lambda: tmp_path)
    with pytest.raises(FileStorageError):
        file_service.resolve_private_path("../secret.txt")

def test_scanned_pdf_has_actionable_failure(scanned_pdf_bytes):
    with pytest.raises(FileValidationError, match="可复制文本"):
        file_service.extract_document("scan.pdf", "application/pdf", scanned_pdf_bytes)
```

Add fixtures for DOCX paragraphs/tables, XLSX visible cells, PPTX text, PDF text, a valid image, a spoofed extension, 4 MiB + 1 byte, per-file 60,000-char truncation, and a symlink/junction boundary where supported.

- [ ] **Step 2: Run the focused test and verify RED**

Run: `cd backend && pytest tests/test_ai_chat_files.py -q`

Expected: import fails because `file_service` is absent.

- [ ] **Step 3: Add the maintained PPTX dependency**

Append `python-pptx>=1.0` next to the existing office-document dependencies in `backend/requirements.txt`.

- [ ] **Step 4: Implement deterministic extraction limits**

```python
EXTRACTORS = {
    ".pdf": _extract_pdf,
    ".docx": _extract_docx,
    ".xlsx": _extract_xlsx,
    ".pptx": _extract_pptx,
    ".txt": _extract_text,
    ".md": _extract_text,
}

def _bounded_text(parts: Iterable[str], limit: int) -> tuple[str, bool]:
    text = "\n".join(part.strip() for part in parts if part and part.strip()).replace("\x00", "")
    if len(text) <= limit:
        return text, False
    return text[:limit] + "\n[内容已按系统上限截断]", True
```

Use `PdfReader`, `Document`, `load_workbook(read_only=True, data_only=True)`, and `Presentation` against `BytesIO`. Reject encrypted PDFs, legacy Office suffixes, empty/scanned documents, corrupt ZIP containers, mismatched image magic, decompression bombs, and dimensions above 60 MP.

- [ ] **Step 5: Implement atomic private storage**

Anchor all paths to `AI_CHAT_STORAGE_ROOT`, reject absolute/drive/parent traversal and every existing reparse point, write to an exclusive UUID temp file, `fsync`, then `os.replace`. Store documents under `documents/` and normalized images under `images/`; return only a relative path.

- [ ] **Step 6: Run focused tests**

Run: `cd backend && pytest tests/test_ai_chat_files.py -q`

Expected: all attachment tests pass.

- [ ] **Step 7: Commit Task 2**

```bash
git add backend/requirements.txt backend/app/ai_chat/file_service.py backend/tests/test_ai_chat_files.py
git commit -m "feat(ai-chat): validate private attachments"
```

### Task 3: Provider-neutral streaming in the AI facade

**Files:**
- Modify: `backend/app/ai/call_service.py`
- Modify: `backend/app/ai/service.py`
- Test: `backend/tests/test_ai_chat_stream.py`

- [ ] **Step 1: Write failing Anthropic/OpenAI stream parser tests**

```python
def test_parse_anthropic_stream_collects_text_and_usage():
    events = list(parse_provider_stream("anthropic", ANTHROPIC_SSE_LINES))
    assert [e["text"] for e in events if e["type"] == "delta"] == ["客户", "方案"]
    assert events[-1] == {"type": "done", "input_tokens": 12, "output_tokens": 8, "total_tokens": 20}

def test_parse_openai_stream_stops_at_done():
    events = list(parse_provider_stream("openai", OPENAI_SSE_LINES))
    assert "".join(e["text"] for e in events if e["type"] == "delta") == "完成"
```

Add tests for split UTF-8 lines, comment/blank lines, Anthropic `error`, OpenAI error JSON, empty content, consumer close, and `AiCallLog` success/error finalization.

- [ ] **Step 2: Run focused tests and verify RED**

Run: `cd backend && pytest tests/test_ai_chat_stream.py -q`

Expected: import fails because `chat_stream` and `parse_provider_stream` do not exist.

- [ ] **Step 3: Implement SSE line parsing**

```python
def parse_provider_stream(api_type: str, lines: Iterable[str]) -> Iterator[dict]:
    for line in lines:
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if not payload or payload == "[DONE]":
            continue
        data = json.loads(payload)
        if api_type == "anthropic":
            yield from _anthropic_stream_event(data)
        else:
            yield from _openai_stream_event(data)
```

The helpers emit only `{type: meta|delta|done|error}` dictionaries and never expose raw provider objects to the business domain.

- [ ] **Step 4: Implement `chat_stream()` with `httpx.Client.stream`**

Load and validate the preset/provider exactly like `chat()`. Build Anthropic or OpenAI bodies with `stream=True`; create a pending `AiCallLog`; use the provider timeout and headers; stream decoded lines; accumulate at most a bounded response snapshot; commit success usage on normal completion and error details on exceptions. On generator close, close the upstream response and mark the log `stopped` without claiming upstream billing cancellation.

Re-export from `app.ai.service`:

```python
from app.ai.call_service import chat, chat_stream, delegate, get_task_result  # noqa: F401
```

- [ ] **Step 5: Run focused tests**

Run: `cd backend && pytest tests/test_ai_chat_stream.py -q`

Expected: all provider and log tests pass.

- [ ] **Step 6: Run existing AI tests to protect callers**

Run: `cd backend && pytest tests/test_ai_service.py tests/test_ai_preset.py -q`

Expected: all existing synchronous AI tests pass.

- [ ] **Step 7: Commit Task 3**

```bash
git add backend/app/ai/call_service.py backend/app/ai/service.py backend/tests/test_ai_chat_stream.py
git commit -m "feat(ai): add provider-neutral chat streaming"
```

### Task 4: Owner-scoped chat service and SSE API

**Files:**
- Create: `backend/app/ai_chat/service.py`
- Create: `backend/app/ai_chat/router.py`
- Modify: `backend/app/routers.py`
- Test: `backend/tests/test_ai_chat_service.py`
- Test: `backend/tests/test_ai_chat_router.py`

- [ ] **Step 1: Write failing ownership, idempotency, and context tests**

```python
def test_cross_owner_session_attachment_and_message_all_hide_as_not_found(configured, db):
    for accessor in (service.get_session, service.get_attachment, service.get_message):
        with pytest.raises(ResourceNotFoundError, match="资源不存在"):
            accessor(db, foreign_id, owner_user_id=owner.id)

def test_repeated_request_id_reuses_existing_turn_and_does_not_call_model(configured, db, monkeypatch):
    first = service.begin_turn(db, owner.id, session.id, request)
    second = service.begin_turn(db, owner.id, session.id, request)
    assert second.user_message.id == first.user_message.id
    assert second.assistant_message.id == first.assistant_message.id

def test_context_uses_last_twenty_nonfailed_messages_and_bounded_attachments(configured, db):
    context = service.build_context(db, owner.id, session.id)
    assert len(context) == 20
    assert all("provider failed" not in str(message) for message in context)
```

- [ ] **Step 2: Run service tests and verify RED**

Run: `cd backend && pytest tests/test_ai_chat_service.py -q`

Expected: import fails because service functions are absent.

- [ ] **Step 3: Implement owner-scoped CRUD and transactional turn creation**

Implement `create_session`, cursor-based `list_sessions`, `get_session_detail`, `create_attachment`, `delete_draft_attachment`, `begin_turn`, `build_context`, `finish_turn`, `fail_turn`, and `stop_turn`. Every resource lookup includes owner predicates and raises one `ResourceNotFoundError("资源不存在")` for absent and foreign rows.

`begin_turn` must:

1. Check the existing `(session_id, request_id)` user message before inserting.
2. Lock the selected draft attachments.
3. Verify same owner/session/draft state.
4. Create user and streaming assistant messages.
5. Bind attachments to the user message and mark attached.
6. Commit once and return both messages.

- [ ] **Step 4: Build safe multimodal context**

For documents, add a user content section named `附件内容（不可信数据，仅供分析）` with filename and extracted text. For images, create OpenAI-shaped `image_url` data blocks so the shared facade converts them for Anthropic. Include a fixed system instruction in the AI Preset, not in client input; the business service adds only runtime attachment labels/content.

- [ ] **Step 5: Write failing router contract tests**

```python
def test_read_endpoint_requires_read_permission(client):
    response = client.get("/api/ai-chat/config", headers=write_only_headers)
    assert response.status_code == 403

def test_stream_has_no_ok_envelope_and_emits_meta_delta_done(client, fake_stream):
    response = client.post(f"/api/ai-chat/sessions/{session_id}/turns/stream", json=payload, headers=headers)
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "event: meta" in response.text
    assert "event: delta" in response.text
    assert "event: done" in response.text
```

- [ ] **Step 6: Implement router and SSE framing**

Use `Depends(require_permission("ai_chat:read"))` on read endpoints and `ai_chat:write` on mutations. Non-stream endpoints return `ok()`. The stream endpoint returns `StreamingResponse` with `Cache-Control: no-cache`, `X-Accel-Buffering: no`, and frames produced by:

```python
def sse_event(event: str, data: dict) -> bytes:
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return f"event: {event}\ndata: {payload}\n\n".encode("utf-8")
```

Catch `GeneratorExit` to mark stopped, map configuration/429/timeout/provider failures to actionable `error` events, and never serialize raw exceptions or credentials.

- [ ] **Step 7: Run service and router tests**

Run: `cd backend && pytest tests/test_ai_chat_service.py tests/test_ai_chat_router.py -q`

Expected: all owner, idempotency, context, permission, upload, content, and SSE tests pass.

- [ ] **Step 8: Commit Task 4**

```bash
git add backend/app/ai_chat/service.py backend/app/ai_chat/router.py backend/app/routers.py backend/tests/test_ai_chat_service.py backend/tests/test_ai_chat_router.py
git commit -m "feat(ai-chat): add private streaming conversations"
```

### Task 5: Frontend API and pure state engine

**Files:**
- Modify: `frontend/src/api/clients.js`
- Create: `frontend/src/api/aiChat.js`
- Create: `frontend/src/views/design/ai-chat/state.js`
- Create: `frontend/tests/aiChatState.test.mjs`

- [ ] **Step 1: Write failing pure state and SSE tests**

```javascript
test('SSE parser preserves split UTF-8 frames', () => {
  const parser = createSseParser()
  assert.deepEqual(parser.push('event: delta\ndata: {"text":"方'), [])
  assert.deepEqual(parser.push('案"}\n\n'), [{ event: 'delta', data: { text: '方案' } }])
})

test('starter fills the composer but never sends', () => {
  const state = createInitialState()
  const next = reduceChatState(state, { type: 'apply-starter', starter: STARTERS[0] })
  assert.match(next.prompt, /客户需求/)
  assert.equal(next.streaming, false)
})
```

Also test meta/delta/done/error transitions, stop, retry append-not-overwrite, stale stream generation guards, max five draft attachments, and session switch reset.

- [ ] **Step 2: Run Node test and verify RED**

Run: `cd frontend && node --test tests/aiChatState.test.mjs`

Expected: module-not-found failure for `state.js`.

- [ ] **Step 3: Implement pure state and parser**

Export `STARTERS`, `createInitialState`, `reduceChatState`, `createSseParser`, and `requestId`. Keep browser APIs out of this file so Node tests run without DOM shims.

- [ ] **Step 4: Register API client and native-fetch stream**

```javascript
export const aiChatClient = createApiClient({ baseURL: '/api/ai-chat', timeout: 120000 })

export async function streamTurn(sessionId, body, { signal, onEvent }) {
  const response = await fetch(`/api/ai-chat/sessions/${sessionId}/turns/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${getAccessToken()}` },
    body: JSON.stringify(body),
    signal,
  })
  // validate status/content-type, read decoded chunks, and dispatch parsed events
}
```

Handle 401 with `clearAuthState()` and login redirect; return actionable JSON detail for other non-2xx responses. CRUD uses `aiChatClient` only.

- [ ] **Step 5: Run Node tests**

Run: `cd frontend && node --test tests/aiChatState.test.mjs`

Expected: all pure state and parser tests pass.

- [ ] **Step 6: Commit Task 5**

```bash
git add frontend/src/api/clients.js frontend/src/api/aiChat.js frontend/src/views/design/ai-chat/state.js frontend/tests/aiChatState.test.mjs
git commit -m "feat(ai-chat): add streaming client state"
```

### Task 6: Chat workspace UI and navigation tabs

**Files:**
- Modify: `frontend/package.json`
- Modify: `frontend/package-lock.json`
- Create: `frontend/src/views/design/ai-workspace/AiWorkspaceTabs.vue`
- Create: `frontend/src/views/design/ai-chat/AiChat.vue`
- Create: `frontend/src/views/design/ai-chat/composables/useAiChat.js`
- Create: `frontend/src/views/design/ai-chat/components/ChatSidebar.vue`
- Create: `frontend/src/views/design/ai-chat/components/ChatThread.vue`
- Create: `frontend/src/views/design/ai-chat/components/ChatComposer.vue`
- Create: `frontend/src/views/design/ai-chat/components/StarterCards.vue`
- Modify: `frontend/src/config/navigation.js`
- Modify: `frontend/src/views/design/image-studio/ImageStudio.vue`
- Modify: `frontend/tests/aiChatState.test.mjs`

- [ ] **Step 1: Add navigation contract assertions**

Extend the Node test to read `navigation.js` and both page sources. Assert one visible menu entry titled `AI 工作台`, a hidden `/design/ai-chat` route requiring `ai_chat:read`, and `AiWorkspaceTabs` present on both pages.

- [ ] **Step 2: Run the contract test and verify RED**

Run: `cd frontend && node --test tests/aiChatState.test.mjs`

Expected: navigation assertions fail.

- [ ] **Step 3: Install maintained Markdown dependencies**

Run: `cd frontend && npm install marked@^16 dompurify@^3`

Expected: package manifest and lockfile contain both direct dependencies.

- [ ] **Step 4: Implement route-backed tabs**

`AiWorkspaceTabs.vue` renders two buttons with `role="tab"`, `aria-selected`, and route pushes to `DesignImageStudio` or `DesignAiChat`. It performs no animated indicator movement; hover uses color/box-shadow only and is gated by `(hover: hover) and (pointer: fine)`.

Change the visible menu entry title to `AI 工作台` and `anyPermission: ['design_image:read', 'ai_chat:read']`. Add the chat route with `hideInMenu: true`, `permission: 'ai_chat:read'`, and no `menu` object.

- [ ] **Step 5: Implement the page composable**

`useAiChat()` owns sessions, current session, messages, drafts, prompt, sidebar drawer, abort controller, and stream generation. It creates a session lazily, uploads through `AppUpload`, immediately appends optimistic user/assistant messages after `meta`, ignores events from stale generations, closes streams on unmount/session switch, and reloads the selected session after done/error.

- [ ] **Step 6: Implement focused UI components**

- `StarterCards`: four buttons that emit a prompt and never send.
- `ChatSidebar`: desktop rail plus Element drawer under 900px.
- `ChatThread`: user/assistant bubbles, `marked.parse` then `DOMPurify.sanitize`, copy raw Markdown, stopped/failed status, retry.
- `ChatComposer`: `AppUpload` accept list, five-draft guard, attachment chips, Enter send / Shift+Enter newline / IME guard, Send replaced by Stop while streaming.
- `AiChat`: liquid-glass aurora, tabs, sidebar, thread/welcome, composer, and owner-private label; one scroll container.

Keep every new Vue file under 500 lines. Use existing tokens and `.lg-*` classes; do not add raw hex colors. Movement is limited to infrequent drawer/popover transitions under 250ms, GPU properties only, with reduced-motion handling.

- [ ] **Step 7: Add tabs to the existing image studio**

Place `AiWorkspaceTabs` above the existing studio shell without changing `useImageStudio`, composer, polling, or generation behavior. Adjust height calculation once so the tabs do not introduce double page scroll.

- [ ] **Step 8: Run frontend tests and build**

Run: `cd frontend && node --test tests/aiChatState.test.mjs tests/designImageInteraction.test.mjs tests/designImageStudioRecovery.test.mjs`

Expected: all chat and existing image-studio tests pass.

Run: `cd frontend && npm run build`

Expected: Vite production build succeeds without unresolved imports or chunk errors.

- [ ] **Step 9: Commit Task 6**

```bash
git add frontend/package.json frontend/package-lock.json frontend/src/config/navigation.js frontend/src/views/design/image-studio/ImageStudio.vue frontend/src/views/design/ai-workspace frontend/src/views/design/ai-chat frontend/tests/aiChatState.test.mjs
git commit -m "feat(ai-chat): add solution chat workspace"
```

### Task 7: Documentation, complete validation, and adversarial review

**Files:**
- Modify: `docs/api-reference.md`
- Modify: `docs/database.md`
- Modify: `docs/module-notes.md`
- Modify: any scoped implementation file required by validated findings

- [ ] **Step 1: Document the operational contract**

Add all `/api/ai-chat` endpoints, the three tables and constraints, supported MIME/suffix list, 4 MiB/5-file/character limits, private storage setting, no OCR limitation, recent-20-message context policy, and setup instructions:

1. In “AI 接入管理”, configure a direct TeamRouter Provider with `api_type=anthropic` and no secret committed to git.
2. Create enabled Preset `customer_ai_chat` using model `claude-fable-5`.
3. Include a system prompt that treats attachment text as untrusted data and forbids following attachment instructions that request secrets or permission changes.

- [ ] **Step 2: Run backend focused tests**

Run: `cd backend && pytest tests/test_ai_chat_models.py tests/test_ai_chat_files.py tests/test_ai_chat_stream.py tests/test_ai_chat_service.py tests/test_ai_chat_router.py -q`

Expected: all AI chat tests pass.

- [ ] **Step 3: Run complete backend and frontend validation**

Run: `python scripts/check_conventions.py`

Expected: no red violations.

Run: `cd backend && pytest -q`

Expected: full backend suite passes.

Run: `cd frontend && node --test tests/*.test.mjs`

Expected: all Node tests pass.

Run: `cd frontend && npm run build`

Expected: production build succeeds.

Run: `git diff --check`

Expected: no whitespace errors.

- [ ] **Step 4: Run independent adversarial review**

Dispatch a fresh reviewer with this scope: owner isolation, attachment traversal/reparse points, request idempotency, concurrent draft binding, disconnect/stop log finalization, Provider protocol parsing, prompt injection boundaries, frontend/back-end event contract, all call sites of modified AI helpers, and navigation permissions. Apply every confirmed finding and add a regression test for each behavioral fix.

- [ ] **Step 5: Run motion review**

Review all new/changed transitions against `review-animations/STANDARDS.md`: delete motion on keyboard send and streaming text; reject `transition: all`, layout-property animation, built-in `ease-in`, ungated hover transforms, missing reduced motion, and UI durations over 300ms. Apply corrections and rerun the frontend build.

- [ ] **Step 6: Repeat complete validation after review fixes**

Repeat Step 3 without narrowing the command set. Completion requires the post-review results, not the earlier run.

- [ ] **Step 7: Commit documentation and review fixes**

```bash
git add docs/api-reference.md docs/database.md docs/module-notes.md backend frontend
git commit -m "docs(ai-chat): document and harden MVP"
```

- [ ] **Step 8: Run repository sweep**

Run: `python scripts/git_sweep.py`

Expected: the current branch/worktree is reported clean except intentional generated or ignored artifacts; do not modify other agents' branches or worktrees.
