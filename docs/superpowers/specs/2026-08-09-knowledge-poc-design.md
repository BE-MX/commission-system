# 方舟知识库 POC 设计

## 目标

在方舟现有 FastAPI、Vue 3、RBAC 与 MCP 基础上，交付可部署的原生知识库最小闭环：管理员创建知识库并分配成员权限，编辑者编写文档并提交审批，审核者批准冻结版本，已授权用户和 Agent 只能检索、读取已发布内容。

POC 验收不是“页面能打开”，而是权限边界、审批快照和 Agent 接口由同一服务层强制执行并有自动化测试证明。

## 范围

### 包含

- 知识库创建、列表和成员 ACL 管理。
- 目录节点与文档树。
- 基于 Tiptap OSS 的 Vue 3 富文本编辑器，正文以 ProseMirror JSON 为事实源。
- 草稿保存、提交审批、批准、驳回和已发布版本读取。
- 不可变修订记录和追加式审计日志。
- HTTP API 与 MCP 的授权搜索和文档读取。
- 后端测试、前端构建、规范检查和部署说明。

### 不包含

- 附件、图片上传和文件预览。
- 多人实时协作、评论、外链分享、模板和复杂导入导出。
- 独立搜索引擎。
- 依靠提示词承诺“绝对无法复制”。内容防外流在本期通过最小授权、仅发布版本、审计和限量响应降低风险，不宣称解决可见内容的人工重组问题。

## 架构

新增 `backend/app/knowledge/` 领域模块，包含模型、Schema、服务和路由。HTTP 路由只负责参数与响应；ACL、状态机、搜索可见性和审计全部位于服务层，MCP 工具复用同一服务，避免形成第二套权限实现。

前端新增单一知识库工作台。左侧知识库和目录树，中部文档列表，右侧文档编辑或只读内容。高频编辑动作不增加装饰动画，沿用现有 Design Token、GlassButton 和 Element Plus 反馈组件。

## 权限模型

平台级权限：

- `knowledge:read`：进入模块并读取获授权知识库。
- `knowledge:write`：在成员角色允许时创建、编辑和提交文档。
- `knowledge:review`：在成员角色允许时审批。
- `knowledge:admin`：创建知识库、维护 ACL 和管理结构。

知识库成员角色：

- `viewer`：读取已发布内容。
- `editor`：包含 viewer，并可维护草稿和提交审批。
- `reviewer`：包含 viewer，并可批准或驳回审批。
- `admin`：知识库内全部能力和成员维护。

每个服务方法同时验证平台权限和知识库 ACL。除平台超级管理员外，未授权资源统一表现为不存在，避免泄露标题、目录和 ID。权限实时查库，不依赖 JWT 中可能长期缓存的资源 ACL。

## 数据模型

- `ark_knowledge_libraries`：知识库名称、描述、创建者、状态与时间戳。
- `ark_knowledge_library_members`：知识库、用户、成员角色，二者唯一。
- `ark_knowledge_documents`：知识库、父目录、节点类型、标题、排序、当前草稿修订、已发布修订、状态与软删除时间。
- `ark_knowledge_revisions`：不可变标题、Tiptap JSON、纯文本、版本号、作者和创建时间。
- `ark_knowledge_approval_requests`：文档、冻结 revision、状态、提交者、审核者、意见与时间。
- `ark_knowledge_audit_logs`：actor、action、object、revision、detail 和时间，仅追加。

文档正文 canonical 为受限 Tiptap JSON。服务端验证根节点及允许节点类型，并抽取纯文本用于 POC 关键词搜索。HTML 只在前端由编辑器渲染，不存为事实源。

## 状态机

1. 编辑保存时创建新的不可变 revision，并更新 `draft_revision_id`。
2. 提交审批时创建 `pending` approval，绑定当时 revision；审批期间继续编辑可产生新草稿，但不会改变待审内容。
3. 批准时将 approval 置为 `approved`，并把 `published_revision_id` 指向该冻结 revision。
4. 驳回时只更新 approval；草稿继续存在。
5. HTTP 普通读取可按权限返回草稿或发布版；搜索与 MCP 永远只读取 `published_revision_id`。

每个状态变化与 ACL 变化写入审计日志并在同一数据库事务提交。

## API 与 MCP

HTTP API 使用 `/api/knowledge`：

- `GET/POST /libraries`
- `GET /libraries/{library_id}`
- `PUT /libraries/{library_id}/members`
- `GET /libraries/{library_id}/tree`
- `POST /libraries/{library_id}/documents`
- `GET/PUT /documents/{document_id}`
- `POST /documents/{document_id}/submit`
- `GET /approvals`
- `POST /approvals/{approval_id}/approve`
- `POST /approvals/{approval_id}/reject`
- `GET /search`

MCP 新增：

- `search_knowledge(query, limit)`：仅返回调用者获授权知识库的已发布标题、摘要和 document_id。
- `get_knowledge_document(document_id)`：仅返回获授权的已发布标题与正文纯文本。

MCP 继续使用个人 opaque token 映射到方舟用户；服务层随后执行平台权限与知识库成员校验。

## 错误处理与安全

- 无平台权限返回 403；目标资源无 ACL 或不存在统一返回 404。
- 非法状态转换返回 409；非法 Tiptap JSON 返回 422。
- 同一文档只允许一个 pending 审批；数据库唯一约束与服务校验共同保护。
- MCP 搜索 `limit` 有硬上限，详情一次仅返回一个文档；所有访问进入审计。
- 禁止文档 JSON 中的任意脚本、iframe 和未批准节点；前端不使用未经清洗的 `v-html`。
- POC 的“不能下载”定义为不提供附件或批量导出接口，并不把浏览器中已展示内容描述为不可复制。

## 测试与验收

- 服务测试证明 viewer/editor/reviewer/admin 权限矩阵。
- 越权测试覆盖列表、树、详情、搜索和 MCP，断言未授权资源不可见。
- 状态机测试证明审批绑定冻结 revision，提交后新草稿不会暗改待审内容。
- MCP 测试证明草稿和待审内容不可见，批准后可检索并读取。
- 路由接线测试证明权限依赖、统一响应和 MCP 工具注册。
- 前端 API/状态辅助测试、生产构建、后端目标测试、全量 pytest、Alembic 校验和 `scripts/check_conventions.py` 全部通过。
- 本地启动后执行登录、建库、授权、编辑、提交、审批、MCP 查询的冒烟流程。

## 部署策略

数据库变更为新增 `ark_knowledge_*` 表和权限种子，不修改现有业务表。迁移先验证 upgrade SQL 和模型一致性，再按项目现有 Alembic 流程应用。前后端沿用现有部署命令与静态资源服务；不新增独立服务，因此无需新增端口、Redis 或搜索集群。
