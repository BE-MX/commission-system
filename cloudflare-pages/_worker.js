import app from "../server/index.js";

const STATIC_PREFIXES = ["/_next/static/", "/products/"];
const STATIC_FILES = new Set(["/favicon.svg", "/leshine-brand.jpg", "/og.png"]);

export default {
  async fetch(request, env, context) {
    const { pathname } = new URL(request.url);
    const isStaticRequest =
      request.method === "GET" || request.method === "HEAD";

    if (
      isStaticRequest &&
      env.ASSETS &&
      (STATIC_FILES.has(pathname) ||
        STATIC_PREFIXES.some((prefix) => pathname.startsWith(prefix)))
    ) {
      return env.ASSETS.fetch(request);
    }

    return app.fetch(request, env, context);
  },
};
