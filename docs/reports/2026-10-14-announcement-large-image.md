# 公告图片上传超时修复（Git 交付，未部署）

用户反馈编辑公告插入约 2.2M 图片，等待 30–40 秒后显示“上传失败”。公告复用 KnowledgeEditor，原图片直接 multipart 上传到 `/api/knowledge/libraries/{id}/assets`，继承 knowledgeClient 的 30 秒超时；界面仅提取 `detail`，网络超时被泛化为上传失败。真实 Axios 延迟响应回归在原实现出现 timeout，在修复后通过。

2026-10-14 只读核对北京线上配置：`knowledge_cos_enabled=True`、图片上限 10MiB。存储链路是浏览器 → 业务后端 → 图片验证/规范化 → COS，并非浏览器直传。北京当前访问日志内有一条公告库上传 400/0 字节回执，未取得本次请求的逐段耗时，不能将该条日志认定为用户请求，也不能认定 COS 本身慢。新加坡近期日志无匹配上传。本轮未创建生产图片、公告、业务记录，也没有修改线上配置。

## 修改

- 只延长图片上传请求到 180 秒，保留普通知识库请求的 30 秒。
- 大于 400KiB 的图片尝试浏览器重编码，最长边 2400px，JPEG/WebP quality 0.9；PNG 保持 PNG、透明像素保留。编码结果更大或格式变化时使用原文件；小图不重编码。大于 10MiB 或 60MP 的输入保留服务端验证路径。
- 传输完成后显示“图片已传输，正在处理并保存…”。超时、断网、413 和服务端业务错误显示可采取行动的原因。没有自动重发；失败节点仍阻断保存。
- 保留原图的文件名；成功后正文仍仅保存 assetId/alt/caption，权限及私有读取接口未改变。JPEG/WebP 重编码是有损优化，图片压缩比例依内容而定。

## 验证

- `node --test tests/knowledgeImageUpload.test.mjs tests/knowledgeEditor.test.mjs tests/announcement.test.mjs`：21 passed。慢上传测试使用真实 Axios/本地 HTTP 服务，并缩放时间预算；原实现复现超时，修复后成功且仅请求一次。
- `knowledgeImageUpload.browser.py`：真实 Edge XHR 等待约 33.83 秒成功、一次 POST、成功保存规范正文。API 被 Playwright 拦截，未连接真实后端。
- 生成图片样本：2,202,481 字节的含大段文本元数据 PNG → 8,936 字节，尺寸 800×450、透明像素保留；6,489,332 字节的高质量噪声 JPEG → 1,800,321 字节，尺寸 2400×1350。这是特定测试样本，不能推定用户图片有相同压缩比例。
- `announcementImages.browser.py`：文件选择、原生 Ctrl+V、保存重载、缺失 randomUUID、上传中/失败保存阻断、撤销重贴、并行上传、知识库及只读编辑全部通过。
- `npm run build`：通过，只有既有大包/动态导入警告。
- `check_conventions.py --strict`：全量 UI 门禁被既有 17 项发票表格问题阻断；本任务未触及发票表格。独立调用脚本的 `check('HEAD')` 检查本任务增量，0 项违规；全量门禁仍未通过。
- `git diff --check` 通过；`git_sweep.py --no-fetch` 已运行，仅本地远端快照，没有远端写入。

证据保存在本任务 worktree 的 `tmp/knowledge-image-upload/` 与 `tmp/announcement-images/`。分支 `codex/announcement-large-image`，用户已授权本次代码及文档合并 main 并推送 origin，最终结果以远端回读为准；未部署；生产端到端上传仍需发布后验证。本地自查覆盖格式、透明背景、大小/像素验证边界、单次写请求和规范保存，没有改动跨域 API 权限或持久数据契约。
