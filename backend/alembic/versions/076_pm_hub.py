"""pm hub: project material collaboration tables

Revision ID: 076_pm_hub
Revises: 075_training_digest
Create Date: 2026-07-17

PM 项目资料协作站（设计稿 docs/requirements/2026-07-17-pm-material-hub.md）。
8 张表：项目/白名单/资料条目/资料版本/任务/任务资料关联/评论(P2)/审计日志。

沿革：原 073_pm_hub（down_revision=072）。合并时发现共享库已被 codex 的
073_invoice/074_invoice/075_training_digest（后者当时未提交）占头——
已把那三份迁移文件一并收编上 main，本迁移顺延为 076 接 075。
"""

from alembic import op
import sqlalchemy as sa


revision = "076_pm_hub"
down_revision = "075_training_digest"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ark_pm_projects",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False, comment="主键"),
        sa.Column("name", sa.String(128), nullable=False, comment="项目名称"),
        sa.Column("code", sa.String(64), nullable=False, comment="项目代号，如 alibaba-ai-agent"),
        sa.Column("description", sa.String(512), nullable=True, comment="项目说明"),
        sa.Column("status", sa.String(16), nullable=False, server_default="active", comment="active/archived"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP"), comment="创建时间"),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP"), comment="更新时间"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code", name="uq_ark_pm_projects_code"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
        comment="PM协作站-项目表",
    )

    op.create_table(
        "ark_pm_members",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False, comment="主键"),
        sa.Column("username", sa.String(64), nullable=False, comment="进入用用户名（非真名拼音，口头分发）"),
        sa.Column("display_name", sa.String(64), nullable=False, comment="展示名（审计/顶栏身份显示用）"),
        sa.Column("is_active", sa.SmallInteger(), nullable=False, server_default="1", comment="1=有效,0=已移出名单(token每请求回查,立即生效)"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP"), comment="创建时间"),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP"), comment="更新时间"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("username", name="uq_ark_pm_members_username"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
        comment="PM协作站-用户名白名单",
    )

    op.create_table(
        "ark_pm_materials",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False, comment="主键"),
        sa.Column("project_id", sa.BigInteger(), nullable=False, comment="所属项目 ark_pm_projects.id"),
        sa.Column("list_no", sa.Integer(), nullable=True, comment="顾问清单编号(1-35)，清单外新增为 NULL"),
        sa.Column("name", sa.String(256), nullable=False, comment="资料名称（项目内唯一，即下载文件名前缀）"),
        sa.Column("description", sa.String(1024), nullable=True, comment="资料说明"),
        sa.Column("category", sa.String(64), nullable=False, server_default="其他", comment="产品与报价/客户分类与分配/知识与内容/系统权限与账号/历史数据/其他"),
        sa.Column("importance", sa.String(16), nullable=False, server_default="important", comment="required必须/important重要/optional锦上添花"),
        sa.Column("phase", sa.SmallInteger(), nullable=True, comment="所属 Phase 1-4，按清单「准备顺序」批次，与重要级无关"),
        sa.Column("delivery_type", sa.String(16), nullable=False, server_default="file", comment="file文件/offline线下交付(禁传原文)/link外部链接"),
        sa.Column("external_url", sa.String(512), nullable=True, comment="delivery_type=link 时的网盘/素材中台链接"),
        sa.Column("delivery_remark", sa.String(512), nullable=True, comment="线下交付方式备注（凭据类材料只跟踪状态）"),
        sa.Column("status", sa.String(16), nullable=False, server_default="not_started", comment="not_started/preparing/submitted/confirmed/not_required"),
        sa.Column("owner", sa.String(64), nullable=True, comment="负责人（白名单 username）"),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0", comment="分类内排序"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP"), comment="创建时间"),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP"), comment="更新时间"),
        sa.Column("deleted_at", sa.DateTime(), nullable=True, comment="软删时间，非空即已删除"),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["project_id"], ["ark_pm_projects.id"]),
        sa.UniqueConstraint("project_id", "name", name="uq_ark_pm_materials_project_name"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
        comment="PM协作站-资料条目（名称项目内唯一）",
    )
    op.create_index("idx_ark_pm_materials_project", "ark_pm_materials", ["project_id"])

    op.create_table(
        "ark_pm_material_versions",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False, comment="主键"),
        sa.Column("material_id", sa.BigInteger(), nullable=False, comment="所属资料 ark_pm_materials.id"),
        sa.Column("version_no", sa.Integer(), nullable=False, comment="版本号（条目内自增，只增不复用）"),
        sa.Column("file_path", sa.String(512), nullable=False, comment="存储相对路径 {material_id}/{uuid}{ext}，根为 backend/data/pm"),
        sa.Column("original_name", sa.String(256), nullable=False, comment="上传原始文件名（存档用，不作对外名称）"),
        sa.Column("file_size", sa.BigInteger(), nullable=False, server_default="0", comment="字节数"),
        sa.Column("content_type", sa.String(128), nullable=True, comment="上传声明的 MIME"),
        sa.Column("change_note", sa.String(512), nullable=True, comment="上传人填写的一句修改说明（选填）"),
        sa.Column("diff_status", sa.String(16), nullable=False, server_default="pending", comment="pending/done/failed/not_applicable"),
        sa.Column("diff_summary", sa.Text(), nullable=True, comment="AI 差异概要（本地 diff + AI 转述）"),
        sa.Column("diff_error", sa.String(512), nullable=True, comment="差异管线失败原因（可手动重试）"),
        sa.Column("diff_updated_at", sa.DateTime(), nullable=True, comment="差异管线最后完成时间"),
        sa.Column("uploaded_by", sa.String(64), nullable=False, comment="上传人（白名单 username）"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP"), comment="上传时间"),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP"), comment="更新时间"),
        sa.Column("deleted_at", sa.DateTime(), nullable=True, comment="软删时间，非空即已删除(下载端点立即拒绝)"),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["material_id"], ["ark_pm_materials.id"]),
        sa.UniqueConstraint("material_id", "version_no", name="uq_ark_pm_versions_material_no"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
        comment="PM协作站-资料版本（material_id+version_no 唯一，并发上传靠约束+重试）",
    )
    op.create_index("idx_ark_pm_versions_material", "ark_pm_material_versions", ["material_id"])

    op.create_table(
        "ark_pm_tasks",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False, comment="主键"),
        sa.Column("project_id", sa.BigInteger(), nullable=False, comment="所属项目 ark_pm_projects.id"),
        sa.Column("title", sa.String(256), nullable=False, comment="任务标题"),
        sa.Column("description", sa.String(2048), nullable=True, comment="任务描述"),
        sa.Column("status", sa.String(16), nullable=False, server_default="todo", comment="todo/in_progress/done/blocked"),
        sa.Column("blocked_reason", sa.String(512), nullable=True, comment="受阻原因（置 blocked 必填）"),
        sa.Column("assignee", sa.String(64), nullable=True, comment="负责人（白名单 username）"),
        sa.Column("due_date", sa.Date(), nullable=True, comment="截止日期"),
        sa.Column("phase", sa.SmallInteger(), nullable=True, comment="所属 Phase 1-4（可选）"),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0", comment="看板列内排序"),
        sa.Column("created_by", sa.String(64), nullable=False, comment="创建人（白名单 username）"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP"), comment="创建时间"),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP"), comment="更新时间"),
        sa.Column("deleted_at", sa.DateTime(), nullable=True, comment="软删时间，非空即已删除"),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["project_id"], ["ark_pm_projects.id"]),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
        comment="PM协作站-任务看板",
    )
    op.create_index("idx_ark_pm_tasks_project", "ark_pm_tasks", ["project_id"])

    op.create_table(
        "ark_pm_task_materials",
        sa.Column("task_id", sa.BigInteger(), nullable=False, comment="任务 ark_pm_tasks.id"),
        sa.Column("material_id", sa.BigInteger(), nullable=False, comment="资料 ark_pm_materials.id"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP"), comment="关联时间"),
        sa.PrimaryKeyConstraint("task_id", "material_id"),
        sa.ForeignKeyConstraint(["task_id"], ["ark_pm_tasks.id"]),
        sa.ForeignKeyConstraint(["material_id"], ["ark_pm_materials.id"]),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
        comment="PM协作站-任务资料关联",
    )
    op.create_index("idx_ark_pm_task_materials_material", "ark_pm_task_materials", ["material_id"])

    op.create_table(
        "ark_pm_comments",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False, comment="主键"),
        sa.Column("material_id", sa.BigInteger(), nullable=False, comment="所属资料 ark_pm_materials.id"),
        sa.Column("version_id", sa.BigInteger(), nullable=True, comment="锚定版本；重锚失败降级保留原版本号"),
        sa.Column("parent_id", sa.BigInteger(), nullable=True, comment="父评论 id（单层回复）"),
        sa.Column("anchor_text", sa.String(1024), nullable=True, comment="划线引用原文（MD 锚点评论）"),
        sa.Column("anchor_context", sa.String(2048), nullable=True, comment="前后文特征（新版本按文本匹配重锚定）"),
        sa.Column("body", sa.String(2048), nullable=False, comment="评论内容（渲染前必须 sanitize）"),
        sa.Column("author", sa.String(64), nullable=False, comment="评论人（白名单 username）"),
        sa.Column("status", sa.String(16), nullable=False, server_default="open", comment="open/resolved"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP"), comment="创建时间"),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP"), comment="更新时间"),
        sa.Column("deleted_at", sa.DateTime(), nullable=True, comment="软删时间"),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["material_id"], ["ark_pm_materials.id"]),
        sa.ForeignKeyConstraint(["version_id"], ["ark_pm_material_versions.id"]),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
        comment="PM协作站-评论（Phase 2 划线锚点+文件级）",
    )
    op.create_index("idx_ark_pm_comments_material", "ark_pm_comments", ["material_id"])

    op.create_table(
        "ark_pm_activity_logs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False, comment="主键"),
        sa.Column("project_id", sa.BigInteger(), nullable=False, comment="所属项目 ark_pm_projects.id"),
        sa.Column("username", sa.String(64), nullable=False, comment="操作人（白名单 username）"),
        sa.Column("action", sa.String(32), nullable=False, comment="entry/upload_version/delete_version/create_material/update_material/delete_material/create_task/update_task/delete_task/retry_diff 等"),
        sa.Column("object_type", sa.String(16), nullable=False, comment="material/version/task/comment/member"),
        sa.Column("object_id", sa.BigInteger(), nullable=True, comment="对象主键"),
        sa.Column("object_name", sa.String(256), nullable=True, comment="对象名称快照（如 价格体系 v3，删除后仍可读）"),
        sa.Column("detail", sa.Text(), nullable=True, comment="附加 JSON（旧→新状态/修改说明/失败原因等）"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP"), comment="操作时间"),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["project_id"], ["ark_pm_projects.id"]),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
        comment="PM协作站-审计日志（全站动态数据源）",
    )
    op.create_index("idx_ark_pm_activity_project_time", "ark_pm_activity_logs", ["project_id", "created_at"])


def downgrade() -> None:
    op.drop_index("idx_ark_pm_activity_project_time", table_name="ark_pm_activity_logs")
    op.drop_table("ark_pm_activity_logs")
    op.drop_index("idx_ark_pm_comments_material", table_name="ark_pm_comments")
    op.drop_table("ark_pm_comments")
    op.drop_index("idx_ark_pm_task_materials_material", table_name="ark_pm_task_materials")
    op.drop_table("ark_pm_task_materials")
    op.drop_index("idx_ark_pm_tasks_project", table_name="ark_pm_tasks")
    op.drop_table("ark_pm_tasks")
    op.drop_index("idx_ark_pm_versions_material", table_name="ark_pm_material_versions")
    op.drop_table("ark_pm_material_versions")
    op.drop_index("idx_ark_pm_materials_project", table_name="ark_pm_materials")
    op.drop_table("ark_pm_materials")
    op.drop_table("ark_pm_members")
    op.drop_table("ark_pm_projects")
