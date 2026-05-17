"""设计预约状态机 — 单元测试

覆盖 state_machine.TRANSITIONS 的 15 条合法迁移 + 4 类非法路径。
纯函数测试,无 DB 依赖。
"""

import pytest

from app.design.state_machine import (
    OperatorRole,
    RequestStatus,
    TRANSITIONS,
    transition,
)


# 直接从 TRANSITIONS 表生成参数,任何 transitions 表的增减都自动反映到测试上
VALID_TRANSITIONS = [
    (from_status, action, role, to_status)
    for (from_status, action, role), to_status in TRANSITIONS.items()
]


@pytest.mark.parametrize(
    "from_status,action,role,to_status",
    VALID_TRANSITIONS,
    ids=[f"{f.value}--{a}-by-{r.value}" for (f, a, r), _ in TRANSITIONS.items()],
)
def test_valid_transition(from_status, action, role, to_status):
    """每条合法迁移按预期产生 to_status"""
    assert transition(from_status, action, role) == to_status


def test_invalid_action_raises():
    """未注册的 action 抛 ValueError"""
    with pytest.raises(ValueError, match="非法操作"):
        transition(RequestStatus.pending_audit, "bogus_action", OperatorRole.supervisor)


def test_invalid_role_for_action_raises():
    """合法 action 但角色错(业务员审批)抛 ValueError"""
    with pytest.raises(ValueError, match="非法操作"):
        transition(RequestStatus.pending_audit, "approve", OperatorRole.salesperson)


def test_terminal_state_no_transitions():
    """终止状态(completed)不允许任何操作"""
    with pytest.raises(ValueError):
        transition(RequestStatus.completed, "start", OperatorRole.design_staff)


def test_rejected_state_no_transitions():
    """rejected 也是终止态"""
    with pytest.raises(ValueError):
        transition(RequestStatus.rejected, "approve", OperatorRole.supervisor)


def test_cancelled_state_no_transitions():
    """cancelled 也是终止态"""
    with pytest.raises(ValueError):
        transition(RequestStatus.cancelled, "start", OperatorRole.design_staff)
