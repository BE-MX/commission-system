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
| 3 | `SUM(a2.score)` 与 A-15"积分跟人不跟单"冲突：score 列跟单型（分配类的人有 20 单 score=1.5） | 按人属性 `CASE eah.attribute_type WHEN 'develop' THEN 1.5 ELSE 1 END × 新签数` | score×属性交叉验证表 |
| 4 | 复购积分无取整、无 2025+ 客户池限制 | `FLOOR(SUM/1000)` + EXISTS(该客户存在 account_date≥2025-01-01 的新成交单) | EXISTS 使测试窗复购金额 $2,231,408 → $538,150 |
| 5 | departments 过滤会带进非参赛人员（如 57171776） | JOIN `user_rel_team` 限定 24 人名册 | 修正后无名册外人员 |

新成交/复购的邻接 LIKE（`"22595163468": "是/否", "691123983470": "定制品"`）**保留**——两字段在序列化中确实相邻，且与 `config/order_match_rules.yaml` 既有模式一致，测试窗分别取得 24/23 行。

```sql
-- 公共过滤（三条共用）：
--   AND a2.trail NOT LIKE '%个人%'
--   AND (a2.status = '13972831656' OR (a2.status = '13972831654' AND a2.status_name = '已结清'))
--   AND (departments LIKE 7 个 department_id 之一)   -- 24925/24926/25198/258938/258940/258941/258942

-- ① 新签（窗口 2026-08-01 ~ 08-31）
SELECT t.user_id, t.Name, t.Camp,
       COUNT(DISTINCT a2.company_id) AS 新签数,
       COUNT(DISTINCT a2.company_id)
         * CASE eah.attribute_type WHEN 'develop' THEN 1.5 ELSE 1 END AS 新签积分
FROM lsordertest.okki_orders a2
JOIN lsordertest.user_rel_team t ON t.user_id = a2.user_id
LEFT JOIN commission_db.employee_attribute_history eah
       ON eah.employee_id = a2.user_id AND eah.is_current = 1
WHERE a2.custom_fields LIKE '%"22595163468": "是", "691123983470": "定制品"%'
  AND a2.account_date BETWEEN '2026-08-01' AND '2026-08-31'
  AND <公共过滤>
GROUP BY t.user_id, t.Name, t.Camp, eah.attribute_type;

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

## 5. 待确认（2026-07-29 全部关闭）

| # | 裁决 |
|---|------|
| D-1 | ~~4 人目标值~~：**GMV 目标不需要**（gmv_t 不用于本活动）；新签目标按阵营门槛 × 属性填充，已落表。 |
| D-2 | ~~newclient_t 与门槛的关系~~：旧值作废，**全表重填为阵营门槛 × 属性**——个人新签目标与瓜分门槛就是同一套数（A-8 口径再次坐实）；大屏"达成个人新签目标"即按 newclient_t（=门槛）判定。 |
| D-3 | ~~score 列~~：**弃用**，不再进任何积分口径；新签积分一律按人属性计算。 |
| D-4 | ~~分队名写法~~：正字 = **无名、稻乐偲、个人队**（表内"无名@"与文档"稻乐俪"均已订正）。 |
