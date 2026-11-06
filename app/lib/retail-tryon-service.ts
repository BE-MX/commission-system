import { env } from "cloudflare:workers";

const HEADER = "x-retail-tryon-service";
const LOCAL_SECRET = "local-retail-tryon-service-only";

function configuredSecret(request: Request) {
  const value = (env as unknown as { RETAIL_TRYON_SERVICE_SECRET?: string }).RETAIL_TRYON_SERVICE_SECRET?.trim();
  if (value) return value;
  const host = new URL(request.url).hostname;
  return host === "localhost" || host === "127.0.0.1" ? LOCAL_SECRET : "";
}

export function requireRetailTryonService(request: Request) {
  const expected = configuredSecret(request);
  const actual = request.headers.get(HEADER) ?? "";
  return expected.length >= 24 && actual === expected;
}
