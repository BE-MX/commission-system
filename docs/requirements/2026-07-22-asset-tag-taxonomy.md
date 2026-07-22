# 素材库标签体系重构方案 v2

日期：2026-07-22 ｜ 状态：设计稿待确认（已过对抗性审查并修订）｜ 模块：asset（素材中台）

## 一、问题诊断（基于真实数据，2026-07-22 生产库快照）

### 现状

素材库 12,277 个素材（11,080 图 / 1,197 视频），当前 5 个维度（机器名：asset_type / asset_type_2 / color / others / year）：

| 维度 | 值数量 | 问题 |
|------|--------|------|
| 素材类型 (asset_type) | 8 | 「类型」实际是 内容×媒体格式 的叉积（产品图片/产品视频） |
| 素材子类 (asset_type_2) | 22 | 与素材类型无挂靠关系，任意组合 |
| 颜色标签 (color) | 107 | 格式脏乱：`#P1B-2` vs `#P1B--2B`、`#Cookie cream` vs `#Cookie Cream`、`半片PU卡子发-#2`（产品+颜色混写） |
| 综合标签 (others) | 275 | **大杂烩**：产品类型、活动名、工艺步骤、纹理、画幅、压缩状态、节日混装；**约 160 个值使用量为 0**（文件夹名直接灌成标签） |
| 年份 (year) | 5 | 干净可用，沿用 |

### 根因

标签体系不是设计出来的，是**文件夹路径逐层平移**出来的（folder_upload 路径提取机制）。文件夹是给人浏览的单一层级结构，标签是给检索用的多维正交结构——平移必乱。

### 连带损伤（已实锤）

AI 打标签实质失效：`asset_analyze` preset（存于 AI preset 表，由 seed_ai.py 播种，`analyze_service.py` 里的同名常量是死代码）仍是早期 9 维度体系（产品线/长度/克重/市场地区…），与库中实际维度对不上；响应解析侧 `_DIMENSION_MAP` 同样硬编码老维度。教训：**值域硬编码在 prompt / 代码里，标签体系一变就静默失效**。

### 设计部新版（Excel「加程整理」sheet）评估

进步：拆出了产品类型(34)、工艺流程(23)、拍摄风格(3)。
仍存在的问题：
1. 综合标签仍是杂烩（纹理/节日/规格/画幅/压缩/字幕 ≥6 个独立面混装）
2. 颜色仍是 120 个平铺值，重复未清（`#2TP2-6`、`#5AT60` 各出现两次），还混入「产品合集」
3. 工艺流程用 `01-`~`13-` 前缀在标签名里编码顺序（系统有 sort_order，不需要）
4. 素材类型仍混媒体格式（file_type 字段已记录 image/video）
5. 无英文名/别名——外部 agent 用英文查询无法命中

## 二、设计原则（第一性原理）

标签存在的唯一目的是**检索**——人检索 + agent 检索：

1. **一个维度只回答一个问题**（正交性）。agent 组合过滤的前提。
2. **受控词表**。值域封闭、去重、格式规范；新值需管理员添加。
3. **机器可读**。维度用稳定英文 name，值带英文别名（外贸 agent 大概率收到英文需求：Genius Weft / Tape-in / Clip-in）。
4. **能自动的不手动**。画幅从宽高算、色系从色号推、媒体格式用 file_type——不进人工标签。

## 三、新标签体系（11 个维度）

### 维度总表

新维度 name 需避开已占用的 `asset_type / asset_type_2 / color / others / year`（`idx_tag_dim_name` 唯一索引）。年份维度**直接沿用现有 year 维度**，不新建。

| # | name | 中文 | 单/多选 | 必填* | 值来源 |
|---|------|------|---------|-------|--------|
| 1 | content_category | 内容大类 | 单 | ✅ | 5 值 |
| 2 | content_type | 内容子类 | 单 | ✅ | ~30 值，挂靠大类 |
| 3 | product_type | 产品类型 | 多 | 产品类必填 | 设计部 34 值规范化 + 英文别名 |
| 4 | color_code | 色号 | 多 | 否 | 规范化格式，对齐 ark_color_palette |
| 5 | color_family | 色系 | 多 | 系统托管 | 从色号推导，禁人工编辑 |
| 6 | texture | 纹理造型 | 多 | 否 | 直发/自然曲/Body Wave/Curly/Deep Wave |
| 7 | shoot_style | 拍摄风格 | 单 | 否 | 白底/INS风/库存间实拍/模特佩戴/手持/细节特写/AI生成 |
| 8 | process_step | 工艺环节 | 单 | 否 | 14 步，去序号前缀（sort_order 排序） |
| 9 | theme | 节日/营销主题 | 单 | 否 | 12 节日 + 新贸节/采购节 + 夏日/熊猫等风格主题 |
| 10 | year（沿用） | 年份 | 单 | ✅ | 现有 5 值 |
| 11 | media_trait | 媒体特性 | 多 | 否 | 带字幕/带水印/未压缩原片（横竖版走 orientation 字段） |

*必填的生效时机：新维度种子落库时 is_required 一律为 0（否则上传表单当场被卡），**前端切换日**才把三个必填维度置 1。

### 内容大类 → 内容子类（级联）

- **产品素材**：产品展示 / 细节图 / 产品对比 / 佩戴效果 / 产品合集 / 清洗测试 / 色板色卡 / 包装配件 / 原材料说明
- **生产工艺**：工艺流程记录 / 质检包装
- **公司实力**：工厂环境 / 门头厂房 / 公司宣传片 / 证书资质
- **公司活动**：年会 / 启动会 / 复盘总结会 / 团建聚餐 / 节日福利 / 班会培训 / 其他活动
- **营销设计**：详情页 / 问候图 / 节日海报 / 倒计时物料 / 内容号 / 优势图 / AI效果图 / 其他设计

旧综合标签的六类杂物各归其位：
- 「年会/启动会/复盘会/团建」→ 内容子类。不再为每场活动建标签——**年份 + 子类已足够检索**，确需场次名写 asset.remark（旧库 160 个零使用场次标签证明没人用它检索）
- 「11-跑帘子/06-漂染」→ process_step；「11-天才制作」类产品专属步骤 = process_step:成品制作 + product_type:天才发帘 两维组合，不造叉积值
- 「横版/竖版」→ orientation 字段（自动）；「已压缩/加字幕」→ media_trait
- 「天才发帘/贴发/接发」→ product_type；「INS风格/白底图」→ shoot_style

product_type 与 content_type 存在「色板/包装」语义重叠，在 list_asset_taxonomy 的维度描述里写清边界：content_type 回答「这张素材拍的是什么」，product_type 回答「涉及哪个产品」。

### 产品类型规范值（示例，最终以设计部确认为准）

| 规范中文名 | 英文别名（agent 检索用） |
|-----------|------------------------|
| 天才发帘 | Genius Weft |
| 双层天才 / 加丝天才 | Double Drawn / Silk Genius Weft |
| 机织发帘 | Machine Weft |
| 鱼线发帘 | Halo / Fish Line |
| 打孔发帘-天才+天才 / 天才+PU / 机织+PU / 机织+机织 | Hole Weft (…) |
| 普通贴发 / 机织贴发 / 双层贴发 / 迷你贴发 / 机织长条贴发 | Tape-in 系列 |
| 平型 / 迷你平型 | Flat Tip / Mini Flat Tip |
| 棒棒 / 迷你哑光棒棒 | I-Tip / Mini Matte I-Tip |
| 铁丝 | Nano Ring |
| Y-tip / 指甲 | Y-Tip / U-Tip (Nail) |
| 塑料头接发 / 尼龙绳接发 / 羽毛接发 / 拉环双头接发 | Plastic Tip / Nylon Loop / Feather / Pull-Loop |
| 普通卡子发 / 机织卡子发 / 半片PU卡子发 / 蕾丝卡子发 | Clip-in (…) |
| 多品类 / 色板 / 包装 / 配件工具 | Multi-Category / Color Ring / Packaging / Tools |

### 色号规范化规则

- 统一格式：`#` + 大写代码，单连字符，无空格：`#P1B-2B`、`#5ATP18B-62`；混色比例半角冒号 `#M9A-60(8:2)`；英文色 Title Case
- 产品+色号混写值拆开：`半片PU卡子发-#2` → product_type:半片PU卡子发 + color_code:#2（映射表支持 1→N）
- **权威源对齐 ark_color_palette**，但需先解决三件事：①格式互转（palette 存在 `#1C/18` 斜杠格式，与标签规范不同，需转换表）；②color_family 枚举以 palette 实际值为准：`black/brown/blonde/red/silver/vibrant`；③palette 仅 12 基础色，覆盖不了 107 存量色号——未命中的按前缀规则推导（`P`→piano 挑染、`T`→ombre 渐变、`TP`→双段渐变、`M`→mixed 混色），仍无法归类的落 `vibrant`。同步机制：色板库新增色号时由管理员在标签管理页一键同步（不做自动定时，12 值规模不值得）
- color_family 维度加**系统托管标记**（is_managed），标签管理页与编辑接口禁止人工增删改，由推导脚本独占写入

## 四、系统改动

### 4.1 Schema（Alembic 迁移，兼容过渡期，全部 nullable/带默认值）

- `ark_tag_dimensions` 加 2 列：`is_visible`（0/1，前端与 folder_upload 匹配是否可见——**旧维度退役的执行机制**）、`is_managed`（系统托管，禁人工编辑值）
- `ark_tag_values` 加 3 列：`name_en` VARCHAR(128)、`aliases` JSON、`parent_value_id` INT NULL（自引用 FK，删除值时校验无子级——`delete_dimension_value` 补 children 检查）
- `ark_assets` 加 1 列：`orientation` VARCHAR(16)（landscape/portrait/square）

### 4.2 打标签写入口修复（对抗审查发现的关键窗口）

| 写入口 | 现状问题 | 修法 |
|--------|----------|------|
| AI 建议（asset_analyze preset） | prompt 在 **DB preset 表**里（seed_ai.py 播种、同名跳过），只改 analyze_service.py 无效 | preset 的 system prompt 改为通用角色说明；**维度与值域运行时注入 user message**（list_dimensions_cached 已有缓存）；`_DIMENSION_MAP`/建议组装动态化；seed_ai.py 与生产库现存 preset 行同步更新 |
| folder_upload 校验 | `validate_folder_tags` 对**全部维度**做文本匹配，并存期同名值（「2024」「白底图」「天才发帘」新旧各一份）全部变歧义，上传瘫痪 | 匹配范围限定 `is_visible=1` 的维度 |
| folder_upload 合并判定 | `_tags_match` 比较全量标签集合，迁移追加新标签后集合必不等 → **重传同一文件夹会批量造重复素材** | 合并口径改为 (file_name, file_type) 命中 + 仅比较可见维度的标签 |
| 手工编辑标签 | `update_asset_tags` 全删全写（`_clear_tags` 删素材**所有维度**行），并存期用户一次保存就抹掉迁移成果 | PATCH 语义改为**按维度合并**（只覆盖请求中出现的维度）；这同时是旧维度「保留两周可回退」的前提 |
| 单选约束 | `_apply_tags` 不校验单选，多值静默写入 | service 层加单选校验（超一值报 400） |
| DEFAULT_DIMENSIONS 种子 | tag_service.py 仍是 9 维老体系，新环境/测试库初始化出第三套体系 | 替换为新 11 维种子 |

### 4.3 Agent 调用接口（本次需求的核心目标）

在既有 MCP 网关（app/mcp）新增素材域工具：

- `search_assets(content_category?, content_type?, product_type?, color_code?, color_family?, texture?, shoot_style?, theme?, year?, orientation?, media_trait?, keyword?, limit?)`
  - 参数用**自由字符串 + 运行时解析**，不做静态 enum（FastMCP 工具在启动时注册 schema，动态枚举实为「启动时快照」，新增标签值即失效；百值色号塞 enum 也会让 schema 膨胀）。解析时 value / name_en / aliases 三路匹配，Python 侧大小写归一；解析失败返回错误并附最相近候选
  - **必须复算 AssetPermission 数据范围**（permission_group / specified_user_ids / allow_preview）——现 `query_assets` 不过滤权限，Web 端靠前端处理 can_preview，MCP 直接复用会把受限素材的元数据和签名 URL 泄给任意持 token 的 agent
  - 返回签名下载 URL（复用 share-link 签名机制），MCP 场景有效期放宽（agent 异步消费，2 小时偏短）
- `list_asset_taxonomy()`——返回全部可见维度与值域（含英文别名、维度用法描述），agent 先发现词表再检索

### 4.4 前端

- 筛选面板只渲染 `is_visible=1` 维度；**分组渐进展示**：常用组（内容大类/子类/产品类型/色系）默认展开，高级组（色号/纹理/风格/工艺/主题/特性）折叠——11 维不能平铺甩给用户
- 色号筛选先按 color_family 收窄再展开具体色号
- 内容大类→子类级联（parent_value_id）
- TagDimensionManage 支持编辑 name_en / aliases / parent，托管维度只读
- `/m/` 移动端同步适配（chips 按可见维度渲染 + localStorage 缓存键 `m_tag_dimensions` 失效处理 + 色号 bottom-sheet 加搜索）
- 下载动态命名：单文件 Content-Disposition 按标签生成友好名（`天才发帘_#8TP8-18_白底图_048A9972.jpg`）；顺手修 batch_download 裸 f-string 中文名的 latin-1 问题

## 五、存量 12,277 素材重打标签方案

核心判断：旧标签就是文件夹路径的忠实记录，**~95% 的迁移是确定性映射，不需要 AI 看图**。

### 管道分三层

**第 1 层：确定性映射（零 AI 成本）**

「旧值 → 新维度+新值」映射表（脚本生成 Excel 给设计部确认后回灌执行；模板支持 1→N 拆分与 N→1 合并）：
- 素材类型 + 素材子类 → content_category + content_type
- 综合标签有使用量的 115 值 → product_type / content_type / process_step / theme / shoot_style / media_trait；零使用值执行时**重验使用量**后弃（映射表基于快照，确认周期内可能有新上传）
- 颜色 107 值 → 规范化色号；年份沿用不动

执行脚本要点：
- 执行时以**库内实时数据**重新拉取旧标签关联，不用快照
- 写入用 INSERT IGNORE（复合主键 (asset_id, dimension_id, tag_value_id)，裸 INSERT 重跑会全量撞 PK——幂等靠这个，不是「天然」的）
- 分批 + savepoint 隔离单条失败（硬约定 6）
- **单选冲突裁决**：素材子类与综合标签双源汇流到 content_type 会产出多值。规则：素材子类映射优先，综合标签映射降级为次选；仍冲突的进人工待审清单。验收硬指标：单选维度多值数 = 0
- **必填兜底**：year 缺失用 created_at 年份回填；content_category 无法映射的进人工待审清单，验收标准为「必填缺失清单 = 已审明细」

**第 2 层：规则计算（零 AI 成本）**

- orientation 回填：图片 PIL 读宽高；**视频用 OpenCV 读首帧**（缩略图管线已依赖 cv2）；新版本上传替换文件时重算
- color_family：从规范化色号推导（规则见三）

**第 3 层：AI 视觉补标（可选，建议二期）**

产品图的 texture / shoot_style 细分约 5,000 张，走 `app.ai.service.chat` 多模态（缩略图降成本），置信度 ≥0.7 写入，低置信进待审队列。**一期不做**：旧文件夹层级里没有纹理信息 = 业务此前没按纹理检索过，需求真伪先用两周检索日志验证。

### 并存期运行时行为矩阵

| 写入口 | 阶段A 并存（新维度 is_visible=0） | 阶段B 切换（新可见/旧隐藏，必填生效） | 阶段C 退役（删旧维度） |
|--------|----------------------------------|--------------------------------------|------------------------|
| 单文件上传 | 照旧（新维度不可见不必填） | 走新维度表单 | 不变 |
| folder_upload | 只匹配可见维度=旧体系，行为不变 | 只匹配新体系；合并判定已改 file_name 口径 | 不变 |
| AI 建议 | 注入可见维度=旧体系（仍可用） | 注入新体系 | 不变 |
| 手工编辑 | 按维度合并语义，不再误删对方体系 | 同左（旧标签行保留=可回退） | 旧行随维度清除 |
| 迁移脚本 | 本阶段执行（写不可见的新维度） | 切换前重跑一遍兜底增量 | — |

### 验收与切换

1. 迁移前备份 `ark_asset_tags`（CREATE TABLE ... SELECT）
2. 覆盖率报告：每新维度覆盖数对照旧维度、单选多值=0、必填缺失=已审明细
3. 随机 300 张设计部抽检 → 通过后执行切换（is_visible 翻转 + is_required 生效 + 切换前重跑增量迁移）
4. 观察两周 → 退役迁移删除旧维度（顺序：ark_asset_tags → ark_tag_values → ark_tag_dimensions，删前再备份；`delete_dimension` 接口不支持带值删除，走迁移脚本）

## 六、图片要不要重命名？——不要

**物理文件名和 file_name 字段都不动。**

1. 文件名职责是**存储标识**，检索职责已由标签承担；人和 agent 都不会用 048A9972.jpg 检索
2. storage_path 被版本历史、收藏、分享签名 URL 引用，1.2 万文件改名纯风险零收益
3. 相机连号反而保留拍摄批次线索

替代：下载时动态命名（见 4.4）；二期可选 AI caption 字段进关键词检索。

## 七、实施排期（修订：一期 ≈ 6~7 天，不含设计部确认等待）

| 步骤 | 内容 | 工作量 |
|------|------|--------|
| 1 | Alembic 迁移（3 表加列）+ 新维度种子（避开老 name）+ DEFAULT_DIMENSIONS 替换 | 1 天 |
| 2 | 映射表生成脚本 → 设计部确认 Excel（1→N/N→1 模板） | 0.5 天 |
| 3 | 存量迁移脚本（第 1+2 层）+ 备份 + 覆盖率报告 + 单选/必填裁决 | 1 天 |
| 4 | 写入口修复五件套（preset 动态化 / folder_upload 两处 / 编辑合并语义 / 单选校验） | 1 天 |
| 5 | 前端：筛选分组渐进 + 级联 + 管理页 + /m/ 适配 + 下载命名 | 1.5 天 |
| 6 | MCP 两工具（含权限过滤） | 1 天 |
| 7 | pytest（映射规则/迁移幂等/单选校验/MCP 权限）+ check_conventions + 文档三处同步 + 对抗性审查（DoD 双命中：跨 3+ 文件 + 迁移）| 含在各步 + 0.5 天收尾 |
| 部署 | deploy.bat 主实例 + `git push cloud` 北京展会实例（共库，schema 先行兼容已保证） | 随步骤 |
| 二期 | AI 视觉补标 + caption + 检索日志分析 | 按需另排 |

## 八、需要亮哥拍板的问题

1. **产品类型 34 值定名与英文别名**——映射 Excel 生成后给设计部确认；「打孔发帘 4 变体拆不拆」「天才 vs 天才发帘同义与否」需业务定
2. **AI 视觉补标（第 3 层）做不做**——建议一期不做，先验证纹理检索是真需求
3. **MCP 调用方**——内部 agent（复用个人 token）还是外部第三方（另设计鉴权）？影响鉴权与签名 URL 有效期设计
4. **手工编辑改「按维度合并」语义**是前后端契约变更（PATCH 只覆盖请求中出现的维度），移动端与 PC 端同步改——确认无其他调用方依赖全删全写行为后实施
