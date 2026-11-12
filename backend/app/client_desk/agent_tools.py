"""Read-only tools for the controlled private-sea agent loop.

The program owns the loop: each model turn may request one tool or finish.
Tools only project material already authorized in this run's source bundle
(plus product lines of an order in that bundle). Alibaba inquiries are
available only when the salesperson selected them for this manual run.
"""

import json

from .pack import canonical

TOOL_LABELS = {
    "order_items": "查看订单产品明细",
    "older_messages": "读取更早的 WhatsApp 消息",
    "research_detail": "查看已审核背调",
    "followup_history": "查看跟进记录",
    "selected_inquiries": "读取已勾选询盘",
}
FINAL_LABEL = "生成画像、标签与建议"
RESULT_LIMIT = 4000
CONTEXT_LIMIT = 36000


def max_steps(rules, run_seq):
    agent = (rules or {}).get("agent", {})
    if run_seq > 0:
        return max(0, min(int(agent.get("manual_tool_steps", 4)), 6))
    return max(0, min(int(agent.get("routine_tool_steps", 2)), 6))


def parse_action(raw):
    """Return (tool, args) for a tool request, or None for a final answer."""
    if not isinstance(raw, str):
        return None
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(data, dict) or "tool" not in data or "brief_md" in data:
        return None
    args = data.get("args")
    return str(data.get("tool"))[:40], args if isinstance(args, dict) else {}


def _escape(text):
    return (
        text.replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("`", "\\u0060")
    )


def _bounded(entries, render):
    """Keep whole entries until the serialized result reaches RESULT_LIMIT."""
    kept = []
    for entry in entries:
        if len(canonical(render(kept + [entry]))) > RESULT_LIMIT:
            break
        kept.append(entry)
    return kept


def _message_ref(message):
    return {
        "source": "whatsapp",
        "event_key": message["event_key"],
        "text": message.get("text") or "",
        "at": str(message.get("at") or ""),
        "direction": message.get("direction"),
    }


def run_tool(db, source, refs, name, args):
    """Execute one tool. Returns (payload, new_refs, trace_status)."""
    if name == "order_items":
        order_id = str(args.get("order_id") or "")
        order = next((o for o in source.get("orders") or [] if o["id"] == order_id), None)
        if order is None:
            return {"error": "订单不在本客户可见范围内"}, {}, "rejected"
        from .timeline import order_products

        products = [
            {"name": p.get("name"), "model": p.get("model"), "quantity": p.get("quantity")}
            for p in order_products(db, source["company_id"], order_id)
        ]
        kept = _bounded(products, lambda rows: {"order": order_id, "products": rows})
        key = "O-" + order_id
        ref = {"source": "order", "event_key": order["event_key"], "datum": order | {"products": kept}}
        return {"key": key, "order": order, "products": kept, "truncated": len(kept) < len(products)}, {key: ref}, "ok"

    if name == "older_messages":
        hidden = [
            m
            for m in source.get("messages") or []
            if m["key"].startswith("M-") and m["key"] not in refs
        ]
        hidden.sort(key=lambda m: (str(m.get("at") or ""), m["key"]), reverse=True)
        limit = max(1, min(int(args.get("limit") or 15), 20)) if str(args.get("limit") or "15").isdigit() else 15
        page = _bounded(hidden[:limit], lambda rows: {"messages": [_message_ref(m) | {"key": m["key"]} for m in rows]})
        new_refs = {m["key"]: _message_ref(m) for m in page}
        return {
            "messages": [new_refs[m["key"]] | {"key": m["key"]} for m in page],
            "remaining": len(hidden) - len(page),
        }, new_refs, "ok"

    if name == "research_detail":
        report = source.get("research_report") or {}
        if report.get("status") != "ready":
            return {"result": "无背调结果"}, {}, "empty"
        research = next(
            (r for r in source.get("research") or [] if r["event_key"] == report.get("event_key")),
            None,
        )
        key = "S-" + str(research["id"]) if research else None
        sections = _bounded(
            report["sections"], lambda rows: {"sections": rows}
        )
        new_refs = (
            {key: {"source": "research", "event_key": report["event_key"], "datum": {"sections": sections}}}
            if key
            else {}
        )
        return {"key": key, "verdict": report["verdict"], "sections": sections}, new_refs, "ok"

    if name == "followup_history":
        rows = sorted(
            (
                {"key": k, "text": v.get("text"), "at": str(v.get("at") or "")}
                for k, v in (source.get("refs") or {}).items()
                if k.startswith("F-")
            ),
            key=lambda r: r["at"],
            reverse=True,
        )
        kept = _bounded(rows, lambda items: {"followups": items})
        new_refs = {r["key"]: source["refs"][r["key"]] for r in kept}
        return {"followups": kept}, new_refs, "ok" if kept else "empty"

    if name == "selected_inquiries":
        if source.get("analysis_policy") != "manual_only_v1":
            return {"result": "业务员本次未勾选询盘，不能读取"}, {}, "empty"
        rows = [
            {"key": k, "text": v.get("text"), "at": str(v.get("at") or "")}
            for k, v in (source.get("refs") or {}).items()
            if k.startswith("AF-")
        ]
        rows.sort(key=lambda r: (r["at"], r["key"]))
        hidden = [r for r in rows if r["key"] not in refs]
        kept = _bounded(hidden, lambda items: {"inquiries": items})
        new_refs = {r["key"]: source["refs"][r["key"]] for r in kept}
        return {"inquiries": kept, "remaining": len(hidden) - len(kept)}, new_refs, "ok" if kept else "empty"

    return {"error": "未知工具"}, {}, "rejected"


def tool_message(name, payload, steps_left):
    note = (
        "工具调用次数已用完，下一次必须输出最终结果 JSON。"
        if steps_left <= 0
        else f"还可调用 {steps_left} 次工具；资料足够时直接输出最终结果。"
    )
    return {
        "role": "user",
        "content": note + "\n<tool_result>" + _escape(canonical({"tool": name, "result": payload})) + "</tool_result>",
    }


def context_size(messages):
    return sum(len(m["content"]) for m in messages)


def trace_step(name, status, at, args=None):
    item = {"tool": name, "label": TOOL_LABELS.get(name, FINAL_LABEL if name == "final" else "未知工具"), "status": status, "at": at.isoformat(timespec="seconds")}
    if name == "order_items" and args and args.get("order_id"):
        item["target"] = str(args["order_id"])[:40]
    return item


def run_view(row):
    if row is None:
        return None
    return {
        "id": str(row.id),
        "run_seq": row.run_seq,
        "status": row.status,
        "error_code": row.error_code,
        "steps": list(row.agent_trace or []),
        "started_at": row.created_at,
        "updated_at": row.updated_at,
    }
