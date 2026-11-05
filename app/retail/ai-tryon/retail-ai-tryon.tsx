"use client";

import { useEffect, useState } from "react";

type Status = "loading" | "available" | "active" | "used" | "error";

export default function RetailAiTryOn({ phone }: { phone: string }) {
  const [status, setStatus] = useState<Status>("loading");
  const [grantToken, setGrantToken] = useState("");
  const [starting, setStarting] = useState(false);
  const [message, setMessage] = useState("");

  const applyData = (data: { status?: Status; grantToken?: string; error?: string }) => {
    if (data.grantToken) setGrantToken(data.grantToken);
    setStatus(data.status ?? "error");
    setMessage(data.error ?? "");
  };

  useEffect(() => {
    fetch("/api/retail-ai-tryon", { cache: "no-store" })
      .then(async (response) => ({ response, data: await response.json() }))
      .then(({ response, data }) => response.ok ? applyData(data) : applyData({ status: "error", error: data.error }))
      .catch(() => applyData({ status: "error", error: "网络连接失败，请稍后再试" }));
  }, []);

  const start = async () => {
    if (starting) return;
    setStarting(true);
    setMessage("");
    try {
      const response = await fetch("/api/retail-ai-tryon", { method: "POST" });
      const data = await response.json();
      applyData(response.ok ? data : { status: "error", error: data.error });
    } catch {
      applyData({ status: "error", error: "网络连接失败，请稍后再试" });
    } finally {
      setStarting(false);
    }
  };

  const returnUrl = typeof window === "undefined" ? "" : `${window.location.origin}/retail`;
  const tryonUrl = grantToken
    ? `https://leshine.cloud/expo/retail#grant=${encodeURIComponent(grantToken)}&return=${encodeURIComponent(returnUrl)}`
    : "";

  if (status === "active" && tryonUrl) {
    return <main className="retail-tryon-shell">
      <header className="retail-tryon-header">
        <a href="/retail">‹ 返回商城</a>
        <div><b>AI 智能试戴</b><span>零售客户专享</span></div>
        <span>{phone.replace(/(\d{3})\d{4}(\d{4})/, "$1****$2")}</span>
      </header>
      <iframe title="莱莎 AI 智能试戴" src={tryonUrl} allow="camera; microphone; fullscreen; clipboard-read; clipboard-write" />
    </main>;
  }

  return <main className="retail-tryon-entry"><section>
    <a className="tryon-back" href="/retail">‹ 返回零售商城</a>
    <div className="tryon-mark">AI</div>
    <small>LESHINE AI HAIRSTYLE</small>
    <h1>找到更适合你的发型</h1>
    <p>上传一张正面照片，AI 将分析脸型与气质，并生成发型试戴效果。</p>
    <div className="tryon-rules"><strong>零售客户专享福利</strong><span>每个手机号只有 1 次免费机会</span><span>点击“开始试戴”后即启用本次资格</span><span>照片仅用于本次分析与试戴</span></div>
    {status === "loading" && <button disabled>正在查询免费资格…</button>}
    {status === "available" && <button onClick={start} disabled={starting}>{starting ? "正在开启…" : "开始免费试戴"}</button>}
    {status === "used" && <div className="tryon-used"><strong>免费体验机会已使用</strong><span>如需再次体验，请联系您的专属销售或客服为您开通。</span><a href="/retail/profile">联系专属客服</a></div>}
    {status === "error" && <div className="tryon-used"><strong>暂时无法进入试戴</strong><span>{message || "请稍后再试，或联系专属客服。"}</span><button onClick={() => window.location.reload()}>重新查询</button></div>}
  </section></main>;
}
