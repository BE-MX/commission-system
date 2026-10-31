# 色板数据库重构：公库 / 私库 + 色差仪测量

> 日期：2026-10-27 · 状态：设计稿（未开发） · 原型：[prototype.html](prototype.html)
> 协议依据：`D:\色差仪\LSColor蓝牙连接与数据读写控制技术说明.md`（v1.0，下称“协议说明”）

## 1. 目标与边界

| 项 | 本期做 | 本期不做 |
| --- | --- | --- |
| 库结构 | 公库（公司标准色）+ 业务员私库（必须绑定客户） | 跨客户共享私库 |
| 色板 | 色号 + 尺寸为必填属性，同客户下“色号+尺寸”唯一 | 色板图 AI 生成改造（沿用现有） |
| 测量 | Web Bluetooth 连接 LS 色差仪，一个色板多组测量，读取 Lab/Luv/LCh/Yxy/CMYK/RGB | 校准指令、实体键自动入库（协议说明 6.3/6.4 未确认） |
| 计算 | 平均 Lab、组内平均 ΔE / 最大 ΔE、与公库基准的 ΔE | 合格判定自动通知客户 |

核心判断：**设备只给原始测量，ΔE 一律在平台计算**（协议说明 6.2：原厂标准/样品测量发的是同一条 44 指令）。所以“原始测量”和“统计计算”分两层存，平均值永远可由原始记录重算。

## 2. 信息架构

```
发色数字化
└─ 色板数据库
   ├─ 公库            全员只读；色彩管理员维护；可作为私库基准色
   └─ 我的私库        按客户分组；业务员仅见自己（主负责人/协作人）客户的色板
       └─ 客户 A
           └─ 色板 #1C · 18"   ← 基准：公库 #1C
               ├─ 测量组 1  L/a/b …  ΔE→均值 0.32
               ├─ 测量组 2  …
               └─ 统计：平均 Lab / 平均 ΔE / 最大 ΔE / 与基准 ΔE
```

- **公库**：现有 `ark_color_palette`、`ark_color_blend` 即公库，不迁表；新增“公库色板实物”（带尺寸、可测量）使用同一张色板表，`library_scope='public'`。
- **私库**：`library_scope='private'`，必须有 `customer_id`（`ark_customer_accounts.id`）。
- **可见性**：私库按 `ark_customer_assignments` 当前有效归属（primary / collaborator）实时判定，客户转交后新负责人自动可见、原负责人自动不可见；不在色板上冗余“可见人列表”。`owner_user_id` 只记录创建人，不参与授权。
- **晋升**：私库色板可“申请纳入公库”，管理员审核后复制为公库色板（保留来源 id），私库原记录不动。

## 3. 数据模型（新增 3 表，迁移编号开发时查全部分支后再定）

### 3.1 `ark_color_swatch` 色板

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | BIGINT PK | |
| library_scope | VARCHAR(16) | `public` / `private` |
| customer_id | BIGINT NULL FK | 私库必填，公库必空（CHECK 约束） |
| owner_user_id | USER_ID | 创建人 |
| color_code | VARCHAR(30) | 色号，如 `#1C`、`#8/60`、客户自定义 `CUST-ASH-02` |
| size_value | DECIMAL(5,1) | 尺寸数值，如 18 |
| size_unit | VARCHAR(8) | `inch` / `cm`，默认 inch |
| display_name | VARCHAR(100) NULL | 展示名 |
| base_palette_id / base_blend_id | INT NULL | 关联公库基准色（二选一可空） |
| base_swatch_id | BIGINT NULL | 关联公库色板实物（有测量值时优先作为基准） |
| tolerance_de | DECIMAL(4,2) | 允许色差阈值，默认 1.50（ΔE00） |
| stat_count / stat_lab_l/a/b / stat_mean_de / stat_max_de / stat_base_de | 冗余统计 | 由测量记录重算写入，列表页直接读 |
| record_status | VARCHAR(16) | `active` / `archived` |
| promoted_from_id | BIGINT NULL | 公库色板由哪条私库晋升 |
| created_at / updated_at | DATETIME | `beijing_now` |

唯一键：`(library_scope, customer_id, color_code, size_value, size_unit)`（公库 customer_id 用生成列归一为 0 防 NULL 不唯一）。

### 3.2 `ark_color_swatch_measurement` 测量组（一行 = 一次设备返回的 44 帧）

| 字段 | 说明 |
| --- | --- |
| swatch_id | 所属色板 |
| seq_no | 色板内序号（显示“第 N 组”） |
| lab_l / lab_a / lab_b | `int16LE/100`，协议说明 8.2 字节 8–13 |
| luv_l/u/v、lch_l/c/h、yxy_y/x/y | 全量保存；x/y 为 `/10000`；h 保留原 App 特殊符号规则（8.3） |
| cmyk_c/m/y/k、rgb_r/g/b | `uint8` 原值，不缩放 |
| raw_hex | 完整 CRC 有效帧 HEX，可追溯重解析 |
| device_name / device_sn / device_fw | SN 来自设备信息帧（9.1），**不是** MAC 或浏览器 device.id |
| session_id | 一次蓝牙连接会话 UUID |
| requested_at / received_at | 发 44 指令时间、收到帧时间 |
| receipt_status | `matched`=8 s 内匹配；`late`=超时后到达，进待确认区；`manual`=手工录入 |
| is_included | 是否参与平均（可剔除异常组，需填原因） |
| exclude_reason | |
| client_request_id | 前端生成的幂等键，防止网络重试重复入库 |
| measured_by | 操作人 |

### 3.3 `ark_color_swatch_event` 审计
记录：新建、改尺寸/色号、剔除/恢复测量组、改基准、晋升申请/通过。测量值本身不可修改，只能剔除。

## 4. 计算口径

| 指标 | 公式 | 备注 |
| --- | --- | --- |
| 平均 Lab | 参与组 L、a、b 分别算术平均 | 至少 1 组 |
| 组内平均 ΔE | `mean(ΔE00(Labᵢ, 平均Lab))` | 至少 2 组才显示；衡量测量一致性/色板均匀度 |
| 组内最大 ΔE | `max(ΔE00(Labᵢ, 平均Lab))` | 定位离群组 |
| 与基准 ΔE | `ΔE00(平均Lab, 基准Lab)` | 基准优先取公库色板实测平均，其次公库色号 Lab |
| 平均 RGB / CMYK | 各通道算术平均后取整 | **仅作预览**，界面标注“设备换算值”，不参与判定（协议说明 8.2 末段） |
| 判定 | 与基准 ΔE ≤ tolerance 为“符合”，否则“偏差” | 组内平均 ΔE > 0.8 时提示“建议加测” |

默认 ΔE00，同时保留 ΔE76 切换（老客户报告口径）。所有统计在后端 service 重算，前端算值只用于即时预览。

## 5. 色差仪接入设计（严格按协议说明）

### 5.1 连接状态机（界面四段，不合并成一个“已连接”）

```
未连接 → GATT 已连 → 通知已开 → 初始化已确认 → 可测量
                                    ↑ 设备信息/电压失败时停在“通知已开”，允许测量但显示提示
```

| 步骤 | 实现 |
| --- | --- |
| 选择设备 | 用户点击触发 `requestDevice({filters:[{namePrefix:'LS'}], optionalServices:[0xffe0,0xffe5,0xfff0,0x1001]})` |
| 选通道 | 按 A(FFE0/FFE4 + FFE5/FFE9) → B(FFF0/FFF1) → C(1001/1002) 检查服务、特征、notify/write 属性 |
| 通知 | 先注册 `characteristicvaluechanged` 再 `startNotifications()` |
| 初始化 | 串行发 `AB2005001200946B`（设备信息→SN/物料/版本）、`AB200B0002009B43`（电压，`uint16LE/10` V，只显示 V） |
| 测量 | 发 `AB440000000036001864`，等待前缀 `AB4400000000` 且 CRC-16/MODBUS 通过的帧 |

### 5.2 测量与入库规则
- 指令队列串行、单 pending、**8 s 超时不自动重发**。
- 点“测量”时快照 `swatch_id`，防止等待期间切换色板造成错配。
- 超时后才到达的 44 帧 → `receipt_status=late`，放入“待确认读数”，由用户指定归属色板或丢弃，**不自动计入平均**。
- 一次测量返回后立即预览，用户可“连续测量 N 组”（默认 3 组，组间等待上次返回再发，不并发）。
- A0 事件 / 40 帧只写诊断日志，不入库（协议说明 6.4）。
- 断线：拒绝 pending、清空组帧缓存、移除监听；已入库数据不受影响；重连需重新选择设备。

### 5.3 运行环境
- 首版支持：安卓 Chrome（协议说明 12.1 已验证 API 存在）；桌面 Chrome/Edge 的 Web Bluetooth 需实物验证后再对业务开放。
- 微信/钉钉内置浏览器、iOS 不支持：页面检测 `isSecureContext && navigator.bluetooth`，不满足时测量按钮禁用并提示“请用安卓 Chrome 打开”，仍可查看和手工录入。
- 生产必须 HTTPS。

### 5.4 前端模块划分
```
frontend/src/services/colorimeter/
  protocol.js     PROFILES / COMMANDS / crc16 / FrameStream / decodeMeasurement / decodeInfo
  device.js       connect / enqueue / measure / disconnect，事件：state / reading / late / log
  deltaE.js       ΔE00 / ΔE76 / 平均
frontend/src/views/color/swatch-library/
  SwatchLibrary.vue        公库/私库切换 + 客户侧栏 + 色板网格
  SwatchDetailDrawer.vue   色板详情 + 测量面板
  MeasurePanel.vue         设备状态、测量按钮、读数表、统计
```
协议层与 `D:\色差仪\demo\protocol.mjs` 同口径移植并带离线单测（CRC 7 条固定帧、负 a/b、byteOffset 切片、分片拼接）。

## 6. API

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/color/swatches?scope=public\|private&customer_id=&keyword=&status=` | 分页，私库自动按归属过滤 |
| POST | `/api/color/swatches` | 新建；私库校验当前用户对 customer_id 有有效归属 |
| GET/PATCH | `/api/color/swatches/{id}` | 详情（含测量组、统计）/ 改名、尺寸、基准、阈值 |
| POST | `/api/color/swatches/{id}/measurements` | 批量写入测量组，带 `client_request_id` 幂等 |
| PATCH | `/api/color/swatches/{id}/measurements/{mid}` | 剔除/恢复（`is_included` + 原因） |
| POST | `/api/color/swatches/{id}/promote` | 申请纳入公库 |
| GET | `/api/color/customers/mine` | 我的客户（带私库色板数），供侧栏 |

权限：`color:read`（公库只读，沿用）、`color:swatch:private`（私库读写）、`color:swatch:public`（公库维护、审核晋升）。

## 7. 验收

1. 业务员 A 看不到业务员 B 客户的私库；客户转交后可见性随之变化（接口级测试）。
2. 同客户“#1C·18 inch”重复创建被拒；“#1C·20 inch”可建。
3. 协议单测：7 条固定帧 CRC、负 a/b 解析、x/y 除 10000、byteOffset 切片。
4. 统计：3 组已知 Lab 的平均与 ΔE00 与参考实现误差 < 0.01；剔除一组后统计重算。
5. 超时晚到帧进入待确认，不计入平均。
6. **实物验收**（协议说明 14.3）：固定一台仪器，记录型号/SN/固件，网页测量多组（含负 a/b 样品），与原厂 App 数值对照。**未完成实物验收前，测量功能只能标记为 Beta。**

## 8. 风险

| 风险 | 处理 |
| --- | --- |
| 尚无实物连接成功证据 | 第一周先做实物联调，原型阶段即可用模拟模式 |
| 44 帧长度/尾部未确认 | 用 CRC 边界搜索 + raw_hex 全量保存，确认后可离线重解析 |
| 无事务编号，晚到帧可能错配 | 快照色板 + late 状态人工确认 |
| 光源/观察者角度未知 | 测量记录存 device_sn + 固件；跨设备比较时界面提示 |
