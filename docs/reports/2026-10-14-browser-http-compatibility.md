# 内网 HTTP 浏览器兼容修复

实现阶段及验证记录；最终Git交付状态见 `docs/handoff.md` 最新交付条目。

2026-10-14，本地实现与验证完成。分支 `codex/receipt-delete-entry`，未合并、推送或部署；不修改生产角色权限、不提交实际回款或其他业务操作。摄像头按本次要求保持现状。

## 用户影响

相同前端代码在内网 HTTP 地址下缺少 `crypto.randomUUID` 和异步剪贴板接口。此前部分操作在请求前报错，另有手机素材页跳过复制却提示成功的问题。

新增共享 `frontend/src/utils/requestKey.js`，用 `crypto.getRandomValues` 生成 UUIDv4；各入口仍在原位置生成标识，原有 const/ref/map、冻结提交、sessionStorage及失败重试生命周期不变。没有时间戳或 Math.random 的弱随机替代。知识文档优化保留原去连字符格式，图片工作室保留原业务前缀；已持久保存的旧请求键继续原样核对与重试。

23 个调用文件统一接入：订单关联保存、补登记/修正回款、单笔与批量回款、发货结算、半成品入库与库存调整、出库工作站、售后审核流程、门户账号与通知、内贸决策行动/任务、WhatsApp分析、知识文档优化、获客任务、Agent任务/经营副驾驶、内贸下单/追加明细/报工、客户图片生成、图片工作室、展会图片提交。展会仅替换提交标识，摄像头代码未改。

新增共享 `frontend/src/utils/clipboard.js`：优先使用异步剪贴板；缺失或被拒绝时尝试选中文本复制；仅浏览器确认成功时返回 true。临时节点移除并恢复原焦点及文本选择。物流列表/详情/运单成功页、素材收藏、任务书、AI聊天、知识优化建议、售后话术及AI网关配置接入。

手机素材页的搜索、收藏、最近、详情共四处复制，失败时提供含实际链接的手动复制提示，不显示已复制、不设置复制成功状态、不记录 `copy_link`。主站及手机页使用同一份工具源码；Vite开发服务提供 `/m/clipboard.js`，生产构建发出同路径文件，不依赖生产不存在的 `src/` 路径。

截图导入保留原 Ctrl/Cmd+V 及上传入口；MCP配置和客户图片管理原有复制兼容处理保持。主站、PM站和手机素材业务源码扫描未留下 `randomUUID` 调用；第三方静态供应商包不改。

## 验证

- 先运行新增行为回归，原实现因 `crypto.randomUUID is not a function` 及剪贴板不存在失败；修复后通过。UUID格式/安全随机来源、1000键唯一性、关联保存丢失响应原键原body、复制成功/拒绝/异常、焦点和选择恢复、四处手机失败反馈均覆盖。
- 相关Node联合回归 **151 passed**；回款列表创建/编辑与列表读取失败独立回归 **3 passed**。VM测试夹具接入真实共用工具，WhatsApp不再使用固定伪造键；内贸下单夹具补当前已存在的提成配置及真实转换函数，不弱化业务断言。
- 实际 LAN HTTP：`isSecureContext=false`，`randomUUID`、`navigator.clipboard` 均不存在。共享工具复制后通过真实 Ctrl+V 校验相同中文内容；拒绝复制不报成功，恢复原input焦点与选择。手机素材页开发服务和生产构建预览均通过成功/失败路径；失败不新增复制审计。
- 补登记回款普通业务员/管理员两角色：模拟首次503，资料保留，同键同payload重试成功。批量回款和发货结算分别在1440/390/320宽度运行原有完整恢复脚本，验证未知结果冻结、仅查询核对、原键原资料重试、重新打开/刷新恢复、身份隔离、迟到结果及存储失败；全部通过，零页面异常。所有业务API使用本地替身，不访问生产业务接口。发货结算测试旧等待文案同步为当前“本批发货，定金保留”，保留全部恢复断言。
- `npm run build` 成功；`dist/m/clipboard.js` 与共享源码 SHA256一致，生产静态页真实HTTP加载通过。保留既有混合引用和大包提示。
- 独立 agent 审查随机性、调用方重试生命周期、复制反馈、焦点恢复、手机模块加载及最终产物，无新增阻断；独立生成10000个UUID，格式正确且无重复。
- 约定/diff检查与 `git_sweep.py --no-fetch` 收尾执行，巡检为本地快照。

原有测试限制：`listPagePilots.test.mjs` 的 invoice controller 场景缺少 `invoiceSubmissionGuard` 测试模块；使用 HEAD 原测试在隔离临时副本复现相同失败。本次不改该未受影响的订单列表逻辑、不弱化断言；该文件中受影响的3个回款场景已独立通过，不能将全文件称为通过。

主要复现脚本为 `frontend/tests/browserHttpCompatibility.test.mjs`、`browserHttpCompatibility.browser.mjs`、`receiptRegistrationHttp.browser.mjs`、既有批量回款与发货结算恢复浏览器脚本。原始结果、构建与基线失败记录保留在本worktree的 `tmp/browser-http-*` 与 `tmp/receipt-register-http/`。
