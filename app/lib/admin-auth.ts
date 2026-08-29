import { env } from "cloudflare:workers";
import { getChatGPTUser } from "../chatgpt-auth";

export async function adminAuthResult() {
  const user = await getChatGPTUser();
  if (!user) return { ok: false as const, status: 401, error: "请先使用管理员ChatGPT账号登录" };
  const configured = (env as unknown as { ADMIN_EMAIL?: string }).ADMIN_EMAIL ?? "";
  const allowedEmails = configured.split(",").map((item) => item.trim().toLowerCase()).filter(Boolean);
  if (!allowedEmails.includes(user.email.toLowerCase())) return { ok: false as const, status: 403, error: "当前账号没有后台管理权限" };
  return { ok: true as const, user };
}

export async function requireAdminApi() {
  const result = await adminAuthResult();
  return result.ok ? null : Response.json({ error: result.error }, { status: result.status });
}
