# 客户查重接口说明（v1）

| 项目 | 内容 |
|---|---|
| 接口名称 | 客户查重 |
| 版本 | v1（2026-11-27） |
| 提供方 | 莱莎方舟平台（AI 技术支持部） |
| 适用对象 | 公司内部同事自建的客户开发工具、脚本或插件 |
| 正式地址 | `https://leshine.cloud/api/customer-dedup/check` |

## 1. 用途

开发新客户前，用客户的社媒账号或邮箱查询该客户在公司系统中的状态，避免重复开发已在同事私海的客户。

查询结果为以下四种之一：

| 结论 | 含义 | 建议动作 |
|---|---|---|
| 已在同事私海 | 客户已由同事负责 | 不要开发，必要时联系负责同事 |
| 已在公海 | 系统已收录，但没有绑定业务员 | 按公司公海规则申领后再开发 |
| 尚未收录 | 系统里没有这个账号或邮箱 | 可以开发 |
| 无法判断 | 账号太泛、匹配范围过大，或客户资料正在同步 | 补全账号后重查，或稍后再查；**不能当作「尚未收录」** |

接口只返回结论、客户名称和负责人姓名，不返回客户联系人的邮箱、电话等资料。

## 2. 接入准备

1. **开通权限**：请管理员给使用者的方舟账号分配权限「按社媒账号或邮箱查重客户」（`customer_dedup:read`）。
2. **领取个人 token**：请管理员在方舟后台发放个人 access token。一人一个，与方舟 MCP 使用的是同一种 token，已有的可直接使用。
3. **保管 token**：token 代表你的账号，只放在工具的环境变量或密钥配置中。不要写进代码、提交到代码仓库、发到聊天群或放进网址参数。泄露后请立即找管理员撤销并重新发放。

## 3. 认证方式

每个请求都在请求头中携带 token：

```
Authorization: Bearer <个人 token>
```

- 每次请求都会实时核对账号状态和当前权限：账号停用或权限被收回后立即失效。
- 也可以使用方舟主站的登录会话 token，适合嵌在方舟网页内的工具。小程序登录凭证和其他专用凭证不能调用本接口。

## 4. 接口定义

### 4.1 请求

```
POST https://leshine.cloud/api/customer-dedup/check
Content-Type: application/json
Authorization: Bearer <个人 token>
```

请求体（JSON）：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `account` | string | 是 | 要查重的账号，1–500 个字符。可以是主页链接、账号名（可带 `@`）、WhatsApp 号码、邮箱或 `mailto:` 链接 |
| `platform` | string | 条件必填 | 账号所属平台。提交完整主页链接、邮箱或号码时可省略，系统自动识别；**只提交账号名时必须填写** |

`platform` 可选值（不区分大小写）：

| 平台 | 取值 | 也接受 |
|---|---|---|
| Instagram | `instagram` | `ig`、`ins` |
| Facebook | `facebook` | `fb`、`messenger` |
| WhatsApp | `whatsapp` | `wa` |
| 微信 | `wechat` | `weixin`、`微信` |
| LinkedIn | `linkedin` | `领英` |
| Pinterest | `pinterest` | |
| TikTok | `tiktok` | |
| X（Twitter） | `x` | `twitter` |
| Yelp | `yelp` | |
| YouTube | `youtube` | `yt` |
| 邮箱 | `email` | `mail`、`邮箱` |

请求体不接受其他字段，多传字段会返回 422。

### 4.2 请求示例

```json
{"account": "https://www.instagram.com/glam.hair_la/"}
```

```json
{"account": "@glam.hair_la", "platform": "instagram"}
```

```json
{"account": "+1 202 555 0123"}
```

```json
{"account": "sales@example.com"}
```

### 4.3 成功响应

HTTP 状态码 `200`，统一信封格式：

```json
{
  "code": 200,
  "message": "该客户已进入同事私海：Glam Hair LLC（负责人：张三、Lily）",
  "data": {
    "status": "private",
    "message": "该客户已进入同事私海：Glam Hair LLC（负责人：张三、Lily）",
    "platform": "instagram",
    "platform_label": "Instagram",
    "normalized_account": "glam.hair_la",
    "matched_count": 1,
    "customers": [
      {
        "company_name": "Glam Hair LLC",
        "status": "private",
        "owners": ["张三", "Lily"],
        "is_mine": false
      }
    ]
  }
}
```

`data` 字段说明：

| 字段 | 类型 | 说明 |
|---|---|---|
| `status` | string | 结论：`private` 已在私海 / `public` 已在公海 / `not_found` 尚未收录 / `inconclusive` 无法判断 |
| `message` | string | 给使用者看的结论文字，可直接展示 |
| `platform` | string | 识别出的平台取值（见 4.1） |
| `platform_label` | string | 平台的显示名称 |
| `normalized_account` | string | 统一写法后的账号，用于排查「为什么没查到」 |
| `matched_count` | integer \| null | 命中的客户总数；`inconclusive` 时为 `null` |
| `customers` | array | 命中的客户，最多 10 个，私海客户排在前面 |
| `customers[].company_name` | string | 客户名称 |
| `customers[].status` | string | 该客户的状态：`private` 或 `public` |
| `customers[].owners` | string[] | 负责人姓名；公海客户为空数组 |
| `customers[].is_mine` | boolean | 调用者本人是否是负责人之一 |

`status` 与 `message` 对照：

| `status` | `message` 示例 |
|---|---|
| `private` | 该客户已进入同事私海：Glam Hair LLC（负责人：张三、Lily） |
| `private`（只由你本人负责） | 该客户已在你自己的私海：Mine Hair |
| `public` | 当前客户已进入公海，未绑定业务员：Open Sea Wigs |
| `not_found` | 当前系统尚未收录此客户 |
| `inconclusive` | 这个账号太短、匹配范围过大，无法可靠查重，请提交完整账号或主页链接 |

判断时请以 `status` 为准，不要解析 `message` 文字，因为文字可能调整。同一账号挂在多个客户下时，只要其中一个在私海，整体结论就是 `private`。

### 4.4 失败响应

失败时返回对应 HTTP 状态码，响应体为 `{"detail": "原因说明"}`，原因说明可直接展示给使用者。两个例外：422 的 `detail` 是字段错误列表；500 的响应体为 `{"code": 500, "message": "原因说明", "data": null}`。

| HTTP 状态码 | 含义 | 处理方式 |
|---|---|---|
| 400 | 无法识别平台、链接不是主页（如帖子或分享链接）、号码位数太少、账号太短等 | 按 `detail` 修改后重试，不要原样重试 |
| 401 | 缺少 token、token 无效或已撤销、账号停用、登录已过期 | 检查 token 配置，或找管理员重新发放 |
| 403 | 账号没有查重权限 | 找管理员分配权限 |
| 422 | 请求体格式错误：缺 `account`、类型不对或多传字段 | 修正请求体 |
| 429 | 超出调用频率限制 | 等待后重试，见第 5 节 |
| 500 | 服务内部错误或数据库连接失败 | 稍后重试；持续出现请联系 AI 技术支持部 |
| 503 | 服务暂时不可用（查询记录写入失败），本次没有返回结论 | 稍后重试 |

## 5. 调用限制

- 每人每分钟最多 30 次，每天最多 600 次。「每天」按北京时间 00:00 起算，同一个人用多个工具调用时共享额度。
- 返回 400、401、403、422 的请求不计入次数；已受理的查询（包括结论为「无法判断」的）计入次数。
- 不提供模糊搜索、批量导出或分页浏览。每次查询都会记录查询人、平台、统一后的账号和结论，用于限频和排查异常调用。
- 请在使用者确实要开发某个客户时再查询，不要批量轮询客户名单。

## 6. 调用示例

### curl

```bash
curl -sS -X POST "https://leshine.cloud/api/customer-dedup/check" \
  -H "Authorization: Bearer $ARK_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"account": "https://www.instagram.com/glam.hair_la/"}'
```

### Python

```python
import os

import requests

resp = requests.post(
    "https://leshine.cloud/api/customer-dedup/check",
    headers={"Authorization": f"Bearer {os.environ['ARK_TOKEN']}"},
    json={"account": "@glam.hair_la", "platform": "instagram"},
    timeout=15,
)
if resp.status_code == 200:
    data = resp.json()["data"]
    print(data["status"], data["message"])
else:
    print(resp.status_code, resp.json().get("detail"))
```

### JavaScript

```javascript
const resp = await fetch("https://leshine.cloud/api/customer-dedup/check", {
  method: "POST",
  headers: {
    "Authorization": `Bearer ${process.env.ARK_TOKEN}`,
    "Content-Type": "application/json",
  },
  body: JSON.stringify({ account: "sales@example.com" }),
});
const body = await resp.json();
if (resp.ok) {
  console.log(body.data.status, body.data.message);
} else {
  console.log(resp.status, body.detail);
}
```

## 7. 比对规则

供排查「明明有这个客户却没查到」时参考。

**社媒账号**：两边先统一写法再比较。

- 去掉 `http(s)://`、`www.`、`m.`、国家子域名（如 `uk.pinterest.com`）、`?` 后面的参数和结尾斜杠。
- 账号不区分大小写，`@` 可有可无。
- `twitter.com` 与 `x.com` 视为同一平台；Messenger 链接（`m.me/…`）按 Facebook 处理。
- Facebook 的 `profile.php?id=…`、`/people/名称/数字`、`/pages/名称/数字`、`/p/名称-数字` 都按数字 ID 比较。
- LinkedIn 区分个人页 `in/` 和公司页 `company/`。只提交账号名时两种都会比对。
- YouTube 区分 `@账号`、`channel/`、`user/`、`c/`。只提交账号名时比对 `@账号` 和 `c/` 两种写法。
- 帖子、视频、分享按钮、搜索页这类不是主页的链接不参与查重，会返回 400。

**WhatsApp / 微信号码**：

- 只比数字，忽略空格、括号、横线、点和开头的 `+` 或 `00`。
- 系统里存的号码缺国家区号时（可带一个开头的 `0`，如英国 `07911…`）也能匹配：去掉的前缀必须是 1–3 位，剩下至少 9 位。
- **请尽量提交带国家区号的完整号码**（如 `+44 7911 123456`）。不带区号时，不同国家的同一本地号码可能同时命中。

**邮箱**：不区分大小写。同时查客户联系人邮箱和客户主邮箱，主邮箱中用逗号、分号或空格分隔的多个邮箱都会比对。

## 8. 变更记录

| 版本 | 日期 | 说明 |
|---|---|---|
| v1 | 2026-11-27 | 首版：10 个社媒平台和邮箱查重，个人 token 认证，限频与查询记录 |
