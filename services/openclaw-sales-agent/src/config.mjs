import { lstatSync, readFileSync } from "node:fs";
import { resolve } from "node:path";

const TOKEN_MIN_LENGTH = 32;

export class ArkConfigurationError extends Error {
  constructor(message) {
    super(message);
    this.name = "ArkConfigurationError";
  }
}

function required(env, key) {
  const value = String(env[key] || "").trim();
  if (!value) {
    throw new ArkConfigurationError(`缺少必填环境变量 ${key}`);
  }
  return value;
}

function parseOrigin(value, key) {
  let parsed;
  try {
    parsed = new URL(value);
  } catch {
    throw new ArkConfigurationError(`${key} 必须是有效 URL`);
  }
  if (!["http:", "https:"].includes(parsed.protocol)) {
    throw new ArkConfigurationError(`${key} 只允许 http/https`);
  }
  if (parsed.username || parsed.password || parsed.search || parsed.hash) {
    throw new ArkConfigurationError(`${key} 不允许凭据、查询参数或片段`);
  }
  return parsed;
}

export function loadConfig(env = process.env) {
  const rawBaseUrl = required(env, "ARK_BASE_URL");
  const rawAllowedOrigin = required(env, "ARK_ALLOWED_ORIGIN");
  const token = loadToken(env);
  const agentId = required(env, "ARK_AGENT_ID");
  const baseUrl = parseOrigin(rawBaseUrl, "ARK_BASE_URL");
  const allowedOrigin = parseOrigin(rawAllowedOrigin, "ARK_ALLOWED_ORIGIN");

  if (baseUrl.origin !== allowedOrigin.origin) {
    throw new ArkConfigurationError("ARK_BASE_URL 与 ARK_ALLOWED_ORIGIN 必须同源");
  }
  if (allowedOrigin.pathname !== "/") {
    throw new ArkConfigurationError("ARK_ALLOWED_ORIGIN 只能包含 scheme/host/port");
  }
  if (token.length < TOKEN_MIN_LENGTH) {
    throw new ArkConfigurationError(`ARK_AGENT_TOKEN 长度不能小于 ${TOKEN_MIN_LENGTH}`);
  }
  if (agentId.length > 96) {
    throw new ArkConfigurationError("ARK_AGENT_ID 长度不能超过 96");
  }

  return Object.freeze({
    baseUrl: baseUrl.href.replace(/\/+$/, ""),
    allowedOrigin: allowedOrigin.origin,
    token,
    agentId,
    timeoutMs: Number.parseInt(env.ARK_API_TIMEOUT_MS || "30000", 10),
  });
}

function loadToken(env) {
  const tokenPath = resolve(required(env, "ARK_AGENT_TOKEN_FILE"));
  let stat;
  try {
    stat = lstatSync(tokenPath);
  } catch {
    throw new ArkConfigurationError("ARK_AGENT_TOKEN_FILE 不存在或不可读");
  }
  if (!stat.isFile() || stat.isSymbolicLink()) {
    throw new ArkConfigurationError("ARK_AGENT_TOKEN_FILE 必须是普通文件，不允许符号链接");
  }
  if (typeof process.getuid === "function" && stat.uid !== process.getuid()) {
    throw new ArkConfigurationError("ARK_AGENT_TOKEN_FILE 必须属于当前用户");
  }
  if ((stat.mode & 0o777) !== 0o600) {
    throw new ArkConfigurationError("ARK_AGENT_TOKEN_FILE 权限必须为 0600");
  }
  try {
    return readFileSync(tokenPath, "utf8").trim();
  } catch {
    throw new ArkConfigurationError("ARK_AGENT_TOKEN_FILE 不可读");
  }
}
