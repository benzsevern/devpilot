import pytest

from devpilot.recovery.strategy import (
    RecoveryStrategy,
    RecoveryAction,
    RecoveryTier,
)


@pytest.fixture
def strategy():
    return RecoveryStrategy(max_retries=3, backoff_seconds=[1, 3, 5])


def test_first_crash_is_tier1_restart(strategy):
    action = strategy.on_crash("backend", attempt=1)
    assert action.tier == RecoveryTier.SILENT
    assert action.action == "restart"
    assert action.delay == 1


def test_second_crash_backoff(strategy):
    action = strategy.on_crash("backend", attempt=2)
    assert action.tier == RecoveryTier.SILENT
    assert action.delay == 3


def test_third_crash_still_restarts(strategy):
    action = strategy.on_crash("backend", attempt=3)
    assert action.tier == RecoveryTier.REPORT
    assert action.action == "restart"


def test_fourth_crash_escalates(strategy):
    action = strategy.on_crash("backend", attempt=4)
    assert action.tier == RecoveryTier.ESCALATE
    assert action.action == "report"


def test_port_conflict_with_flag_support(strategy):
    action = strategy.on_port_conflict("backend", supports_port_flag=True)
    assert action.tier == RecoveryTier.REPORT
    assert action.action == "reassign_port"


def test_port_conflict_without_flag_support(strategy):
    action = strategy.on_port_conflict("backend", supports_port_flag=False)
    assert action.tier == RecoveryTier.ESCALATE
    assert action.action == "report"


def test_reload_failed_escalates(strategy):
    action = strategy.on_reload_failed("backend", error="SyntaxError: ...")
    assert action.tier == RecoveryTier.ESCALATE
    assert action.action == "report"


def test_attached_crash_escalates(strategy):
    action = strategy.on_attached_crash("frontend", cmd="npm run dev")
    assert action.tier == RecoveryTier.ESCALATE
    assert "devpilot run" in action.suggestion


def test_unknown_port_holder_escalates(strategy):
    action = strategy.on_unknown_port_holder("backend", port=8000, holder_pid=999, holder_name="node")
    assert action.tier == RecoveryTier.ESCALATE
    assert "node" in action.suggestion
