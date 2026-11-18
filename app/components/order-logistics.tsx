"use client";

import { useCallback, useEffect, useId, useRef, useState, type FormEvent } from "react";
import type { Order } from "../lib/types";
import type { TrackingEvent } from "../lib/sf-tracking";

type Logistics = { orderNo: string; trackingNo: string; company: string; state: string; status: string; events: TrackingEvent[]; checkedAt: string | null; nextCheckAt: string | null; message: string; sandbox: boolean; configured: boolean; revision?: string; phoneLast4?: string };
const date = (value: string) => new Date(value).toLocaleString("zh-CN", { timeZone: "Asia/Shanghai", hour12: false });

export function OrderTrackingDetails({ orderId, mode }: { orderId: number; mode: "retail" | "wholesale" | "admin" }) {
  const [open, setOpen] = useState(false);
  return <details className="order-tracking" onToggle={(event) => setOpen(event.currentTarget.open)}><summary>查看顺丰物流轨迹</summary>{open && <TrackingPanel orderId={orderId} mode={mode} />}</details>;
}

export function TrackingPanel({ orderId, mode }: { orderId: number; mode: "retail" | "wholesale" | "admin" }) {
  const [data, setData] = useState<Logistics | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const load = useCallback(async () => {
    setLoading(true); setError("");
    try {
      const response = await fetch(`/api/orders/${orderId}/logistics?mode=${mode}`, { cache: "no-store" });
      const payload = await response.json() as { error?: string; logistics: Logistics };
      if (!response.ok) throw new Error(payload.error || "暂时无法查询物流");
      setData(payload.logistics);
    } catch (failure) { setError(failure instanceof Error ? failure.message : "连接失败，请稍后重试"); }
    finally { setLoading(false); }
  }, [mode, orderId]);
  useEffect(() => {
    // Cancel StrictMode's discarded mount before making the initial request.
    const task = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(task);
  }, [load]);
  const [copyNotice, setCopyNotice] = useState("");
  const copy = async () => {
    try { await navigator.clipboard.writeText(data!.trackingNo); setCopyNotice("单号已复制"); }
    catch { setCopyNotice("请长按上方单号复制"); }
  };
  return <section className="tracking-panel" aria-label="顺丰物流轨迹" aria-busy={loading}>
    <div className="tracking-heading"><strong>顺丰物流轨迹</strong><button type="button" disabled={loading} onClick={() => void load()}>{loading ? "查询中…" : "刷新轨迹"}</button></div>
    {error && <p className="tracking-warning" role="alert">{error}</p>}
    {data && <>
      {data.sandbox && data.events.length > 0 && <p className="tracking-warning">顺丰沙箱测试轨迹，仅供接口联调，不代表实际快件。</p>}
      <div className="tracking-waybill"><span>{data.company || "顺丰速运"}</span><strong>{data.trackingNo || "尚未发货"}</strong>{data.trackingNo && <button type="button" onClick={copy}>复制单号</button>}</div>
      {copyNotice && <p role="status">{copyNotice}</p>}
      <p className="tracking-state">{data.status}</p>
      {data.message && <p className="tracking-hint" role="status">{data.message}</p>}
      {data.checkedAt && <p className="tracking-hint">查询时间：{date(data.checkedAt)}（北京时间）</p>}
      {data.nextCheckAt && !["delivered", "returned"].includes(data.state) && <p className="tracking-hint">下次可向顺丰查询：{date(data.nextCheckAt)}。此前刷新会显示已保存的轨迹。</p>}
      {data.events.length > 0 ? <ol className="tracking-timeline">{data.events.map((event, i) => <li key={`${event.time}-${i}`}><time dateTime={event.time}>{date(event.time)}</time><strong>{event.status}{event.location ? ` · ${event.location}` : ""}</strong><p>{event.description}</p></li>)}</ol> : <p className="tracking-empty">{data.trackingNo ? "暂时没有可展示的快递轨迹，录入单号不等于快递已揽收。" : "仓库发货后，这里会显示每一步配送进度。"}</p>}
      {data.events.length > 0 && <p className="tracking-hint">轨迹来自顺丰。已签收、已退回的运单保留记录；运输中的运单按查询间隔更新。</p>}
    </>}
  </section>;
}

export function ShipmentDialog({ order, onClose, onSaved }: { order: Order; onClose: () => void; onSaved: () => void | Promise<void> }) {
  const titleId = useId();
  const panel = useRef<HTMLDialogElement>(null);
  const [initial, setInitial] = useState<Logistics | null>(null);
  const [trackingNo, setTrackingNo] = useState(order.trackingNo);
  const [phoneLast4, setPhoneLast4] = useState("");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    const dialog = panel.current;
    dialog?.showModal();
    const abort = new AbortController();
    fetch(`/api/orders/${order.id}/logistics?mode=admin`, { cache: "no-store", signal: abort.signal })
      .then(async (response) => { const data = await response.json() as { error?: string; logistics: Logistics }; if (!response.ok) throw new Error(data.error || "读取物流失败"); return data.logistics; })
      .then((data) => { setInitial(data); setPhoneLast4(data.phoneLast4 ?? ""); setTrackingNo(data.trackingNo); })
      .catch((failure) => { if (!abort.signal.aborted) setError(failure.message || "连接失败，请重新打开"); });
    return () => { abort.abort(); dialog?.close(); previous?.focus(); };
  }, [order.id]);
  const save = async (event: FormEvent) => {
    event.preventDefault();
    if (!initial || saving) return;
    setSaving(true); setError("");
    try {
      const response = await fetch(`/api/orders/${order.id}`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ trackingNo, phoneLast4, revision: initial.revision }) });
      const data = await response.json() as { error?: string };
      if (!response.ok) throw new Error(data.error || "保存失败，请重试");
      await onSaved(); onClose();
    } catch (failure) { setError(failure instanceof Error ? failure.message : "保存失败，请重试"); }
    finally { setSaving(false); }
  };
  return <dialog ref={panel} aria-labelledby={titleId} className="shipment-dialog" onCancel={(event) => { event.preventDefault(); if (!saving) onClose(); }}>
      <div className="tracking-heading"><h2 id={titleId}>顺丰发货与物流</h2><button type="button" disabled={saving} onClick={onClose} aria-label="关闭物流窗口">关闭</button></div>
      <p>订单：{order.orderNo}</p>
      <form onSubmit={save}>
        <label>顺丰运单号<input autoComplete="off" value={trackingNo} onChange={(event) => setTrackingNo(event.target.value)} placeholder="请输入真实顺丰单号" maxLength={24} required disabled={saving} /></label>
        <label>收件人或寄件人手机号后四位（选填）<input inputMode="numeric" autoComplete="off" value={phoneLast4} onChange={(event) => setPhoneLast4(event.target.value.replace(/\D/g, "").slice(0, 4))} maxLength={4} pattern="[0-9]{4}" disabled={saving} /></label>
        <p className="tracking-hint">非本公司月结账号寄付的运单，可能需要手机号后四位才能查询。此信息不对客户展示。</p>
        <p className="tracking-hint">修改单号或校验手机号后，会重新查询并切换轨迹。这里只维护物流，不修改付款状态。</p>
        {error && <p className="tracking-warning" role="alert">{error}</p>}
        <button className="shipment-save" type="submit" disabled={!initial || saving}>{saving ? "正在保存…" : "保存顺丰发货信息"}</button>
      </form>
      <OrderTrackingDetails orderId={order.id} mode="admin" />
  </dialog>;
}
