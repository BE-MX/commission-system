declare namespace Cloudflare {
  interface Env {
    FILES: R2Bucket;
    ARK_STORAGE_ENDPOINT?: string;
    ARK_STORAGE_SECRET?: string;
  }
}
