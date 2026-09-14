# 客户拍摄素材 — 目录化上传设计方案（2026-09-14）

## 背景与需求

设计管理 → 排期任务 → 上传素材（`CustomerMediaWorkspace.vue`）目前只有单一直传入口，所有素材平铺在批次下。需要支持目录化管理：

1. **入口一（现有拖拽区增强）**：直接拖入文件或文件夹上传。拖入文件夹时：
   - 文件夹名称与当前客户下**已有目录**同名（忽略大小写、去首尾空格）→ 素材直接归入已有目录，**不新建**；
   - 不同名 → 自动以该文件夹名新建目录并归入；
   - 多级嵌套文件夹只取**顶层文件夹名**作为目录名，下层文件打平归入同一目录；
   - 直接拖入的散文件 → 归入"未分类"（`directory_id = NULL`）。
2. **入口二（新增弹窗"客户素材门户"）**：弹窗内展示当前客户的素材页面：
   - 手动新建目录、重命名已有目录；
   - 在选中的目录下上传素材；
   - 素材按目录筛选查看。

## 关键设计决策

- **目录是客户级数据**，不随批次/任务隔离（需求明确"与当前客户下已有的目录名称一致"）。一个客户的目录被其所有素材批次共享，重命名对所有批次生效。
- **素材仍归属批次**（现有 `ark_customer_media_assets.batch_id` 不变），仅增加可空的 `directory_id` 指向客户目录。历史素材为 NULL = 未分类。
- 目录只做新建/重命名，**本期不做删除**（删除涉及素材归属策略，空目录允许存在）。
- 弹窗素材视图范围 = **当前批次**的素材（上传工作上下文），目录列表是客户级，目录上的计数按当前批次内未删素材统计。
- 客户可见的公开门户（`public_router` / `CustomerMediaClientLibrary`）本期**不改动**，仍按批次展示。

## 后端改动

### 数据模型（`backend/app/customer_media/models.py`）

新表 `ark_customer_media_directories`：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | BigInteger PK | 主键 |
| customer_id | String(64) | customer_info.company_id |
| name | String(128) | 目录名 |
| created_by | USER_ID FK ark_users.id | 创建人 |
| created_at / updated_at | DateTime | 北京时间 |

约束：`UniqueConstraint("customer_id", "name")`（生产 MySQL utf8mb4 默认 ci 排序规则，天然大小写不敏感）；`Index(customer_id)`。

`ark_customer_media_assets` 增加 `directory_id = Column(BigInteger, ForeignKey(..., ondelete="SET NULL"), nullable=True)` + 索引。

### Alembic 迁移

`147_customer_media_directories.py`，`down_revision = "146_ai_site_gateway"`（已 `git log --all` 核对全分支最新为 146）。

### 接口（`backend/app/customer_media/router.py` / `service.py`）

全部挂在批次路径下，复用 `_assert_writer` 设计师归属校验 + `customer_media:write/admin` 权限：

- `GET /batches/{batch_id}/directories` → `[{id, name, asset_count}]`（asset_count 为本批次内未删素材数；目录创建/重命名只要求 writer 权限，不强制批次 editable）。
- `POST /batches/{batch_id}/directories` `{name}` → find-or-create（trim 后按客户+名字匹配，已存在直接返回 200，幂等）。
- `PATCH /batches/{batch_id}/directories/{directory_id}` `{name}` → 重命名；同客户重名 → 409 "同名目录已存在"；跨客户目录 → 404。
- `POST /batches/{batch_id}/assets` 上传增加可选 form 字段：
  - `directory_id`：校验目录属于该批次客户，否则 409；
  - `directory_name`：后端 find-or-create 后归入（入口一文件夹拖拽用，天然幂等，免去前端先查后建的竞态）；
  - 两者都传时以 `directory_id` 为准；都不传 → 未分类。
- `_batch` 序列化：`assets[]` 增加 `directory_id`；批次增加 `directories: [{id, name, asset_count}]`，前端每次上传/删除后用响应整体刷新，无需额外请求。

## 前端改动

### `frontend/src/api/customerMedia.js`

- `getMediaDirectories(batchId)` / `createMediaDirectory(batchId, name)` / `renameMediaDirectory(batchId, directoryId, name)`；
- `uploadMediaAsset(batchId, file, onUploadProgress, { directoryId, directoryName } = {})` 追加 FormData 字段。

### `CustomerMediaWorkspace.vue`（入口一）

- 文件夹拖拽（现有 `onDropFolders`）改为按**顶层文件夹名**分组：每组上传时带 `directory_name=<顶层文件夹名>`，后端 find-or-create 自动完成"同名归入 / 异名新建"；散文件不带目录字段。
- 上传区旁新增第二入口按钮「客户素材门户」打开弹窗。
- 素材卡片增加目录名小标签（便于确认归组结果）。

### 新组件 `frontend/src/views/design/customer-media/CustomerMediaDirectoryDialog.vue`（入口二）

- `el-dialog`，标题"客户素材门户"，宽度约 1080px。
- 左侧目录栏：全部 / 未分类 / 各客户目录（显示本批次素材数）；顶部"新建目录"输入框；每行目录支持行内重命名（编辑图标 → input → 确认/取消）。
- 右侧：当前选中目录筛选后的素材网格（图/视频缩略 + 文件名 + 大小 + 删除）；顶部上传区（沿用 el-upload 拖拽样式，支持文件与文件夹拖入），**上传目标固定为当前选中目录**；选中"全部"时上传归入未分类并提示。
- 弹窗内操作直接读写 workspace 的 `batch` 状态（上传/删除响应即最新批次），关闭时无需额外同步。
- 批次不可编辑（`editable=false`）时弹窗只读：目录可浏览筛选，新建/重命名/上传/删除禁用。

## 测试与验证

- `backend/tests/test_customer_media.py` 新增用例：
  - find-or-create 幂等（同名含大小写差异不重复建）；
  - 上传带 `directory_name` 自动建目录并归入；带 `directory_id` 归入已有目录；
  - 重命名成功 + 同客户重名 409 + 跨客户目录 404；
  - 未分类素材 `directory_id` 为 NULL 的兼容。
- `cd backend && pytest tests/test_customer_media.py`；`cd frontend && npm run build`。
