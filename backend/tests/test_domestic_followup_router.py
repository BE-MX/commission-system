import base64
import io
import json
from datetime import date

import httpx
import pytest
from PIL import Image, ImageDraw
from sqlalchemy.orm import sessionmaker

from app.ai import call_service
from app.ai.models import AiPreset, AiProvider
from app.bootstrap import seed_ai
from app.domestic import file_service

from app.domestic_followup import ai_parse_service, attachment_service, followup_service, jobs
from app.domestic_followup.models import DomesticFollowup, DomesticFollowupAttachment, DomesticFollowupItem
from tests.domestic_followup_helpers import followup_client, grant, make_customer, make_user, seed_dicts

TODAY = date(2026, 10, 30)


@pytest.fixture(autouse=True)
def _patch(monkeypatch):
    monkeypatch.setattr(followup_service, "beijing_today", lambda: TODAY)
    monkeypatch.setattr(followup_service, "_enqueue_urgent", lambda *a, **k: None)


def _record_jobs(monkeypatch):
    calls = []
    monkeypatch.setattr(jobs, "submit", lambda fn, *args: calls.append((fn, args)))
    return calls


def test_direct_save_submits_ocr_only_when_screenshots_pending(db, monkeypatch):
    seed_dicts(db)
    user = make_user(db, "fu_rt_ocr")
    customer = make_customer(db, user, "路由店OCR")
    att = DomesticFollowupAttachment(uploader_user_id=user.id, seq=1, file_path="fu/o.png", mime_type="image/png")
    db.add(att)
    db.flush()
    calls = _record_jobs(monkeypatch)
    with followup_client(db, user) as client:
        plain = client.post("/api/domestic-followup/followups", json={
            "result_code": "有效沟通",
            "request_id": "rt-ocr-plain", "customer_id": customer.id, "raw_text": "无截图"})
        assert plain.status_code == 200 and calls == []
        shot = client.post("/api/domestic-followup/followups", json={
            "result_code": "有效沟通",
            "request_id": "rt-ocr-shot", "customer_id": customer.id, "raw_text": "带截图",
            "attachment_ids": [att.id]})
        assert shot.status_code == 200
    assert calls == [(attachment_service.run_ocr, ([att.id],))]


def test_requires_permission(db):
    user = make_user(db, "fu_rt_a")
    with followup_client(db, user, permissions=()) as client:
        assert client.get("/api/domestic-followup/tasks").status_code == 403


def test_direct_save_and_list(db):
    seed_dicts(db)
    user = make_user(db, "fu_rt_b")
    customer = make_customer(db, user, "路由店B")
    with followup_client(db, user) as client:
        resp = client.post("/api/domestic-followup/followups", json={
            "result_code": "有效沟通",
            "request_id": "rt-direct-b", "customer_id": customer.id, "raw_text": "回访正常",
            "next_date": "2026-11-02", "next_plan": "问补货"})
        assert resp.status_code == 200 and resp.json()["code"] == 200
        listed = client.get("/api/domestic-followup/followups", params={"customer_id": customer.id}).json()["data"]
        assert listed["total"] == 1
        tasks = client.get("/api/domestic-followup/tasks", params={"due": "all"}).json()["data"]
        assert tasks["items"][0]["task_type"] == "plan"


def test_draft_starts_background_parse_and_conflict_maps_409(db, monkeypatch):
    seed_dicts(db)
    user = make_user(db, "fu_rt_c")
    customer = make_customer(db, user, "路由店C")
    calls = _record_jobs(monkeypatch)
    with followup_client(db, user) as client:
        draft = client.post("/api/domestic-followup/drafts",
                            json={"request_id": "rt-draft-c", "raw_text": "聊天"}).json()["data"]
        assert [(fn, args[0]) for fn, args in calls] == [(ai_parse_service.run_parse, draft["id"])]
        assert draft["ai_status"] == "running"
        replay = client.post("/api/domestic-followup/drafts", json={"request_id": "rt-draft-c", "raw_text": "聊天"})
        assert replay.json()["data"]["id"] == draft["id"] and len(calls) == 1  # 重放不重复调模型
        bad = client.post(f"/api/domestic-followup/drafts/{draft['id']}/confirm",
                          json={"result_code": "有效沟通", "version": 9, "customer_id": customer.id})
        assert bad.status_code == 409
        good = client.post(f"/api/domestic-followup/drafts/{draft['id']}/confirm",
                           json={"result_code": "有效沟通", "version": draft["version"], "customer_id": customer.id})
        assert good.status_code == 200 and good.json()["data"]["status"] == "confirmed"


@pytest.mark.parametrize(("shot_count", "failed_ocr", "parse_failure"), [
    (6, None, None), (6, 5, None), (6, None, "truncated"),
    (1, None, None), (1, None, "overloaded"), (1, None, "dense_screenshot"),
], ids=["all_readable", "last_ocr_failed", "truncated_parse_then_recovered", "long_text_single_image",
        "long_text_recovers_from_overload", "dense_single_image_recovers_from_truncation"])
def test_images_produce_a_reviewable_draft(db, monkeypatch, tmp_path, shot_count, failed_ocr, parse_failure):
    seed_dicts(db)
    user = make_user(db, "fu_rt_screenshots")
    customer = make_customer(db, user, "测试客户")
    provider = AiProvider(name="Test provider", api_base="https://example.invalid/v1")
    db.add(provider)
    db.flush()
    for name, prompt in [
        ("domestic_followup_parse", seed_ai._DOMESTIC_FOLLOWUP_PARSE_SYSTEM_PROMPT),
        ("domestic_followup_ocr", seed_ai._DOMESTIC_FOLLOWUP_OCR_SYSTEM_PROMPT),
    ]:
        db.add(AiPreset(preset_name=name, provider_id=provider.id, model=name,
                        parameters={"max_tokens": 4096}, system_prompt=prompt))
    db.commit()
    monkeypatch.setattr(file_service, "storage_root", lambda: tmp_path)
    monkeypatch.setattr(file_service.cloud_files, "put_bytes", lambda *args: False)
    monkeypatch.setattr(file_service.cloud_files, "read_path", lambda _ns, rel, root: root / rel)
    jobs_to_run = _record_jobs(monkeypatch)

    raw_text = ""
    if shot_count == 1 and parse_failure != "dense_screenshot":
        raw_text = ("客户在比较多个补货方案，月底前会反馈。\n" * 450).strip()
    screenshots = []
    transcripts = [
        f"客户：第 {index} 张聊天记录\n" + "客户：关于样品发片颜色和长度，我们内部还要再核对一次。\n" * 40
        for index in range(1, shot_count + 1)
    ]
    resolved_quote = "最短规格是20厘米，报价已经按20厘米解释清楚"
    transcripts[-1] += f"我：{resolved_quote}"
    requests = []
    deadlines = []
    waits = []
    monkeypatch.setattr(attachment_service, "sleep", waits.append)

    def model_response(_url, *, body, timeout_sec, enforce_total_timeout=False, **_kwargs):
        pictures = [
            base64.b64decode(part["image_url"]["url"].split(",", 1)[1])
            for message in body["messages"] if isinstance(message["content"], list)
            for part in message["content"] if part["type"] == "image_url"
        ]
        requests.append((body["model"], pictures))
        deadlines.append((timeout_sec, enforce_total_timeout))
        assert body["max_tokens"] == 4096
        assert "thinking" not in body and "response_format" not in body
        if body["model"] == "domestic_followup_ocr":
            [picture] = pictures
            index = screenshots.index(picture)
            if parse_failure == "overloaded" and len(requests) == 3:
                request = httpx.Request("POST", _url)
                httpx.Response(503, request=request).raise_for_status()
            if index == failed_ocr:
                return {"choices": [{"message": {"content": '{"text": "截断'}, "finish_reason": "length"}]}
            output = json.dumps({"text": transcripts[index], "unreadable": []})
        else:
            instructions = " ".join(msg["content"] for msg in body["messages"] if msg["role"] == "system")
            assert body["messages"][-1]["content"][0]["text"].endswith(raw_text)
            if parse_failure == "overloaded" and len(requests) == 1:
                request = httpx.Request("POST", _url)
                httpx.Response(503, request=request, headers={"Retry-After": "2"}).raise_for_status()
            if parse_failure == "truncated" and len(requests) == 1:
                return {"choices": [{"message": {"content": '{"summary": "未结束'},
                                     "finish_reason": "length"}], "usage": {"completion_tokens": 4096}}
            if "ocr 必须是空数组" not in instructions:
                return {"choices": [{"message": {"content": '{"ocr": [{"attachment_index": 0, "text": "截断'},
                                     "finish_reason": "length"}], "usage": {"completion_tokens": 4096}}
            output = json.dumps({
                "summary": "已解释规格报价",
                "customer_hint": {"chat_title": "测试客户", "matched_customer_id": customer.id, "confidence": 0.96},
                "suggestions": [{
                    "text": "客户认为报价偏高",
                    "handled_source": {"kind": "attachment", "attachment_index": shot_count - 1, "excerpt": resolved_quote},
                }],
                # Even if the model ignores the prompt and repeats a quote in ocr, only the independent OCR is evidence.
                "ocr": [] if parse_failure == "dense_screenshot" else [
                    {"attachment_index": shot_count - 1, "text": resolved_quote},
                ],
            }, ensure_ascii=False)
        return {"choices": [{"message": {"content": output}, "finish_reason": "stop"}]}

    monkeypatch.setattr(call_service, "post_json", model_response)
    with followup_client(db, user) as client:
        attachment_ids = []
        for index in range(1, shot_count + 1):
            image = Image.new("RGB", (360, 210), "white")
            draw = ImageDraw.Draw(image)
            draw.text((10, 10), f"Test customer - chat page {index}", fill="black")
            draw.text((10, 55), "Customer: Can you explain the quote?", fill="black")
            draw.text((10, 85), "Sales: The shortest option is 20 cm.", fill="black")
            encoded = io.BytesIO()
            image.save(encoded, format="PNG")
            screenshots.append(encoded.getvalue())
            response = client.post("/api/domestic-followup/attachments",
                                   files={"file": (f"chat-{index}.png", screenshots[-1], "image/png")})
            assert response.status_code == 200
            attachment_ids.append(response.json()["data"]["id"])
        response = client.post("/api/domestic-followup/drafts", json={
            "request_id": "rt-screenshots", "attachment_ids": attachment_ids, "raw_text": raw_text or None,
        })
        assert response.status_code == 200, response.text
        draft = response.json()["data"]
        assert draft["ai_status"] == "running"
        [(job, args)] = jobs_to_run
        job(*args, session_factory=sessionmaker(bind=db.get_bind()))
        draft = client.get(f"/api/domestic-followup/drafts/{draft['id']}").json()["data"]

    assert draft["ai_status"] == "done", draft["ai_error"]
    assert (draft["raw_text"] or "") == raw_text
    assert draft["ai_result"]["summary"] == "已解释规格报价"
    assert draft["ai_result"]["customer_id"] == customer.id
    assert draft["ai_result"]["items"][0]["record_only"] is (failed_ocr is None)
    assert [row["ocr_text"] for row in draft["attachments"]] == [
        text if index != failed_ocr else None for index, text in enumerate(transcripts)
    ]
    assert [row["ocr_status"] for row in draft["attachments"]] == [
        "done" if index != failed_ocr else "failed" for index in range(shot_count)
    ]
    assert bool(draft["ai_result"]["unreadable"]) is (failed_ocr is not None)
    parse_count = 2 if parse_failure else 1
    assert requests[:parse_count] == [("domestic_followup_parse", screenshots)] * parse_count
    ocr_requests = [("domestic_followup_ocr", [shot]) for shot in screenshots]
    if failed_ocr is not None:
        ocr_requests.insert(failed_ocr, ocr_requests[failed_ocr])
    if parse_failure == "overloaded":
        ocr_requests = ocr_requests * 2
    assert requests[parse_count:] == ocr_requests
    assert deadlines[0] == (120, True)
    assert all(0 < seconds <= 120 and total for seconds, total in deadlines[:parse_count])
    assert all(0 < seconds <= 45 and total for seconds, total in deadlines[parse_count:])
    assert waits == ([2, 1] if parse_failure == "overloaded" else [])


@pytest.mark.parametrize(("thinking", "long_text"), [
    (None, False), ({"type": "enabled"}, False), (None, True),
], ids=["default", "explicit", "near_input_limit"])
def test_text_only_draft_recovers_from_truncated_json(db, monkeypatch, thinking, long_text):
    seed_dicts(db)
    user = make_user(db, "fu_rt_text")
    customer = make_customer(db, user, "测试客户")
    provider = AiProvider(name="DeepSeek test", api_base="https://api.deepseek.com", timeout_sec=120)
    db.add(provider)
    db.flush()
    parameters = {"max_tokens": 4096}
    if thinking is not None:
        parameters["request_parameters"] = {"thinking": thinking}
    db.add(AiPreset(preset_name="domestic_followup_parse", provider_id=provider.id, model="deepseek-flash",
                    parameters=parameters, system_prompt=seed_ai._DOMESTIC_FOLLOWUP_PARSE_SYSTEM_PROMPT))
    db.commit()
    jobs_to_run = _record_jobs(monkeypatch)
    raw_text = "客户确认试用效果正常，下周三反馈是否补货。"
    if long_text:
        raw_text = ("已讨论补货规格。\n" * 2400)[:19_900] + raw_text
    requests = []
    clock_ticks = iter((100.0, 122.0))
    monkeypatch.setattr(attachment_service, "monotonic", lambda: next(clock_ticks))

    def model_response(_url, *, body, timeout_sec, **_kwargs):
        requests.append((body, timeout_sec))
        instructions = " ".join(msg["content"] for msg in body["messages"] if msg["role"] == "system")
        assert "本次只有业务员原文" in instructions
        assert ("请通读完整原文" in instructions) is long_text
        assert body["messages"][-1]["content"][0]["text"].endswith(raw_text)
        assert all(part["type"] == "text" for part in body["messages"][-1]["content"])
        if len(requests) == 1:
            return {"choices": [{"message": {"content": '{"summary": "未结束'}, "finish_reason": "length"}],
                    "usage": {"completion_tokens": 4096}}
        output = {"summary": "试用正常，待确认是否补货"}
        return {"choices": [{"message": {"content": json.dumps(output)}, "finish_reason": "stop"}]}

    monkeypatch.setattr(call_service, "post_json", model_response)
    with followup_client(db, user) as client:
        response = client.post("/api/domestic-followup/drafts", json={
            "request_id": "rt-text-only", "customer_id": customer.id, "raw_text": raw_text,
        })
        assert response.status_code == 200
        draft = response.json()["data"]
        [(job, args)] = jobs_to_run
        job(*args, session_factory=sessionmaker(bind=db.get_bind()))
        draft = client.get(f"/api/domestic-followup/drafts/{draft['id']}").json()["data"]

    assert draft["ai_status"] == "done", draft["ai_error"]
    assert draft["ai_result"]["summary"] == "试用正常，待确认是否补货"
    assert draft["raw_text"] == raw_text and draft["attachments"] == []
    assert len(requests) == 2
    for body, _ in requests:
        assert body["thinking"] == (thinking or {"type": "disabled"})
        assert body["response_format"] == {"type": "json_object"}
    assert [timeout for _, timeout in requests] == [120, 98]


def test_writing_other_owners_customer_is_403(db):
    seed_dicts(db)
    owner = make_user(db, "fu_rt_d1")
    other = make_user(db, "fu_rt_d2")
    customer = make_customer(db, owner, "路由店D")
    with followup_client(db, other) as client:
        resp = client.post("/api/domestic-followup/followups",
                           json={"result_code": "有效沟通", "request_id": "rt-direct-d", "customer_id": customer.id, "raw_text": "x"})
        assert resp.status_code == 403 and "fu_rt_d1" in resp.json()["detail"]


def test_config_write_requires_admin(db):
    user = make_user(db, "fu_rt_e")
    with followup_client(db, user) as client:
        assert client.put("/api/domestic-followup/config", json={"receipt_delay_days": 4}).status_code == 403
    with followup_client(db, user, permissions=("domestic_followup:read", "domestic_followup:admin")) as client:
        resp = client.put("/api/domestic-followup/config", json={"receipt_delay_days": 4})
        assert resp.status_code == 200 and resp.json()["data"]["receipt_delay_days"] == 4


def test_cannot_read_other_users_draft(db):
    seed_dicts(db)
    author = make_user(db, "fu_rt_f1")
    other = make_user(db, "fu_rt_f2")
    draft = DomesticFollowup(author_user_id=author.id, followup_date=TODAY, request_id="rt-draft-f",
                             status="draft", ai_status="none", version=1)
    db.add(draft)
    db.flush()
    with followup_client(db, other) as client:
        assert client.get(f"/api/domestic-followup/drafts/{draft.id}").status_code == 404


def test_cannot_read_other_users_screenshot(db):
    author = make_user(db, "fu_rt_g1")
    other = make_user(db, "fu_rt_g2")
    att = DomesticFollowupAttachment(uploader_user_id=author.id, seq=1, file_path="fu/g.png", mime_type="image/png")
    db.add(att)
    db.flush()
    with followup_client(db, other) as client:
        assert client.get(f"/api/domestic-followup/attachments/{att.id}/file").status_code == 403


def test_cannot_resolve_item_outside_scope(db):
    owner = make_user(db, "fu_rt_h1")
    other = make_user(db, "fu_rt_h2")
    customer = make_customer(db, owner, "路由店H")
    followup = DomesticFollowup(author_user_id=owner.id, customer_id=customer.id, followup_date=TODAY,
                                request_id="rt-item-h", status="confirmed", version=2)
    db.add(followup)
    db.flush()
    item = DomesticFollowupItem(followup_id=followup.id, customer_id=customer.id, seq=1, kind="issue",
                                text="掉色", category="质量", severity="一般", status="open",
                                handler_user_id=owner.id)
    db.add(item)
    db.flush()
    with followup_client(db, other) as client:
        resp = client.post(f"/api/domestic-followup/items/{item.id}/resolve",
                           json={"status": "resolved", "resolution": "x"})
        assert resp.status_code == 403
    db.refresh(item)
    assert item.status == "open"


def test_user_search_for_transfer(db):
    user = make_user(db, "fu_rt_f")
    grant(db, make_user(db, "fu_rt_qc"), "domestic_followup:write")
    make_user(db, "fu_rt_qc_reader")  # 没有跟进权限：转过去也处理不了，不该出现在候选里
    with followup_client(db, user) as client:
        rows = client.get("/api/domestic-followup/users", params={"q": "qc"}).json()["data"]
        assert [r["real_name"] for r in rows] == ["fu_rt_qc"]
