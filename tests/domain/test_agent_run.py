import pytest

from src.domain.agent.run import (
    ACTIVE, TERMINAL, InvalidTransition, RunStatus, cancellation_target, poll_after_ms, transition,
)


def test_lifecycle_transitions():
    assert transition("queued", "running") == RunStatus.RUNNING
    assert transition("running", "waiting_calculation") == RunStatus.WAITING_CALCULATION
    assert transition("waiting_calculation", "queued") == RunStatus.QUEUED
    assert transition("waiting_user", "queued") == RunStatus.QUEUED
    with pytest.raises(InvalidTransition):
        transition("completed", "running")
    with pytest.raises(InvalidTransition):
        transition("waiting_user", "running")  # a worker resumes only from queued
    with pytest.raises(InvalidTransition):
        transition("waiting_user", "completed")
    assert TERMINAL.isdisjoint(ACTIVE) and TERMINAL | ACTIVE == set(RunStatus)


def test_cancellation_waits_for_running_step_only():
    assert cancellation_target("running") == RunStatus.CANCELLING
    assert cancellation_target("queued") == RunStatus.CANCELLED
    assert cancellation_target("waiting_calculation") == RunStatus.CANCELLED
    assert cancellation_target("cancelling") == RunStatus.CANCELLING
    with pytest.raises(InvalidTransition):
        cancellation_target("completed")


def test_polling_interval_follows_status():
    assert poll_after_ms("running") == 1500
    assert poll_after_ms("waiting_calculation") == 5000
    assert poll_after_ms("waiting_user") is None and poll_after_ms(None) is None
