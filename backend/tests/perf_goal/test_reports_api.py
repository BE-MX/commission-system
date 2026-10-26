"""报告生成（AI 降级）、投递状态机与降级通道、台账 API、补发。"""
from datetime import date

import httpx
import pytest

from app.perf_goal import jobs, report_ai
from app.perf_goal.delivery import deliver_report
from app.perf_goal.models import PerfReport, PerfReportDelivery
from tests.perf_goal.conftest import become


class FakeSender:
    """替代 WebhookSender：记录调用，可按需抛错。"""

    calls = []
    error = None

    def __init__(self, *args, **kwargs):
        pass

    async def send_markdown(self, title, text, at_mobiles=None, is_at_all=False):
        type(self).calls.append({"title": title, "at_mobiles": at_mobiles, "text": text})
        if type(self).error is not None:
            raise type(self).error
        return {"errcode": 0}


class _SessionCtx:
    def __init__(self, session):
        self._session = session

    def __enter__(self):
        return self._session

    def __exit__(self, *args):
        return False


@pytest.fixture
def pushed(perf, monkeypatch):
    FakeSender.calls = []
    FakeSender.error = None
    monkeypatch.setattr("app.perf_goal.delivery.WebhookSender", FakeSender)

    def _chat_raises(*args, **kwargs):
        raise ValueError("Preset 'perf_report_analyst' 不存在")

    monkeypatch.setattr("app.perf_goal.report_ai.chat", _chat_raises)
    monkeypatch.setattr("app.perf_goal.jobs.SessionLocal", lambda: _SessionCtx(perf.db))
    monkeypatch.setattr("app.perf_goal.jobs.beijing_today", lambda: date(2026, 10, 1))
    return perf


def test_run_push_generates_reports_and_degraded_deliveries(pushed):
    s = pushed
    stats_ = jobs.run_push(s.db, s.period, date(2026, 10, 1))
    # 3 个 listed 业务员 + 2 个队长 + 1 个管理层 = 6 份报告
    assert stats_["reports"] == 6 and stats_["generated"] == 6
    assert stats_["sent"] == 6 and stats_["failed"] == 0
    # 工作通知未启用 → 全部降级 webhook @
    assert stats_["degraded"] == 6
    reports = s.db.query(PerfReport).filter_by(slot=date(2026, 10, 1)).all()
    assert {r.scope for r in reports} == {"person", "leader", "company"}
    person = next(r for r in reports if r.scope == "person" and r.user_id == s.users[1].id)
    assert person.status == "generated" and person.content_md
    assert person.content_json["degraded"] is True
    assert "1500" in person.content_json["summary"] or "1,500" in person.content_json["summary"] \
        or "完成" in person.content_json["summary"]
    deliveries = s.db.query(PerfReportDelivery).filter_by(report_id=person.id).all()
    assert len(deliveries) == 1 and deliveries[0].channel == "webhook_at"
    assert deliveries[0].status == "sent" and deliveries[0].attempts == 1
    assert deliveries[0].sent_at is not None
    # 幂等：同 slot 重跑不新增报告，已 sent 不重发
    again = jobs.run_push(s.db, s.period, date(2026, 10, 1))
    assert again["reports"] == 6 and again["sent"] == 6
    assert s.db.query(PerfReport).filter_by(slot=date(2026, 10, 1)).count() == 6
    person_delivery = s.db.query(PerfReportDelivery).filter_by(report_id=person.id).one()
    assert person_delivery.attempts == 1


def test_ai_success_and_parse_paths(db, perf, monkeypatch):
    payload = {"scope_name": "测试", "period_label": "2026 年度", "as_of": "2026-06-30",
               "time_progress": 0.5, "metrics": {m: {"target": 100, "achieved": 50, "rate": 0.5,
               "delta_pp": 0.0, "unit": "USD"} for m in
               ("gmv", "new_sign", "repeat_customers", "repeat_amount")},
               "people": [], "warnings": []}
    monkeypatch.setattr(report_ai, "chat", lambda *a, **k: {
        "content": '```json\n{"summary": "总体向好", "highlights": ["GMV 达标"], '
                   '"risks": ["新签偏慢"], "suggestions": ["跟进报价"]}\n```'})
    content_md, content_json = report_ai.generate_content(db, payload, "perf_report_analyst")
    assert "degraded" not in content_json and content_json["summary"] == "总体向好"
    assert "总体向好" in content_md and "新签偏慢" in content_md
    for bad in ("not json at all", '{"summary": 1}', '{"summary": "x"}',
                '{"summary": "x", "highlights": [], "risks": ["r"], "suggestions": ["s"]}'):
        monkeypatch.setattr(report_ai, "chat", lambda *a, **k: {"content": bad})
        _md, degraded = report_ai.generate_content(db, payload, "perf_report_analyst")
        assert degraded["degraded"] is True


def test_delivery_failure_then_resend(pushed):
    s = pushed
    FakeSender.error = httpx.ConnectError("boom")
    stats_ = jobs.run_push(s.db, s.period, date(2026, 10, 1))
    assert stats_["failed"] == 6 and stats_["sent"] == 0
    report = s.db.query(PerfReport).filter_by(slot=date(2026, 10, 1), scope="person",
                                              user_id=s.users[1].id).one()
    row = s.db.query(PerfReportDelivery).filter_by(report_id=report.id).one()
    assert row.status == "failed" and row.attempts == 1
    assert row.last_error and "boom" not in row.last_error  # 不落异常原文
    FakeSender.error = None
    response = s.client.post(f"{s.url}/reports/{report.id}/resend")
    assert response.status_code == 200, response.text
    deliveries = response.json()["data"]["deliveries"]
    assert deliveries[0]["status"] == "sent" and deliveries[0]["attempts"] == 1
    # 中断的 sending 不自动重发，标记 uncertain
    row = s.db.query(PerfReportDelivery).filter_by(report_id=report.id).one()
    row.status = "sending"
    s.db.commit()
    recipient = {"ark_user_id": s.users[1].id, "name": "毕晓珍",
                 "dingtalk_id": "dt-u1", "phone": "13800000001"}
    updated = deliver_report(s.db, report, recipient, "毕晓珍")
    assert updated.status == "uncertain" and "中断" in updated.last_error


def test_reports_api_access_and_schedule(pushed):
    s = pushed
    jobs.run_push(s.db, s.period, date(2026, 10, 1))
    rows = s.client.get(f"{s.url}/reports").json()["data"]
    assert rows["total"] == 6 and len(rows["rows"]) == 6
    first = rows["rows"][0]
    assert {"id", "slot", "scope", "user_id", "user_name", "department_id",
            "team_name", "status", "created_at"} <= set(first)
    person = next(r for r in rows["rows"] if r["scope"] == "person" and r["user_id"] == s.users[2].id)
    detail = s.client.get(f"{s.url}/reports/{person['id']}").json()["data"]
    assert detail["content_md"] and detail["content_json"]["degraded"] is True
    assert detail["deliveries"][0]["channel"] == "webhook_at"
    become(s, 2)
    mine = s.client.get(f"{s.url}/reports").json()["data"]
    assert mine["total"] == 1
    assert s.client.get(f"{s.url}/reports/{person['id']}").status_code == 200
    leader_other = next(r for r in rows["rows"] if r["scope"] == "leader" and r["department_id"] == 101)
    assert s.client.get(f"{s.url}/reports/{leader_other['id']}").status_code == 403
    become(s, 3)  # 102 队长：本人 person + 本队 leader 报告
    mine = s.client.get(f"{s.url}/reports").json()["data"]
    assert mine["total"] == 2
    leader_own = next(r for r in rows["rows"] if r["scope"] == "leader" and r["department_id"] == 102)
    assert s.client.get(f"{s.url}/reports/{leader_own['id']}").status_code == 200
    assert s.client.post(f"{s.url}/reports/{leader_own['id']}/resend").status_code == 403
    become(s, 0)
    schedule = s.client.get(f"{s.url}/reports-schedule").json()["data"]
    assert schedule["cron"] == "0 9 1,10,20 * *" and schedule["next_run_at"]
    slot = next(item for item in schedule["recent_slots"] if item["slot"] == "2026-10-01")
    assert slot == {"slot": "2026-10-01", "total": 6, "sent": 6, "failed": 0, "degraded": 6}


def test_push_job_wrapper_and_failure_alert(pushed, monkeypatch):
    s = pushed
    jobs.perf_report_push_job()  # 全成功不抛错
    assert s.db.query(PerfReport).filter_by(slot=date(2026, 10, 1)).count() == 6
    # 新 slot 全部失败时 job 抛 RuntimeError 供 registry 告警监听
    FakeSender.error = httpx.ConnectError("boom")
    monkeypatch.setattr(jobs, "beijing_today", lambda: date(2026, 10, 10))
    with pytest.raises(RuntimeError, match="绩效报告存在未完成"):
        jobs.perf_report_push_job()


def test_config_roundtrip(perf):
    s = perf
    config = s.client.get(f"{s.url}/config").json()["data"]
    assert config["ai_preset"] == "perf_report_analyst"
    assert config["delivery_channel_mode"] == "worknotice_first"
    assert config["metrics_enabled"]["gmv"] is True
    assert config["worknotice_enabled"] is False and config["webhook_configured"] is False
    updated = s.client.put(f"{s.url}/config", json={
        "default_factor": "1.1", "ai_preset": "custom_preset",
        "metrics_enabled": {"repeat_amount": False},
        "order_decisions": [{"order_id": "1004", "order_no": "NO4", "company_id": "5003",
                             "owner_id": "90002", "account_date": "2026-03-05",
                             "role": "repeat", "reason": "人工确认"}]})
    assert updated.status_code == 200, updated.text
    data = updated.json()["data"]
    assert data["default_factor"] == "1.1" and data["ai_preset"] == "custom_preset"
    assert data["metrics_enabled"]["repeat_amount"] is False
    assert data["metrics_enabled"]["gmv"] is True
    assert len(data["order_decisions"]) == 1
    again = s.client.get(f"{s.url}/config").json()["data"]
    assert again["ai_preset"] == "custom_preset"
    # 配置的人工裁定即刻生效到统计口径
    overview = s.client.get(f"{s.url}/overview", params={
        "scope": "person", "scope_id": s.users[2].id}).json()["data"]
    assert overview["metrics"]["repeat_customers"]["achieved"] == 1
    assert overview["metrics"]["repeat_amount"]["achieved"] == 300.0
    become(s, 1)
    assert s.client.put(f"{s.url}/config", json={"default_factor": "1.2"}).status_code == 403
