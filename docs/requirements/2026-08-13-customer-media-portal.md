# 客户专属素材库详细设计（首期冻结版）

日期：2026-08-13

## 1. 产品边界

- 方舟是客户、预约、任务、审核、发布和门户账号的唯一事实源。
- 客户通过 `https://media.leshine.cloud` 登录；门户账号与方舟账号完全隔离。
- `customer_info.company_id` 是客户关联唯一键，客户名称只保存业务快照。
- 一个客户 ID 只允许一个登录邮箱；邮箱全局唯一，不开放注册和找回密码。
- 首期只提供原始图片/视频的上传、审核、发布、查看和下载，不提供任何在线编辑。
- 文件首期保存在 `leshine.cloud` 服务器私有目录；数据库只保存 provider 与 object key，后续迁移 COS 不改变业务 API。

## 2. 角色与权限

| 角色 | 能力 |
|---|---|
| 预约发起人 | 从本人客户中选择客户、查看批次、审核通过或整批退回 |
| 设计师/设计管理 | 查看负责任务、上传/删除草稿素材、提交审核 |
| 素材管理员 | 查看全部、代审、下架、管理门户账号和重置密码 |
| 外部客户 | 只查看和下载本客户已发布素材 |

方舟权限码：`customer_media:read`、`customer_media:write`、`customer_media:admin`。
外部门户不使用 RBAC，所有查询以服务端会话中的 `customer_id` 强制收口。

## 3. 状态与事务

素材批次状态：

```text
draft -> pending_review -> published
             |                 |
             v                 v
     changes_requested      unpublished
             |
             +-----> pending_review
```

- 每个设计任务最多一条素材批次；重复打开工作台返回原批次。
- 设计师“完成并送审”在一个事务内锁定批次和设计请求，校验至少一个 ready 素材，将拍摄任务/请求置 `completed`，批次置 `pending_review`。
- 退回只改变素材批次，不回退拍摄完成状态。
- 审核操作使用 `lock_version` 乐观锁，重复请求和陈旧页面返回 409。
- 发布不复制文件；门户只查询 `published`，审核通过提交后立即可见。
- 已发布批次只能由管理员下架；不物理删除发布记录和原件。

## 4. 存储契约

私有根目录由 `CUSTOMER_MEDIA_STORAGE_ROOT` 配置，文件 object key：

```text
customers/{customer_id}/batches/{batch_id}/originals/{uuid}.{ext}
customers/{customer_id}/batches/{batch_id}/thumbnails/{uuid}.jpg
```

首期 provider 为 `local`。所有业务代码经 `MediaStorage` 接口访问；未来增加 `CosMediaStorage`，迁移时仅复制 object key、校验 SHA-256 并切换 provider。

- 不把存储根挂为公开静态目录。
- 内部/门户内容端点先做归属和状态校验，再流式返回文件。
- 上传采用流式落盘、临时文件、原子 rename；单文件/批次容量由 Settings 控制。
- 允许 JPEG/PNG/WebP/GIF 与 MP4/MOV/WebM；服务端按 MIME、扩展名和真实文件头交叉校验。
- 下载使用 `Content-Disposition`；门户下载写审计日志。

## 5. 数据表

- `ark_customer_media_batches`：任务唯一批次、客户快照、发起人、设计师、状态、修订和审核信息。
- `ark_customer_media_assets`：原件元数据、provider/object key、SHA-256、缩略图及软删除。
- `ark_customer_media_reviews`：每轮提交、退回、通过、下架的不可变审计事件。
- `ark_customer_portal_accounts`：客户唯一账号、邮箱唯一、bcrypt 密码哈希、会话版本和禁用状态。
- `ark_customer_portal_sessions`：随机会话 token 的 SHA-256、有效期、撤销时间、IP 和 UA。
- `ark_customer_media_downloads`：客户下载审计。

同时给 `design_schedule_request`、`design_schedule_task` 增加 `customer_id VARCHAR(64)`。

## 6. API 契约

方舟鉴权 API（`/api/customer-media`）：

- `GET /customers?search=`：按权限搜索 `customer_info`。
- `GET /tasks/{task_id}/batch`：取得或幂等创建任务素材批次。
- `POST /batches/{id}/assets`：流式上传原件。
- `DELETE /batches/{id}/assets/{asset_id}`：仅草稿/退回状态删除。
- `POST /batches/{id}/submit`：完成拍摄并送审。
- `GET /reviews`：当前用户待审队列；管理员可看全部。
- `POST /batches/{id}/review`：`approve` 或 `request_changes`。
- `POST /batches/{id}/unpublish`：管理员下架。
- `GET/POST/PATCH /portal-accounts`：门户账号查询、创建/修改、启停、重置密码。
- `GET /assets/{id}/content`：内部预览/下载。

门户 API（`/api/customer-media/portal`）：

- `POST /login`、`POST /logout`、`GET /me`。
- `GET /library`：本客户已发布批次及素材。
- `GET /assets/{id}/content?download=`：本客户已发布素材预览/下载。

门户 session 使用 HttpOnly、Secure、SameSite=Lax Cookie；邮箱与真实密码不写日志。

## 7. 页面

- 提交预约：客户名称文本框改为远程客户搜索，表单同时保存客户 ID 和名称快照。
- 设计管理：执行中任务的“标记完成”改为“上传素材”；工作台完成上传后统一送审。
- 我的预约：新增“素材状态/审核素材”入口，发起人完成审批。
- 客户素材管理：管理员管理单客户单账号、启停和密码重置。
- 客户门户：登录、按批次展示、图片/视频预览、单个下载；首期不做编辑、多账号或客户上传。

## 8. 上线门禁

- `media.leshine.cloud` 当前存在未备案导致 HTTPS reset 的已知风险；未恢复可用前不得向客户发正式链接。
- 域名可用后配置独立证书、DNS、Nginx server block、CORS、上传体积限制、登录限速和私有文件内部转发。
- 上线前必须有第二份文件备份、磁盘空间告警和抽样恢复演练；单机唯一副本不满足发布条件。

