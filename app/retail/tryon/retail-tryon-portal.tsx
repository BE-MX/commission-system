"use client";

import { useEffect, useRef, useState } from "react";

const AI_TRYON_URL = "https://leshine.cloud/expo/retail";
type LaunchState = "loading" | "ready" | "used" | "error";

export default function RetailTryonPortal() {
  const [state, setState] = useState<LaunchState>("loading");
  const [frameUrl, setFrameUrl] = useState("");
  const [message, setMessage] = useState("");
  const started = useRef(false);

  const launch = async () => {
    setState("loading");
    setMessage("");
    try {
      const response = await fetch("/api/retail-ai-tryon", { method: "POST" });
      const payload = await response.json() as { grantToken?: string; error?: string };
      if (response.status === 401) {
        window.location.replace("/retail/login");
        return;
      }
      if (response.status === 409) {
        setMessage(payload.error ?? "该账号的一次 AI 试戴机会已使用");
        setState("used");
        return;
      }
      if (!response.ok || !payload.grantToken) throw new Error(payload.error ?? "临时试戴账号创建失败");

      const target = new URL(AI_TRYON_URL);
      target.hash = new URLSearchParams({
        grant: payload.grantToken,
        return: `${window.location.origin}/retail`,
      }).toString();
      setFrameUrl(target.href);
      setState("ready");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "AI 试戴暂时无法打开");
      setState("error");
    }
  };

  useEffect(() => {
    if (started.current) return;
    started.current = true;
    void launch();
  }, []);

  if (state === "ready") {
    return <main className="retail-tryon-shell">
      <iframe
        src={frameUrl}
        title="莱莎 AI 发型试戴"
        allow="camera; clipboard-write"
        referrerPolicy="no-referrer"
      />
    </main>;
  }

  return <main className="retail-tryon-gate">
    <section>
      <span className="tryon-gate-mark">AI</span>
      {state === "loading" ? <>
        <h1>正在进入 AI 试戴</h1>
        <p>正在为当前商城账号创建一次性试戴身份，请稍候…</p>
        <i className="tryon-spinner" aria-label="加载中" />
      </> : <>
        <h1>{state === "used" ? "本次免费试戴已使用" : "AI 试戴暂时无法打开"}</h1>
        <p>{message}</p>
        <div className="tryon-gate-actions">
          {state === "error" && <button onClick={() => void launch()}>重新尝试</button>}
          <a href="/retail">返回商城</a>
          {state === "used" && <a className="secondary" href="/retail/profile#service">联系客服</a>}
        </div>
      </>}
    </section>
  </main>;
}
