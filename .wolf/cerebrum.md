# Cerebrum

> OpenWolf's learning memory. Updated automatically as the AI learns from interactions.
> Do not edit manually unless correcting an error.
> Last updated: 2026-05-25

## User Preferences

<!-- How the user likes things done. Code style, tools, patterns, communication. -->

## Key Learnings

<!-- Project-specific conventions discovered during development. -->

- SQLAlchemy session 在循环批量处理中，单次 `db.commit()` 失败后必须显式 `db.rollback()` 恢复 session 状态，否则后续所有 commit 都会失败。典型案例：`folder_upload_service.py` 的 `execute_folder_upload` 逐文件入库，一个文件异常后 session 污染导致后续全部文件数据库写入失败（但 `_save_upload_file` 文件复制不受影响，造成"文件已复制但数据库没数据"的诡异现象）

- 素材管理模块采用**领域模块**结构（与 tracking/stock/insight 一致），`app/asset/` 下自包含 router/models/schemas/service，复杂逻辑拆子 service 模块
- 标签维度/值设计为**可扩展的 EAV 模式**：`tag_dimensions`（维度定义）+ `tag_values`（值定义）+ `asset_tag_association`（多对多关联），支持单选/多选/必填/系统内置标记
- AI 打标签通过**预设调用链**复用：`analyze_service.py` → `app.ai.service.chat` → `asset_analyze` preset，无需独立视觉模型，文件名+目录路径解析即可满足需求
- 移动端独立页面部署方案：Vue 3 CDN 单页 HTML 放 `frontend/public/m/`，Vite 构建时自动拷贝到 `dist/m/`，生产环境通过 `https://leshine.work/m/` 访问，与后端 API 同域免 CORS
- `asset_service.py` 已有 `get_asset_download_url()` 生成签名 URL，`verify_sign_token()` 验证签名。分享链接可直接复用下载签名机制
- 文件夹批量上传走独立 service (`folder_upload_service.py`) + 3 个 API 端点 (`validate`/`preview`/`execute`)，复用现有 `create_asset`/`upload_new_version` 实现版本迭代
- 新路由注册顺序至关重要：`/folder-upload/*` 必须在 `/{asset_id}` 之前注册，否则 FastAPI 会将 `folder-upload` 匹配为 asset_id（详见 Do-Not-Repeat 2026-05-20）
- `_save_upload_file()` 新增 `copy: bool=False` 参数实现「移动/复制」双模式 — folder_upload 用 `copy=True` 保留源目录文件，单文件上传默认 `copy=False` 清理临时文件，零侵入兼容
- 异步文件夹上传采用「内存 job store + threading.Thread」方案 — 项目无 Redis/Celery，threshold=100 时返回 job_id 前端轮询，足够覆盖场景
- Vue 页面左右分栏独立滚动：最终采用 `position: sticky` 方案（`filter-sidebar` sticky + `toolbar` sticky），不依赖嵌套 flex 高度传递，更稳定
- 标签值图片上传存 `UPLOADS_DIR/tag_images/`（系统 uploads 目录），前端通过 `/uploads/${path}` 访问；与素材文件（存 `ASSET_STORAGE_ROOT`/`D:\WORKSOURCE`，通过 `/uploads/assets/` 访问）物理隔离
- 行业情报模块采用「采集库 → 速览」分层架构：情报条目 (`InsightItem`) 做中间存储层，速览报告 (`InsightReport` type=intelligence_overview) 从条目选材生成。与现有 `industry_daily` 管线共存，长期可迁移
- 信源差异化配置（cron/target_accounts/monitor_fields 等）统一存 `config_json` JSON 字段，不在表中横向扩展。校验在 Pydantic/service 层做，灵活且无需改表结构
- 情报速览 HTML 报告采用完整 HTML 文档模板（带 `<style>`），前端用 iframe 嵌入避免 v-html 样式污染。文件存 `uploads/intelligence_reports/`，数据库存 `file_path`
- 采集引擎用装饰器注册表模式：`@register_collector("rss")` 将采集函数注册到 `_COLLECTORS` 字典，统一入口 `collect_source()` 按 `source_type` 路由。新信源类型只需加装饰器函数
- 发色数字化模块采用领域模块结构 `app/color/`，自包含 router/models/schemas/service facade + palette/blend/calc/trend/swatch/social_extract 子模块。混色计算在 LAB 空间做加权线性插值替代 Kubelka-Munk 模型（pymixbox 非商用授权）
- 混合色（Piano/Ombre/Balayage/Rooted）通过 `color_blend` + `color_blend_component` 两张表联合表达，`computed_hex` 仅用于列表缩略图和粗筛，真实色彩结构通过 component 表的 position + weight + sort_order 完整描述
- 色彩计算核心依赖 `colour-science`（BSD-3 授权），提供工业级色彩空间转换（RGB↔LAB↔XYZ）、ΔE2000 色差计算。OpenCV + scikit-learn 用于图片主色提取（K-means 聚类）
- 素材库标签联动筛选的可用标签值必须基于**全量检索结果**（不分页）统计，而非当前页。实现方式：后端 `query_assets` 在同筛选条件下（排序和分页之前）额外做一次 `DISTINCT tag_value_id` 查询，随分页结果一并返回 `available_tag_ids`。前端直接用该字段替代从 `assets.value` 自行统计
- **Vue 3 CDN 全局构建中，无值 attribute 绑定行为与 SFC 不同**：`<BottomSheet searchable>` 在运行时模板中不会自动传 `true`，而是传空字符串 `''`（falsy），导致 `v-if="searchable"` 不渲染。必须显式写成 `:searchable="true"` 才能正确传递布尔值。这与 SFC 编译版本不同（SFC 中无值 prop 会根据 prop 类型定义自动转换）
- **移动端 `/quick-search` 和 `/recent` API 返回的字段与 `/list` 不同**：`/list` 返回 `storage_path`，而 `/quick-search`/`/recent` 早期实现遗漏了该字段。移动端 `MAssetCard` 仅使用 `thumbnail_path` 生成缩略图 URL，当缩略图生成失败时 `thumbnail_path` 为空，导致图片卡片空白。修复：后端补充 `storage_path`，前端 fallback 到 `storage_path`

## Do-Not-Repeat

<!-- Mistakes made and corrected. Each entry prevents the same mistake recurring. -->
<!-- Format: [YYYY-MM-DD] Description of what went wrong and what to do instead. -->

- [2026-05-19] Python 字符串内包含双引号时，外层必须用单引号包裹，否则解析失败。`description='JSON {"color":[1,2]}'` 而不是 `"JSON {"color":[1,2]}"`
- [2026-05-19] SQLAlchemy relationship 在双向外键引用时必须显式指定 `foreign_keys`，否则启动期映射失败。`asset = relationship("Asset", back_populates="versions", foreign_keys=[asset_id])`
- [2026-05-19] MySQL 8 外键要求引用列和被引用列类型完全匹配（包括 unsigned）。Alembic 迁移中 `Integer()` 默认有符号，而 `AUTO_INCREMENT` 列默认 unsigned，需用 `sa.Integer().with_variant(mysql.INTEGER(unsigned=True), 'mysql')` 统一
- [2026-05-20] 移动端独立页面（Vue CDN）与主站共享登录态时，token 必须持久化到 localStorage（而非仅内存 Pinia），否则独立页面无法读取。修改点：`stores/auth.js` 中 `_setGlobalToken` 同步写 localStorage，`clearAuthState` 同步清除
- [2026-05-20] FastAPI 同一 router 内两个函数装饰相同路径+方法会被静默覆盖（后定义者 wins），不会报错。新增接口前必须 grep 检查路径是否已存在，避免与已有接口冲突
- [2026-05-20] FastAPI 路径参数路由 `/{asset_id}` 会吞噬所有单段路径（如 `/folder-upload/validate`），必须在 `/{asset_id}` 之前注册更具体的路径。文件夹上传的 `/folder-upload/*` 三端点放在 `/list` 之后、`/{asset_id}` 之前
- [2026-05-20] insight 模块阶段二拆分时丢失了 4 个模块级常量（`_DEFAULT_UA`/`_AIHOT_BASE_URL`/`_AIHOT_SECTION_MAP`/`_CASE_SKILL_CORE`），导致信源抓取和 AI 工具报告生成 NameError。修复：在每个使用文件顶部补回常量定义
- [2026-05-20] MySQL DDL 是自动提交的，Alembic 迁移中前面 `add_column` 成功、后面 `create_table` 失败时，已添加的列不会回滚。需让迁移幂等（`IF NOT EXISTS` 检查），且 FK 引用列类型必须与目标列完全匹配（signed vs unsigned）
- [2026-05-21] `start.bat` 使用的是 `.venv` 虚拟环境中的 Python，不是全局 Python。新依赖必须同时安装到 `.venv`（` .venv/Scripts/python.exe -m pip install xxx`）和全局环境，否则通过 start.bat 启动时模块导入失败报 500
- [2026-05-21] MySQL 外键要求引用列和被引用列类型**完全匹配**（包括 unsigned）。Alembic 迁移中 `_UINT = sa.Integer().with_variant(mysql.INTEGER(unsigned=True), 'mysql')` 用作主键时，FK 引用列也必须用 `_UINT`，不能用 `sa.Integer()`
- [2026-05-21] Margaret2/pantone-colors 的 `pantone-colors.json` 只有 names/values 数组，Pantone code 在单独的 `pantone-numbers.json` 中（key 为 code，value 为 {name, hex}）
- [2026-05-22] 关联表（多对多）的复合主键必须包含所有区分度列，不能只设一个 `asset_id` 为主键。`ark_asset_tags` 原主键只有 `asset_id`，导致同一素材无法写入多条标签，文件夹批量上传第二条标签即报 IntegrityError (1062)。正确主键应为 `(asset_id, dimension_id, tag_value_id)`。同时 `_clear_tags` 需按 `asset_id` 清除全部旧标签（而非仅当前 version），避免新旧版本标签重叠导致复合主键冲突
- [2026-05-23] 文件夹批量上传服务中 `file_type` 不能硬编码为 `"image"`。`scan_folder` 的扩展名白名单、`execute_folder_upload` 的查重条件和 `create_asset` 调用都必须根据实际文件扩展名自动判断类型（image/video/document），否则视频/文档文件在扫描阶段就被丢弃或入库后类型错误
- [2026-05-25] Vue 3 的 `v-if`/`v-else-if`/`v-else` 必须在**同级相邻元素**上配对。移动端 `MAssetCard` 中 `img` 在 `router-link` 内部有 `v-if`，但 `v-else-if`/`v-else` 的 div 在 `router-link` 外部 → 导致 `v-else-if`/`v-else` 被静默忽略，视频/无缩略图素材在卡片上完全空白。修复：将 `v-else-if`/`v-else` 元素移入 `router-link` 内部与 `img` 同级
- [2026-05-25] Vue 3 CDN 运行时模板中，组件无值 attribute（如 `<BottomSheet searchable>`）传的是空字符串 `''` 而非布尔值 `true`。空字符串是 falsy 的，导致 `v-if="searchable"` 不渲染搜索框、`v-if="multi"` 不显示"清除"按钮。修复：显式写成 `:searchable="true"` `:multi="true"`
- [2026-05-25] 素材库移动端搜索页初始态调用 `loadRecent()`（基于 `DownloadLog`），如果用户没有下载/查看/复制记录，返回空数组，页面显示"没找到匹配素材"。与 PC 端素材库（显示全量列表）行为不一致。修复：`loadRecent()` 返回空时自动 fallback 到 `doSearch()` 获取全量素材列表
- [2026-05-25] 后端 `/quick-search` 和 `/recent` 返回的字段集与 `/list` 不同，遗漏了 `storage_path`。移动端 `MAssetCard` 仅依赖 `thumbnail_path` 生成缩略图 URL，缩略图生成失败时卡片空白（无 fallback）。修复：后端补充 `storage_path`，前端使用 `thumbnail_path || storage_path` fallback

## Decision Log

<!-- Significant technical decisions with rationale. Why X was chosen over Y. -->

- [2026-05-19] 素材存储根目录默认 `D:\WORKSOURCE`（`ASSET_STORAGE_ROOT` 环境变量），与 uploads/avatars 分离 — 历史文件量大，独立盘符便于扩展
- [2026-05-19] AI 打标签走「文件名解析」路线而非视觉模型 — 需求确认后设计部命名规范已含颜色/尺寸信息，视觉模型成本高且延迟大，文本解析足够
- [2026-05-19] 收藏夹分享采用 token 机制（非短链服务）— 分享场景独立，token 直接绑定收藏夹表，简化链路
