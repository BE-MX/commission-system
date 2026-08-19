"use client";

import { FormEvent, useState } from "react";

export default function RetailLogin() {
  const [phone, setPhone] = useState(""); const [code, setCode] = useState("");
  const [sent, setSent] = useState(false); const [message, setMessage] = useState(""); const [loading, setLoading] = useState(false);
  const sendCode = () => { if (!/^1\d{10}$/.test(phone)) return setMessage("请先输入正确的11位手机号码"); setSent(true); setMessage("演示验证码已发送：6688"); };
  const verify = async (event: FormEvent) => { event.preventDefault(); setLoading(true); setMessage(""); const response = await fetch("/api/retail-auth", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ phone, code }) }); const data = await response.json(); if (response.ok) window.location.href = "/retail"; else setMessage(data.error ?? "验证失败"); setLoading(false); };
  return <main className="wholesale-login-page retail-login-page"><section className="login-brand-panel"><img src="/leshine-brand.jpg" alt="LESHINE 莱莎健康假发" /><div><p>LESHINE RETAIL</p><h1>莱莎零售商城</h1><span>手机号验证后进入零售商城，查看零售款式与零售价格</span></div></section><section className="phone-login-panel"><a href="/">← 返回身份入口</a><div className="phone-login-card"><span className="login-shield">零</span><p>零售客户登录</p><h2>手机号验证登录</h2><small>输入本人手机号并完成短信验证码验证，即可进入零售商城。</small><form onSubmit={verify}><label>手机号码<div><span>+86</span><input value={phone} onChange={(e) => setPhone(e.target.value.replace(/\D/g, "").slice(0, 11))} inputMode="numeric" placeholder="请输入手机号码" /></div></label><label>短信验证码<div className="code-row"><input value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, "").slice(0, 6))} inputMode="numeric" placeholder="请输入验证码" /><button type="button" onClick={sendCode}>{sent ? "重新发送" : "获取验证码"}</button></div></label>{message && <div className="login-message">{message}</div>}<button className="verify-button" disabled={loading}>{loading ? "正在验证…" : "验证并进入零售商城"}</button></form><div className="demo-phones"><strong>演示说明</strong><button onClick={() => setPhone("13900139000")}>使用演示手机号：13900139000</button><span>当前演示验证码统一为 6688；零售手机号无需后台预先添加。</span></div></div></section></main>;
}
