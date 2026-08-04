# 2026 采购节大屏 — 取数层与交付形态（2026-07-29）

> 规则本体见《2026-07-24-procurement-festival-dashboard.md》（v6，§2 已全清）。本文承接其排除的"取数方式"部分：双轨取数策略、lsordertest 保底 SQL 的修正与实测、user_rel_team 参数表、交付形态。

## 1. 双轨取数策略（2026-07-29 用户确定）

| 轨道 | 数据源 | 定位 |
|------|--------|------|
| 保底轨 | `lsordertest`（小满/OKKI 同步数据） | 兜底方案，SQL 已修正并实测（见 §3） |
| 主轨（备选） | 方舟平台订单发票数据（app/invoice 域） | 若 8 月方舟可正常使用则切换，取值更简单 |

实现时取数层做成可切换的 provider 接口，两轨输出同一套指标结构。

## 2. 参数表 `lsordertest.user_rel_team`（活动人员/阵营/目标唯一参数源）

列：`id`(自增), `Name`, `user_id`(=okki user_id), `En_name`, `Team`(分队), `Camp`(阵营), `gmv_t`(个人GMV目标), `newclient_t`(个人新签目标), created_at/updated_at。

- 2026-07-29 补录 4 名 2026 年入职业务员（此前 20 行 → 现 24 行全员）：刘也/Eva(57125949, 星星之火, 阵营一)、隋晓茹/Kara(57130433, 星星之火, 阵营一)、阿伍提凯丽比努尔/Katy(57130855, 乘风, 阵营三)、张心茹/Rina(57180994, 无名, 阵营一)。En_name 取自业务库 nickname。
- **newclient_t 已于 2026-07-29 全表重填**（D-2 裁决：旧值作废）：= 本人阵营门槛 × 属性（阵营一 6/4、二 7/5、三 9/7），与瓜分门槛同一套数；各阵营合计 42/52/66 与规则文档"全员踩线"结构观察吻合。**gmv_t 不用于本活动**（D-1 裁决），存量旧值不动。
- 24 行 Camp 与规则文档附录 B 逐人核对一致。
- 分队名正字（D-4 裁决）：**无名、稻乐偲、个人队**——表内"无名@"已订正为"无名"（2 行）；规则文档"稻乐俪"系笔误已订正为"稻乐偲"（C-7）。
- ⚠ 属性（分配/开发）不在此表，SQL 里现靠 `commission_db.employee_attribute_history is_current` 联查。规则要求属性全程固定（快照 2026-07-29），**建议实现时把附录 B 的属性快照落成常量或给本表加列**，避免活动中途 DB 属性被改导致积分漂移。

## 3. 保底轨取数 SQL（修正版，2026-07-29 实测通过）

用户原始 SQL 的**五处修正**（测试窗 2026-06-01~07-29 实测证据）：

| # | 问题 | 修正 | 证据 |
|---|------|------|------|
| 1 | **首返的邻接 LIKE 匹配不到任何行**：custom_fields 按 OKKI 字段序序列化为 `{新成交, 订单类型, 包邮, 首返, ...}`，"首返"与"订单类型"不相邻 | 拆成两个独立 LIKE | 邻接版 0 行 → 拆分版 15 行 |
| 2 | COUNT(*) 违反 A-4"同一客户只计一次" | `COUNT(DISTINCT company_id)` | 潘康衡测试窗 13 单/11 客户 |
| 3 | `SUM(a2.score)` 不可作为活动积分真相源 | 2026-08-04 更正：按资源来源字段 `45285192666116` 判定；公司分配=1，社媒开发/转介绍=1.5，不再使用人员属性 | 资源来源交叉验证 |
| 4 | 复购积分无取整、无 2025+ 客户池限制 | `FLOOR(SUM/1000)` + EXISTS(该客户存在 account_date≥2025-01-01 的新成交单) | EXISTS 使测试窗复购金额 $2,231,408 → $538,150 |
| 5 | departments 过滤会带进非参赛人员（如 57171776） | JOIN `user_rel_team` 限定 24 人名册 | 修正后无名册外人员 |

新成交/复购的邻接 LIKE（`"22595163468": "是/否", "691123983470": "定制品"`）**保留**——两字段在序列化中确实相邻，且与 `config/order_match_rules.yaml` 既有模式一致，测试窗分别取得 24/23 行。

```sql
-- 公共过滤（三条共用）：
--   AND a2.trail NOT LIKE '%个人%'
--   AND (a2.status = '13972831656' OR (a2.status = '13972831654' AND a2.status_name = '已结清'))
-- 参赛范围仅由 JOIN user_rel_team 名册限定；不再按 department_id 过滤（含嘉树）

-- ① 新签（窗口 2026-08-01 ~ 08-31）
SELECT t.user_id, t.Name, t.Camp,
       a2.company_id,
       a2.amount_usd,
       a2.custom_fields  -- 服务层按客户去重，对资源来源计 1/1.5 分
FROM lsordertest.okki_orders a2
JOIN lsordertest.user_rel_team t ON t.user_id = a2.user_id
WHERE a2.custom_fields LIKE '%"22595163468": "是", "691123983470": "定制品"%'
  AND a2.account_date BETWEEN '2026-08-01' AND '2026-08-31'
  AND <公共过滤>
;

-- ② 首返（窗口 2026-08-01 ~ 09-30；注意必须拆分 LIKE）
SELECT t.user_id, t.Name,
       COUNT(DISTINCT a2.company_id) AS 首返数,
       COUNT(DISTINCT a2.company_id) * 1.5 AS 首返积分
FROM lsordertest.okki_orders a2
JOIN lsordertest.user_rel_team t ON t.user_id = a2.user_id
WHERE a2.custom_fields LIKE '%"20528142733548": "是"%'
  AND a2.custom_fields LIKE '%"691123983470": "定制品"%'
  AND a2.account_date BETWEEN '2026-08-01' AND '2026-09-30'
  AND <公共过滤>
GROUP BY t.user_id, t.Name;

-- ③ 复购金额（窗口 2026-08-01 ~ 09-30；限 2025-01-01 起新签的客户；含首返单金额=A-6 叠加）
SELECT t.user_id, t.Name,
       SUM(a2.amount_usd) AS 复购金额,
       FLOOR(SUM(a2.amount_usd) / 1000) AS 复购积分
FROM lsordertest.okki_orders a2
JOIN lsordertest.user_rel_team t ON t.user_id = a2.user_id
WHERE a2.custom_fields LIKE '%"22595163468": "否", "691123983470": "定制品"%'
  AND a2.account_date BETWEEN '2026-08-01' AND '2026-09-30'
  AND <公共过滤>
  AND EXISTS (SELECT 1 FROM lsordertest.okki_orders o
              WHERE o.company_id = a2.company_id
                AND o.custom_fields LIKE '%"22595163468": "是"%'
                AND o.account_date >= '2025-01-01')
GROUP BY t.user_id, t.Name;
```

口径注：
- 复购①+② 总积分 = ②首返积分 + ③复购积分（③的金额含首返单本身 = A-6 叠加；FLOOR 按**人汇总后**取整，对业务员最有利且与 $2500=2 分示例一致）。
- ③ EXISTS 判定"2025+ 新签客户"只用新成交标记 + 日期，未附加定制品/状态/部门过滤（该单只是资格凭证不是计分单）——如需更严口径再收紧。
- 属性 LEFT JOIN 取不到时按分配类（×1）兜底；当前 24 人属性齐全。

## 4. 交付形态（2026-07-29 用户确定）

1. 数据大屏看板（方案评审后实现）；
2. **免登录局域网链接**——先例见 `frontend/public/caigoujie/`（192.168.101.193:8001/<slug>/，拷进 dist 即时生效），但本屏需要动态数据：大屏页静态托管 + 取数 API 走**免认证白名单端点**（硬约定 3 的机器对机器例外，需代码注释说明；建议限内网来源）；
3. **方舟平台导航入口**——navigation.js 加 entry，点击进入大屏页（登录态路径）。

## 4.5 大屏显示口径备忘（2026-07-30）

- **阵营积分榜成员芯片的"阵营第一"高亮 = 排除全司前三后的阵营内积分第一**（与 500 元奖评选口径一致，并列同标、名单置顶；2026-07-30 二次裁决，取代同日上午的"纯营内第一"口径）。为消歧义，**全司前三成员的芯片上叠加金色流光"全司前三"动效标识**——他们走的是前三奖，不参与阵营第一。
- 三营"已完成"合计可能 ≠ 顶栏 149 进度：阵营 done = Σ成员个人新签数（个人口径，同客户跨人各计），顶栏 = 全司客户去重（公司口径，A-4）。两数各自合规，现场被问按此备询。
- user_rel_team.Camp 为手工列：服务端 strip 归位 + 未知值计入 `unassigned` 上报（页面右上红色角标 + 日志），不静默丢人。

## 5. 待确认（2026-07-29 全部关闭）

| # | 裁决 |
|---|------|
| D-1 | ~~4 人目标值~~：**GMV 目标不需要**（gmv_t 不用于本活动）；新签目标按阵营门槛 × 属性填充，已落表。 |
| D-2 | ~~newclient_t 与门槛的关系~~：旧值作废，**全表重填为阵营门槛 × 属性**——个人新签目标与瓜分门槛就是同一套数（A-8 口径再次坐实）；大屏"达成个人新签目标"即按 newclient_t（=门槛）判定。 |
| D-3 | ~~score 列~~：**弃用**，不再进任何积分口径；2026-08-04 起新签积分一律按客户资源来源计算。 |
| D-4 | ~~分队名写法~~：正字 = **无名、稻乐偲、个人队**（表内"无名@"与文档"稻乐俪"均已订正）。 |

## 6. 主轨统计方案：基于 commission_db 发票域（2026-07-30 设计并当日实现）

> **三项裁决（2026-07-30 用户拍板）**：①金额口径 = **总金额扣手续费**（total_amount − surcharge_amount）；②统计范围 = **仅 sync_status='synced'**（已推 OKKI 的发票）；③切轨策略照 §6.3 执行（保底轨开赛 + 并跑对账，连续 3 天零差异切 ark）。
> **实现状态**：已落地——`Settings.FESTIVAL_DATA_SOURCE=okki|ark` 全局开关；六个取数函数双轨分发；全部大屏端点支持 `?source=` 调试覆盖；对账端点 `GET /api/public/festival/reconcile?key=`（按人三列 diff，差异行置顶，diff_count=0 即出"可切 ark"结论）；测试 20 个含主轨 3 项（仅 synced/扣手续费/客户池双通道）。

### 6.1 可行性实测（2026-07-30，窗口 6/1–7/29）

| 检查项 | 结果 | 结论 |
|--------|------|------|
| 名册 24 人 OKKI 绑定（ark_user_external_bindings） | **24/24 全绑定** | sales_user_id→okki user_id→user_rel_team 桥完整 ✓ |
| 三标记填充（okki_new_deal/first_return） | 12 张发票 0 个 NULL | 录入即有值，无需兜底推断 ✓ |
| 币种 | 全部 USD | 无汇率问题 ✓ |
| customer_id | = OKKI company_id（同 customer_info） | 客户去重/客户池口径与保底轨同源 ✓ |
| **窗口内覆盖率** | ark_invoices **12 张** vs okki_orders **1414 单** | **⚠ 核心风险：主轨成立的硬前提是 8 月起全部订单走方舟录入** |

### 6.2 口径映射（保底轨 → 主轨）

| 指标 | 保底轨（lsordertest.okki_orders） | 主轨（commission_db.ark_invoices） |
|------|------|------|
| 时间归属 | account_date | **invoice_date**（推单时它就是 account_date 的来源，天然同口径） |
| 定制品过滤 | custom_fields 邻接 LIKE（保留） | **不过滤**（2026-07-30 裁决：方舟"生产订单/库存单"与小满"定制品"不是一个概念，主轨全量发票计入）——两轨口径差**保持现状**（同日二次裁决选项2）：推成"规格品"的发票主轨计、保底轨不计，对账时此类差异属**正常预期**，人工识别后忽略，只盯其余差异；"连续 3 天零差异"判据相应放宽为"连续 3 天无规格品之外的差异" |
| 新签 | 新成交"是"+定制品，COUNT(DISTINCT company_id) | okki_new_deal=1，COUNT(DISTINCT customer_id)；NULL 兜底复刻推单逻辑（跨库查该客户无 okki 历史单） |
| 新签积分 | 读 custom_fields 资源来源：公司分配=1，社媒开发/转介绍=1.5 | 通过 xiaoman_order_id 精确回查当前小满订单来源；不用客户历史来源替代当前单；同步延迟暂无来源时按公司分配 1 分兜底 |
| 首返 | 首返"是"拆分 LIKE | okki_first_return=1 |
| 复购金额 | 新成交"否"+定制品+客户池 EXISTS | okki_new_deal=0 + 客户池 = EXISTS(lsordertest 2025+新成交) **OR** EXISTS(ark_invoices okki_new_deal=1 且 invoice_date≥2025)——历史判定仍跨库（同 RDS 零成本），未来纯方舟时代自洽 |
| 业务员归属 | okki_orders.user_id | sales_user_id → ark_user_external_bindings(provider=okki) → user_rel_team |
| GMV | SUM(amount_usd) 全订单类型 | SUM(total_amount) 全 order_type——**决策点①：total_amount 含运费/包装费/手续费，product_amount 是行净额，用哪个** |
| 大单事件 | amount_usd ≥5000，dedup deal:{order_id} | total_amount ≥5000，dedup 优先 deal:{xiaoman_order_id}（与保底轨天然同键，切轨不重报），未推单用 deal:ark:{invoice_no} |
| trail 排除"个人" | NOT LIKE '%个人%' | 无对应概念（发票均为公司业务，天然干净）——差异点知悉 |
| 统计范围 | 状态 13972831656 或 已结清 | **决策点②：建议 status≠draft 的全部发票（录入即上屏，不等推单成功——这是主轨"更快"的价值）；发票删除机制需确认（无软删列）** |

### 6.3 切换与对账设计

- **provider 开关**：Settings 加 `FESTIVAL_DATA_SOURCE=okki|ark`（默认 okki）；service 层六个取数函数（新签榜/复购统计/GMV/公司去重/大单扫描/首单）各出 ark 实现同签名，`_windows` 之上按开关分发；调试可用 `?source=` 参数临时指定。
- **事件留档兼容**：进榜/达标类 dedup_key 已是业务语义键（user_id/阵营名），轨道无关；仅 deal 键按上表规则对齐，**切轨不产生重复弹窗**。
- **并跑对账**：内部端点 `/api/public/festival/reconcile?key=`——两轨按人输出新签数/首返数/复购金额三列 diff；8 月第一周每日人工看一次（或接钉钉），差异来源只有两种：没走方舟录入的单、未推单的滞后。**差异连续 3 天为 0 → 正式切 ark**。
- **切轨纪律**：赛中切轨只影响取数源不影响已留档事件；建议在自然日 0 点切，避免当日榜单口径混合。

### 6.4 实施步骤（待确认后执行，估算 1 天内）

1. 决策点①②拍板 + 「全员方舟录单」运营纪律确认（8/1 生效）；
2. service 层 ark provider 六函数 + Settings 开关 + 单测（复用现有 conftest，ark_invoices 走 Base.metadata 建表零额外 infra）；
3. reconcile 对账端点 + runbook 操作项；
4. 8/1 起 okki 轨开赛 + ark 并跑对账 → 达标后切换（或运营拍板直接 ark 起步）。
