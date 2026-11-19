# 顺丰快件路由查询 — 其他应用接入指南

> **适用对象**：公司内部其他应用（自研系统、脚本、Agent）需要查询顺丰快件轨迹和状态时，照本文开发与配置即可接入。
> **接口**：顺丰开放平台「丰桥」路由查询接口 `EXP_RECE_SEARCH_ROUTES`，鉴权用 OAuth2。
> **校验日期**：2026-11-18（官方文档原文与沙箱实测）。
> **参考实现**：方舟平台 `backend/app/tracking/carriers/sf.py`（Python，含测试 `backend/tests/test_tracking_sf_adapter.py`）。

## 0. 当前状态（接入前先看）

| 项 | 状态 |
|---|---|
| 丰桥应用 | 「企业物流状态查询」，顾客编码 `HOFZPSKTV6TF` |
| 沙箱 | 已联调通过（2026-11-18） |
| 生产 | **以丰桥控制台「应用列表」中路由查询接口是否为「已上线」为准**。未上线前调生产地址会报 `A1004 无对应服务权限` |

所有应用**共用同一个顾客编码和校验码**，这样做的影响：

- **额度共享**：丰桥每个顾客编码、每个接口限 **30 次/秒、3000 次/天**，所有接入应用加起来算。请按第 6 节控制调用频率；用量较大的应用请先和负责人（亮哥）确认。
- **令牌共享**：同一顾客编码 2 小时内获取的 accessToken 是同一个，多个应用各自获取不会互相顶掉，可以放心各自缓存。
- **校验码是密钥**：只能放在环境变量或密钥管理里，不进代码仓库、不写日志、不发聊天。校验码向负责人索取；沙箱和生产的校验码不同。

## 1. 能查什么、查不到什么

可以查到：每一票的完整路由节点（时间、城市、描述、操作码）以及顺丰给出的一级、二级状态。

有以下限制：

1. **只能查本公司月结账号寄付的运单。** 按运单号查询（`trackingType=1`）时，运单的付款月结卡号必须和顾客编码绑定，否则 `routes` 为空。
   - 别人寄来的单、工厂用自己账号发的单：要额外传 `checkPhoneNo`（收件人或寄件人任一方手机号后 4 位），校验通过才返回。
2. **只能查 3 个月内的运单。**
3. **一次最多 10 个单号。**
4. `routes` 为空表示 无权限 / 还没有路由 / 超过 3 个月，三种情况接口不区分（有时会带 `reasonCode`、`reasonRemark`）。
5. 国际件（顺丰国际）不走这个接口。

## 2. 配置项

接入方应用里建议使用以下配置（名字可按自己项目的规范调整）：

```dotenv
SF_PARTNER_ID=HOFZPSKTV6TF      # 顾客编码
SF_CHECKWORD=                   # 校验码，向负责人索取，沙箱/生产不同
SF_SANDBOX=true                 # true=沙箱，false=生产
```

| 环境 | 业务地址 | 令牌地址 |
|---|---|---|
| 沙箱 | `https://sfapi-sbox.sf-express.com/std/service` | `https://sfapi-sbox.sf-express.com/oauth2/accessToken` |
| 生产 | `https://bspgw.sf-express.com/std/service` | `https://bspgw.sf-express.com/oauth2/accessToken` |

注意：沙箱返回的是 MOCK 数据，任何单号都会返回同一条示例轨迹，只能用来验证代码，不能验证业务数据。

## 3. 调用流程

```
① POST 令牌地址（partnerID + 校验码）→ accessToken（有效 2 小时，缓存复用）
② POST 业务地址（partnerID + requestID + serviceCode + timestamp + accessToken + msgData）
③ 解析 apiResultCode → apiResultData（JSON 字符串）→ msgData.routeResps[].routes[]
④ 若返回 A1011（令牌失效）→ 重新获取令牌，重试一次
```

两个请求都是 **`POST` + `Content-Type: application/x-www-form-urlencoded;charset=UTF-8`**，即表单提交，不是 JSON body。业务数据以 JSON 字符串放在表单字段 `msgData` 里。

### 3.1 获取令牌

| 表单字段 | 值 |
|---|---|
| `partnerID` | 顾客编码 |
| `secret` | 校验码 |
| `grantType` | 固定 `password` |

成功响应：

```json
{ "apiResultCode": "A1000", "apiErrorMsg": "success", "accessToken": "20D02FC4F63B4A4AA7C9A236EAD5B0A1", "expiresIn": 5150 }
```

`expiresIn` 单位为秒，是剩余有效期，不一定是 7200。缓存时按「当前时间 + expiresIn − 60 秒」计算过期时刻。

### 3.2 查询路由

| 表单字段 | 值 |
|---|---|
| `partnerID` | 顾客编码 |
| `requestID` | 每次请求生成一个新的 UUID |
| `serviceCode` | 固定 `EXP_RECE_SEARCH_ROUTES` |
| `timestamp` | 当前 Unix 毫秒时间戳 |
| `accessToken` | 3.1 拿到的令牌（**不要**同时传 `msgDigest`） |
| `msgData` | 下面的 JSON 字符串 |

```json
{
  "language": "zh-CN",
  "trackingType": "1",
  "trackingNumber": ["SF1011603494291"],
  "methodType": "1"
}
```

非本公司月结的单，加上 `"checkPhoneNo": "1234"`（多个单号时传多个后 4 位，用英文逗号隔开放在同一个字符串里，例如 `"1234,5678"`）。

### 3.3 响应

外层：

```json
{
  "apiResultCode": "A1000",
  "apiErrorMsg": "",
  "apiResponseID": "000173271968963FA47C03E68000103F",
  "apiResultData": "{\"success\":true,\"errorCode\":\"S0000\",\"errorMsg\":null,\"msgData\":{\"routeResps\":[...]}}"
}
```

- `apiResultCode=A1000` 只代表「平台校验通过」。**业务是否成功要看 `apiResultData` 里的 `success` 和 `errorCode`**（`S0000` 为成功）。
- `apiResultData` 是 **JSON 字符串**，需要再解析一次。

路由节点 `msgData.routeResps[].routes[]`：

| 字段 | 说明 |
|---|---|
| `acceptTime` | 节点时间，`YYYY-MM-DD HH:MM:SS`，**北京时间且不带时区**，月日可能不补零（如 `2012-7-30 09:30:00`） |
| `acceptAddress` | 城市 |
| `remark` | 节点描述（会包含快递员姓名和电话，展示和存储时注意隐私） |
| `opCode` | 操作码，如 50 揽收、44 派件出仓、80 签收 |
| `firstStatusCode` / `firstStatusName` | 一级状态 |
| `secondaryStatusCode` / `secondaryStatusName` | 二级状态 |

返回的节点不保证按时间排序，**自己按 `acceptTime` 排序后取最新一条作为当前状态**。

## 4. 状态归一化（建议与方舟保持一致）

按以下优先级判断最新节点：

1. 状态名称包含「退回」→ `returned`（已退回）
2. `opCode` 为 `70`（问题件）或 `934`（外配异常），或描述含「遗失」→ `exception`（异常）
3. 二级状态码：`204` 清关中 → `customs_hold`；`205` 已清关 → `in_transit`
4. 一级状态码：

| firstStatusCode | 顺丰含义 | 统一状态 |
|---|---|---|
| 1 | 已揽收 | `picked_up` 已揽收 |
| 2 | 运送中 | `in_transit` 运输中 |
| 3 | 派送中 | `out_for_delivery` 派送中 |
| 4 | 已签收 | `delivered` 已签收 |
| 5 / 6 | 已作废 / 已取消 | `exception` 异常 |
| 7 / 10 | 待揽收 / 仓库处理中 | `pending` 待处理 |
| 11 | 待取件（已到丰巢、驿站或网点） | `out_for_delivery` 派送中 |
| 13 | 待派送（滞留） | `in_transit` 运输中 |
| `-` 或其他 | 已转寄 / 未完善 | `in_transit` 运输中 |

完整码表见丰桥「服务与支持 → 业务文档 → 路由信息操作码」。

## 5. 参考代码

### 5.1 Python（httpx，可直接复制）

```python
import json, os, time, uuid
from datetime import datetime
import httpx

SANDBOX = os.environ.get("SF_SANDBOX", "true").lower() != "false"
BASE = "https://sfapi-sbox.sf-express.com" if SANDBOX else "https://bspgw.sf-express.com"
PARTNER_ID = os.environ["SF_PARTNER_ID"]
CHECKWORD = os.environ["SF_CHECKWORD"]
FORM = {"Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"}

_token, _token_exp = None, 0.0

def get_token(force=False) -> str:
    global _token, _token_exp
    if not force and _token and time.time() < _token_exp - 60:
        return _token
    body = httpx.post(f"{BASE}/oauth2/accessToken", headers=FORM, timeout=30, data={
        "partnerID": PARTNER_ID, "secret": CHECKWORD, "grantType": "password",
    }).json()
    if body.get("apiResultCode") != "A1000":
        raise RuntimeError(f"SF token {body.get('apiResultCode')}: {body.get('apiErrorMsg')}")
    _token, _token_exp = body["accessToken"], time.time() + int(body.get("expiresIn") or 7200)
    return _token

def _call(token: str, msg: dict) -> dict:
    return httpx.post(f"{BASE}/std/service", headers=FORM, timeout=30, data={
        "partnerID": PARTNER_ID,
        "requestID": str(uuid.uuid4()),
        "serviceCode": "EXP_RECE_SEARCH_ROUTES",
        "timestamp": str(int(time.time() * 1000)),
        "accessToken": token,
        "msgData": json.dumps(msg, ensure_ascii=False),
    }).json()

def query_routes(waybills: list[str], check_phone_no: str | None = None) -> dict[str, list[dict]]:
    """返回 {运单号: [路由节点, 按时间倒序]}；一次最多 10 个单号。"""
    assert 1 <= len(waybills) <= 10
    msg = {"language": "zh-CN", "trackingType": "1", "trackingNumber": waybills, "methodType": "1"}
    if check_phone_no:
        msg["checkPhoneNo"] = check_phone_no
    body = _call(get_token(), msg)
    if body.get("apiResultCode") == "A1011":          # 令牌失效，重取一次
        body = _call(get_token(force=True), msg)
    if body.get("apiResultCode") != "A1000":
        raise RuntimeError(f"SF api {body.get('apiResultCode')}: {body.get('apiErrorMsg')}")
    data = json.loads(body["apiResultData"])
    if not data.get("success"):
        raise RuntimeError(f"SF biz {data.get('errorCode')}: {data.get('errorMsg')}")

    result = {}
    for resp in (data.get("msgData") or {}).get("routeResps") or []:
        routes = resp.get("routes") or []
        for r in routes:   # 北京时间钟面，不做时区换算
            r["_time"] = datetime.strptime(r["acceptTime"], "%Y-%m-%d %H:%M:%S")
        result[resp["mailNo"]] = sorted(routes, key=lambda r: r["_time"], reverse=True)
    return result

if __name__ == "__main__":
    for no, routes in query_routes(["SF1011603494291"]).items():
        latest = routes[0] if routes else None
        print(no, latest and (latest["acceptTime"], latest["firstStatusName"], latest["remark"]))
```

### 5.2 curl（手工排查用）

```bash
# 1. 取令牌
curl -s -X POST https://sfapi-sbox.sf-express.com/oauth2/accessToken \
  -H 'Content-Type: application/x-www-form-urlencoded;charset=UTF-8' \
  --data-urlencode "partnerID=$SF_PARTNER_ID" \
  --data-urlencode "secret=$SF_CHECKWORD" \
  --data-urlencode "grantType=password"

# 2. 查路由（把上一步的 accessToken 填入 TOKEN）
curl -s -X POST https://sfapi-sbox.sf-express.com/std/service \
  -H 'Content-Type: application/x-www-form-urlencoded;charset=UTF-8' \
  --data-urlencode "partnerID=$SF_PARTNER_ID" \
  --data-urlencode "requestID=$(uuidgen)" \
  --data-urlencode "serviceCode=EXP_RECE_SEARCH_ROUTES" \
  --data-urlencode "timestamp=$(date +%s000)" \
  --data-urlencode "accessToken=$TOKEN" \
  --data-urlencode 'msgData={"language":"zh-CN","trackingType":"1","trackingNumber":["SF1011603494291"],"methodType":"1"}'
```

其他语言照第 3 节的协议实现即可：两个表单 POST，再加一次 JSON 字符串的二次解析。

## 6. 调用规范（共用额度，请遵守）

- **令牌要缓存**，不要每次查询都重新获取。
- **能批量就批量**：每次最多 10 个单号。
- **按状态控制频率**：在途的单 1~2 小时查一次就够了；已签收、已退回的单停止轮询；超过 3 个月的单停止轮询。
- **禁止压测**，也不要在沙箱里大量循环调用。
- **失败退避**：连续失败的单号要降低频率或暂停，不要死循环重试。
- **别把空路由当成功**：`routes` 为空时要记录原因（无权限、未揽收、超期），常见原因是非月结单漏传 `checkPhoneNo`。
- **隐私**：`remark` 中含快递员电话，`checkPhoneNo` 是客户手机号片段，只用于查询，不要外传。

## 7. 错误码速查

| 代码 | 含义 | 处理 |
|---|---|---|
| A1000 | 平台校验成功 | 继续看 `apiResultData.success` |
| A1001 | 必传参数为空 | 检查是否用了表单提交、字段名有没有空格、`msgData` 是否为合法 JSON |
| A1003 | IP 无效 | 应用设置了固定 IP，请求不是从该 IP 发出；联系负责人在丰桥应用详情里调整 |
| A1004 | 无服务权限 | 接口未上线却调了生产地址，或者已上线却还在调沙箱 |
| A1005 | 流量受控 | 超过 30 次/秒或 3000 次/天，降低频率 |
| A1006 | 数字签名无效 | 只出现在签名鉴权方式下；用本文的 OAuth2 方式不会遇到 |
| A1011 | OAuth2 认证失败 | 令牌过期就重新获取；如果是获取令牌本身失败，检查顾客编码、校验码，以及沙箱/生产是否用对 |
| A1009 / A1099 | 顺丰侧服务异常 | 稍后重试，持续出现在丰桥「在线报障」 |
| 8003 / 8004 | 单号超过 10 个 | 拆批 |
| 8013 | 未传查询单号 | 检查 `trackingNumber` |
| 6133 | 路由查询类别不合法 | `methodType` 只能传 1 或 2 |

## 8. 接入自检清单

- [ ] 已向负责人登记：应用名称、预计日调用量、用途
- [ ] 校验码放在环境变量或密钥管理中，代码和日志里搜不到
- [ ] 沙箱跑通：能拿到令牌，能解析出路由列表
- [ ] 令牌有缓存，遇到 A1011 会自动重取
- [ ] 按 `acceptTime` 排序后取最新节点，时间按北京时间处理
- [ ] 区分「接口失败」和「空路由」，空路由会记录原因
- [ ] 已签收、已退回的单停止轮询
- [ ] 确认丰桥上路由查询接口已上线后，再切 `SF_SANDBOX=false` 和生产校验码
