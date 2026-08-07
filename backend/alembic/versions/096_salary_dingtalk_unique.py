"""salary: 钉钉 userid 唯一约束

Revision ID: 096_salary_dingtalk_uniq
Revises: 095_salary_workday_source
Create Date: 2026-08-07

两份档案共用一个钉钉 userid 时，考勤同步会静默丢掉其中一个人：钉钉按 userid 只回
一条记录，`{p.dingtalk_userid: p}` 的字典推导让后来者覆盖前者，落库也只有一条。
而所有告警指标都是绿的——source_count == synced、failed == 0、unbound 为空——
被覆盖的那个人在失败清单、未绑定清单、考勤列表里都不出现。他当月考勤是空的，
M3 拿不到缺勤天数只能按全勤发，还附送 100 元全勤奖。

service 层已经在同步开始前整批拒绝（`attendance_service.profiles_by_userid` 返回
撞号清单），这一版是数据库兜底：绕过 service 的任何写入路径（脚本、手工 SQL、
以后新写的导入）都不该建出这种档案。

**UNIQUE 允许多个 NULL**（MySQL 与 SQLite 都是），所以没绑钉钉的人不受影响——
这是这个约束能加的前提，`dingtalk_userid` 本来就是 nullable。空串不在此列：
空串彼此相等，第二个空串会被拒。所以升级时先把空串归一成 NULL，否则约束建不上，
而空串和 NULL 在业务上是同一个意思（「没绑」）。

单独开一版而不是改 093：093 已在共库执行过（开发/生产同一套 RDS）。
"""

from alembic import op
import sqlalchemy as sa

revision = "096_salary_dingtalk_uniq"
down_revision = "095_salary_workday_source"
branch_labels = None
depends_on = None

_TABLE = "ark_salary_employee_profile"
_OLD_INDEX = "idx_salary_profile_dingtalk"
_NEW_INDEX = "uk_salary_profile_dingtalk"


def upgrade() -> None:
    # 1. 空串归一成 NULL。UNIQUE 放过多个 NULL 但不放过多个 ''，
    #    留着空串会让约束创建直接失败（而 MySQL 的 DDL 不可回滚）。
    op.execute(
        sa.text(
            f"UPDATE {_TABLE} SET dingtalk_userid = NULL "
            "WHERE dingtalk_userid IS NOT NULL AND TRIM(dingtalk_userid) = ''"
        )
    )
    # 2. 普通索引换成唯一索引。用 UNIQUE INDEX 而不是 UNIQUE CONSTRAINT：
    #    MySQL 下两者等价，但 drop 时索引名可控，回滚脚本不用猜约束名。
    op.drop_index(_OLD_INDEX, table_name=_TABLE)
    op.create_index(_NEW_INDEX, _TABLE, ["dingtalk_userid"], unique=True)


def downgrade() -> None:
    op.drop_index(_NEW_INDEX, table_name=_TABLE)
    op.create_index(_OLD_INDEX, _TABLE, ["dingtalk_userid"])
