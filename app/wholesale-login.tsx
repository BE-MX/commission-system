"use client";

import { FormEvent, useState } from "react";

export default function WholesaleLogin() {
  const [phone, setPhone] = useState("");
  const [code, setCode] = useState("");
  const [sent, setSent] = useState(false);
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(false);

  const sendCode = () => {
    if (!/^1\d{10}$/.test(phone)) return setMessage("请先输入正确的11位手机号码");
    setSent(true); setMessage("演示验证码已发送：6688");
  };

  const verify = async (event: FormEvent) => {
    event.preventDefault(); setLoading(true); setMessage("");
    const response = await fetch("/api/wholesale-auth", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ phone, code }) });
    const data = await response.json();
    if (response.ok) window.location.href = "/wholesale";
    else setMessage(data.error ?? "验证失败，请重试");
    setLoading(false);
  };

  return <main className="wholesale-login-page">
    <section className="login-brand-panel"><img src="/leshine-brand.jpg" alt="LESHINE 莱莎健康假发" /><div><p>LESHINE WHOLESALE</p><h1>莱莎批发商城</h1><span>手机号验证后，按账户等级显示批发价格与商品权限</span></div></section>
    <section className="phone-login-panel"><a href="/">← 返回身份入口</a><div className="phone-login-card"><span className="login-shield">验</span><p>批发商账户验证</p><h2>手机号验证后进入</h2><small>仅已在后台审核并建立档案的批发商手机号可以进入。</small><form onSubmit={verify}><label>手机号码<div><span>+86</span><input value={phone} onChange={(e) => setPhone(e.target.value.replace(/\D/g, "").slice(0, 11))} inputMode="numeric" placeholder="请输入批发商手机号码" /></div></label><label>短信验证码<div className="code-row"><input value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, "").slice(0, 6))} inputMode="numeric" placeholder="请输入验证码" /><button type="button" onClick={sendCode}>{sent ? "重新发送" : "获取验证码"}</button></div></label>{message && <div className="login-message">{message}</div>}<button className="verify-button" disabled={loading}>{loading ? "正在验证…" : "验证并进入批发商城"}</button></form><div className="demo-phones"><strong>演示账户</strong><button onClick={() => setPhone("18600167712")}>批发A：18600167712</button><button onClick={() => setPhone("13800132031")}>批发B：13800132031</button><span>当前演示验证码统一为 6688；正式版将接入短信服务商。</span></div></div></section>
  </main>;
}
