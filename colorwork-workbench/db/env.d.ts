declare namespace Cloudflare {
  interface Env {
    DB: D1Database;
    FILES: R2Bucket;
    BOOTSTRAP_ADMIN_EMAIL?: string;
    /** 方舟平台集成：SSO 共享密钥（对应方舟后端 COLORWORK_SSO_SECRET）。 */
    ARK_SSO_SECRET?: string;
    /** 方舟库存状态接口地址（…/api/colorwork/inventory-status），留空则不启用 okki 自动覆盖。 */
    ARK_STATUS_ENDPOINT?: string;
    /** 回源共享密钥（对应方舟后端 COLORWORK_SYNC_KEY）。 */
    ARK_SYNC_KEY?: string;
  }
}
