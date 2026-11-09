# AI 接入管理配置生效改造

## 结果与范围

新型号及供应商不再需要更新生图型号枚举；已支持的 OpenAI / Anthropic / Images / Chat 图片协议内，后台配置会用于后续新请求。业务选择预设，预设决定真实型号、地址、认证和参数。新协议仍须新增适配器，供应商也必须实际支持所配参数。

代码位于 `codex/ai-runtime-configuration` 独立工作区。本次未修改生产配置、未付费生图或部署；2026-11-09 已获授权提交、合并并推送。

本轮后续补齐的提供商/预设参数、迁移与验证见 [参数维护交付报告](2026-11-09-ai-admin-settings.md)。

## 使用方式

普通业务保留原预设名（如 `customer_ai_chat`、`invoice_screenshot_extract`），修改绑定 Provider、型号、提示词与调用参数即可。新增一个任意名称不会自动替换业务所用预设。

生图预设可使用任意名称，勾选「在 AI 生图中使用」，填写模型和显示名称，并选择 Images 或 Chat Completions。已有 `design_image_generation` 及其下划线后缀预设无需迁移即可出现。不同供应商的同名型号使用不同预设区分。

```json
{
  "studio": {
    "enabled": true,
    "label": "营销图片",
    "sizes": ["1024x1024", "1536x1024"],
    "qualities": ["medium", "high"]
  },
  "api_style": "images",
  "size": "1536x1024",
  "quality": "high",
  "max_reference_images": 3,
  "output_format": "png",
  "response_format": "b64_json",
  "download_hosts": ["images.example.com"],
  "request_parameters": {"seed": 123}
}
```

示例域名须换成供应商实际图片下载域名。下载仍执行 HTTPS、域名允许列表、DNS/IP、大小、类型与重定向限制；不因换型号放宽这些边界。若供应商使用比例而非像素，配置 `size_parameter=aspect_ratio`，允许 `WIDTHxHEIGHT` 或 `WIDTH:HEIGHT`。自定义质量在 chat 图片模式中作为提示词约束，效果取决于供应商。

生图页面每次选择覆盖预设默认值；首次选择型号采用它的默认值。API 省略尺寸/质量时采用当前预设默认。参数 JSON 格式错误不会保存或清空旧值。

## 配置一致性

- 列表和新任务即时读取数据库，不缓存型号名单。任务 `model` 为实际调用型号审计快照；列表 `id` 为预设名。
- 已排队/运行任务继续校验预设指纹，配置漂移报错，不静默换型号。
- 失败重试是新请求，读取同一预设当前配置，重新校验输入图数量、尺寸和质量。新待确认消息持久化精确预设名，改名后明确失效，不按相似型号改投。
- 升级前存储的型号选择仅在无同名预设且唯一命中可用图片预设时解析，以保护既有持久消息。
- 去掉方案对话 `AI_CHAT_MODEL` 环境变量门槛和客户生图的固定 gpt-image-2 门槛；保留协议能力、权限、预算、工具和业务输出校验。
- 停止启动时覆写已存在的 TeamRouter 地址/发票截图模型；种子仅创建缺失配置，后续审计也已移除历史提示词启动覆写。
- 扩展参数不能覆盖业务模型、提示词、图片、消息、工具、stream 或 n。Multipart 对象/数组以 JSON 字符串编码。内部管理参数不发送到模型。

## 验证

- 扩展后端回归：1080 passed、1 skipped、2 failed；失败为下述 main 已存在的附件清理行为测试。
- Gateway / Agent 与新增配置回归：153 passed、2 failed；两项失败在未改动 main 上复现：`test_seeded_run_token_can_read_raw_message_and_source_chunk` 与 `test_repurchase_projection_revalidates_live_customer_and_run_scope[opportunity_owner]`，分别涉及客户消息查询和 Portal authority 的测试库缺失表/依赖。未修改这些业务行为。
- 独立审查：52 项针对性回归全过，已关闭配置别名错投、参考数绕过、默认值与真实请求格式漂移问题。
- 最终前端选型、配置编辑与生图相关回归：59 passed；`npm run build` 通过（保留现有大 chunk 提示）。
- 严格增量约定检查与 `git diff --check` 通过；巡检 `git_sweep --no-fetch` 仅为本地快照，不构成合并/推送/部署授权。

隔离 SQLite、模拟网络，不连接生产数据库进行写入。浏览器使用实际 AIManager/composable 与内存模拟 API，外部请求被阻断；通过保存、重新打开、非法 JSON 阻止保存、参数保留及 375×812 窄屏验证。证据在 `tmp/ai-runtime-ui/results.json`。

已确认基线问题：`test_ai_chat_idempotency_cleanup` 的两项附件删除行为测试在未改动 main 上同样失败，涉及清理异常/数据库删除失败后的重试；本次不扩大范围修改。
