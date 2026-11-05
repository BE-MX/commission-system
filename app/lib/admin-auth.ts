import { env } from "cloudflare:workers";
import { headers } from "next/headers";
import { getChatGPTUser } from "../chatgpt-auth";

const ADMIN_COOKIE = "leshine_admin_session";

function normalizeAdminPassword(value: string) {
  return value.toLocaleLowerCase("en-US");
}

async function digest(value: string) {
  const bytes = new TextEncoder().encode(value);
  const hash = await crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(hash), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

function safeEqual(left: string, right: string) {
  if (left.length !== right.length) return false;
  let mismatch = 0;
  for (let index = 0; index < left.length; index += 1) mismatch |= left.charCodeAt(index) ^ right.charCodeAt(index);
  return mismatch === 0;
}

function cookieValue(cookieHeader: string, name: string) {
  const prefix = `${name}=`;
  return cookieHeader.split(";").map((part) => part.trim()).find((part) => part.startsWith(prefix))?.slice(prefix.length) ?? "";
}

export async function verifyAdminPassword(password: string) {
  const configured = (env as unknown as { ADMIN_PASSWORD?: string }).ADMIN_PASSWORD ?? "";
  if (!configured || !password) return false;
  const [submittedHash, configuredHash] = await Promise.all([
    digest(normalizeAdminPassword(password)),
    digest(normalizeAdminPassword(configured)),
  ]);
  return safeEqual(submittedHash, configuredHash);
}

export async function adminSessionCookie() {
  const configured = (env as unknown as { ADMIN_PASSWORD?: string }).ADMIN_PASSWORD ?? "";
  const token = await digest(normalizeAdminPassword(configured));
  return `${ADMIN_COOKIE}=${token}; Path=/; HttpOnly; Secure; SameSite=Strict; Max-Age=604800`;
}

export function clearAdminSessionCookie() {
  return `${ADMIN_COOKIE}=; Path=/; HttpOnly; Secure; SameSite=Strict; Max-Age=0`;
}

export async function adminAuthResult() {
  const user = await getChatGPTUser();
  if (user) {
    const configured = (env as unknown as { ADMIN_EMAIL?: string }).ADMIN_EMAIL ?? "";
    const allowedEmails = configured.split(",").map((item) => item.trim().toLowerCase()).filter(Boolean);
    if (allowedEmails.includes(user.email.toLowerCase())) return { ok: true as const, user };
  }

  const configuredPassword = (env as unknown as { ADMIN_PASSWORD?: string }).ADMIN_PASSWORD ?? "";
  if (configuredPassword) {
    const requestHeaders = await headers();
    const submitted = cookieValue(requestHeaders.get("cookie") ?? "", ADMIN_COOKIE);
    const expected = await digest(normalizeAdminPassword(configuredPassword));
    if (submitted && safeEqual(submitted, expected)) {
      return { ok: true as const, user: { userId: "password-admin", displayName: "管理员", email: "", fullName: "管理员" } };
    }
  }

  return { ok: false as const, status: 401, error: "请输入后台管理密码" };
}

export async function requireAdminApi() {
  const result = await adminAuthResult();
  return result.ok ? null : Response.json({ error: result.error }, { status: result.status });
}
