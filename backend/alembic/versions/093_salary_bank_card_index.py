"""salary: 银行卡哈希唯一约束降级为普通索引

Revision ID: 093_salary_bank_card_idx
Revises: 092_salary_module
Create Date: 2026-08-06

为什么改：092 给 `bank_card_hash` 建了 UNIQUE，把「查重提示」错做成了「硬约束」。
共卡代发（夫妻/父子同卡）在小公司真实存在，动作 2 的档案反向导入脚本本身就
识别出了 duplicate bank card 的异常行。UNIQUE 之下第二个人的档案永远建不进去，
也就永远进不了工资表，且没有旁路（无 force 参数、无 admin 覆盖端点）。

身份证 UNIQUE 保留——一人一证是真约束，撞车必然是录错。
银行卡降级为普通索引：仍能按哈希秒查重复，但由人判断是共卡还是复制错行。

092 已 apply 到共享库，不改它本身（改已 apply 的迁移会让它自己的 downgrade 失效，
见 docs/database.md 的教训），走新迁移。
"""

from alembic import op

revision = "093_salary_bank_card_idx"
down_revision = "092_salary_module"
branch_labels = None
depends_on = None

_TABLE = "ark_salary_employee_profile"
_UK = "uk_salary_profile_bank_card"
_IDX = "idx_salary_profile_bank_card"


def upgrade() -> None:
    # MySQL 里 UNIQUE 约束就是一个 UNIQUE INDEX，drop_constraint(type_="unique")
    # 生成 DROP INDEX，与建表时的 UniqueConstraint 对得上。
    op.drop_constraint(_UK, _TABLE, type_="unique")
    op.create_index(_IDX, _TABLE, ["bank_card_hash"])


def downgrade() -> None:
    # 回滚前提：库里当前没有重复的 bank_card_hash，否则建 UNIQUE 会报 1062。
    op.drop_index(_IDX, table_name=_TABLE)
    op.create_unique_constraint(_UK, _TABLE, ["bank_card_hash"])
