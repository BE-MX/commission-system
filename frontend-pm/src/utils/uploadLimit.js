// 上传上限按「入口」定，不按后端定——两个入口的物理链路完全不同。
//
// 外网入口 pm.leshine.work：云服务器在腾讯云新加坡，文件字节要从新加坡再经 frp 隧道
// 推回济南办公室的后端。2026-07-22 实测这一跳只有 15~120 KB/s，且**没在 ~20 秒内推完
// 必被切断**，失败时还会带崩整条 frp 会话（全站 API 502 约 10 秒）。
// 实测：云端直推 256KB/512KB 过、1MB 挂；走完整公网路径 50KB/100KB 过、300KB 挂。
// 取交集定 256KB —— 这不是后端限制，是跨境链路的物理上限，宁可保守也别让一次上传抖全站。
//
// 内网入口（deploy.bat --base=/pm/，直连 192.168.101.193:8001）不经隧道，
// 20MB 实测 3.3 秒，维持后端 PM_MAX_UPLOAD_MB 的 50MB。
//
// 隧道这条路的根治方案（文件直传国内 COS / 主站回国内）落地后，这里应一并撤掉。

const IS_LAN_ENTRY = import.meta.env.BASE_URL.startsWith('/pm/')

export const LAN_ENTRY_URL = 'http://192.168.101.193:8001/pm/'

export const MAX_UPLOAD_BYTES = IS_LAN_ENTRY ? 50 * 1024 * 1024 : 256 * 1024

export const OVERSIZE_HINT = IS_LAN_ENTRY
  ? '超过 50MB 上限——大文件请改用「外部链接」类型备注网盘地址'
  : `外网入口单文件限 256KB（跨境链路上限）。大文件请在公司内网打开 ${LAN_ENTRY_URL} 上传，或改用「外部链接」类型备注网盘地址`

// 上传区那行说明文字：公网入口要把「为什么这么小、去哪传」一次说清，别让用户自己猜
export const UPLOAD_STRIP_HINT = IS_LAN_ENTRY
  ? '版本号自动 +1 · AI 自动对比上一版 · 单文件 ≤ 50MB'
  : `版本号自动 +1 · AI 自动对比上一版 · 外网入口单文件 ≤ 256KB，大文件走内网入口 ${LAN_ENTRY_URL}`
