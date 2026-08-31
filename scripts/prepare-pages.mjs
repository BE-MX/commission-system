import { copyFile } from "node:fs/promises";

await Promise.all([
  copyFile("cloudflare-pages/_worker.js", "dist/client/_worker.js"),
  copyFile("cloudflare-pages/wrangler.json", "dist/server/wrangler.json"),
]);

console.log("Cloudflare Pages deployment files are ready.");
