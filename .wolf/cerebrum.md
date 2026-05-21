# Cerebrum

> OpenWolf's learning memory. Updated automatically as the AI learns from interactions.
> Do not edit manually unless correcting an error.
> Last updated: 2026-05-19

## User Preferences

<!-- How the user likes things done. Code style, tools, patterns, communication. -->

## Key Learnings

<!-- Project-specific conventions discovered during development. -->

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

## Decision Log

<!-- Significant technical decisions with rationale. Why X was chosen over Y. -->

- [2026-05-19] 素材存储根目录默认 `D:\WORKSOURCE`（`ASSET_STORAGE_ROOT` 环境变量），与 uploads/avatars 分离 — 历史文件量大，独立盘符便于扩展
- [2026-05-19] AI 打标签走「文件名解析」路线而非视觉模型 — 需求确认后设计部命名规范已含颜色/尺寸信息，视觉模型成本高且延迟大，文本解析足够
- [2026-05-19] 收藏夹分享采用 token 机制（非短链服务）— 分享场景独立，token 直接绑定收藏夹表，简化链路
