# 站点后端接入示例

这是业务员自建站点的最小 Python 后端，调用方舟网关，不直接调用供应商。需要方舟已部署网关并由管理员授权文本 Preset。

## 本地运行

在当前目录创建独立 Python 环境，安装 requirements.txt，将 `.env.example` 复制为 `.env` 并在本机编辑真实配置，不提交 `.env`。

```powershell
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt
.venv/Scripts/python -m uvicorn main:app_factory --factory --host 127.0.0.1 --port 8015
```

`POST /generate` 接受 `{"text":"需要翻译的内容"}`。请求头使用 `Authorization: Bearer <SITE_VISITOR_TOKEN>`，它是示例站点的独立访问口令，不是方舟站点密钥。

示例保留 `require_visitor` 登录校验挂接点。正式网站接入自己的登录态或邀请制，并按访问者限流；不要公开无限调用接口。方舟的每站限额是总量保护，不能替代站点的访问者管理。

## 交给 Codex 的接入任务

> 在站点后端增加 AI 文本调用，参考 main.py。使用服务端环境变量 ARK_AI_BASE_URL、ARK_AI_KEY、ARK_AI_PRESET；我会自行配置真实值。浏览器只调用站点自己的受保护后端接口。向方舟 POST /chat，使用 Bearer 站点密钥、每个业务请求一个 UUID 格式 X-Request-ID，消息仅含 user/assistant 文本。遵循 64 KiB、20 条消息、16,000 字符限制，云函数执行时间应超过 75 秒。显示限额、权限和超时错误及 request_id；任何超时或结果未知都不自动重发。不要把方舟密钥写入源码、浏览器配置、日志或提示词。

## 响应与重试

- 正常返回 content、request_id；示例不把方舟内部细节传给浏览器。
- 429 代表方舟次数或并发已满，提示稍后操作或联系管理员。
- 409 代表同一 Request ID 已准入，不能把换 ID 当成自动重试方案。
- 502/503/504 或网络断开时结果可能未知，保留 request_id，联系站点负责人到方舟查记录。
- 供应商 token 用量以方舟记录为准；超时不代表未消耗费用。

示例通过独立的 mock 网关测试：未登录不外呼、只使用服务端 Preset、密钥不回传、失败不重试。真实供应商调用仍需环境凭据和测试额度授权。
