"""Unit tests for the Verification States lifecycle manager (verification_states.py)."""

from __future__ import annotations

import pytest

from kmcp.intelligence import VerificationStates


@pytest.fixture()
def vs() -> VerificationStates:
    return VerificationStates()


# ── States and transitions ───────────────────────────────────────────


def test_initial_state_is_observed(vs):
    assert vs.get_state("f1") == "observed"


def test_transition_observed_to_suspected(vs):
    ok = vs.transition("f1", "suspected", "analyst1", "Looks likely")
    assert ok is True
    assert vs.get_state("f1") == "suspected"


def test_transition_suspected_to_validated(vs):
    vs.transition("f1", "suspected", "analyst1", "Looks likely")
    ok = vs.transition("f1", "validated", "nuclei", "Template match")
    assert ok is True
    assert vs.get_state("f1") == "validated"


def test_transition_validated_to_remediated(vs):
    vs.transition("f1", "suspected", "analyst1", "Looks likely")
    vs.transition("f1", "validated", "nuclei", "Template match")
    ok = vs.transition("f1", "remediated", "analyst1", "Patched")
    assert ok is True
    assert vs.get_state("f1") == "remediated"


# ── Invalid transitions ──────────────────────────────────────────────


def test_cannot_skip_states(vs):
    # observed -> remediated directly is not allowed
    assert vs.can_transition("observed", "remediated") is False
    ok = vs.transition("f1", "remediated", "analyst1", "Skip")
    assert ok is False
    assert vs.get_state("f1") == "observed"


def test_cannot_transition_from_terminal_state(vs):
    vs.transition("f1", "false_positive", "analyst1", "Not real")
    assert vs.get_state("f1") == "false_positive"
    # Cannot transition out of terminal state
    assert vs.can_transition("false_positive", "validated") is False
    ok = vs.transition("f1", "validated", "analyst1", "Retry")
    assert ok is False
    assert vs.get_state("f1") == "false_positive"


def test_cannot_transition_from_accepted_risk(vs):
    vs.transition("f1", "accepted_risk", "analyst1", "Risk accepted")
    assert vs.can_transition("accepted_risk", "remediated") is False


def test_invalid_state_rejected(vs):
    assert vs.transition("f1", "invalid_state", "tool", "reason") is False


# ── Terminal states ──────────────────────────────────────────────────


def test_false_positive_is_terminal(vs):
    assert vs.is_terminal("false_positive") is True


def test_accepted_risk_is_terminal(vs):
    assert vs.is_terminal("accepted_risk") is True


def test_observed_is_not_terminal(vs):
    assert vs.is_terminal("observed") is False


# ── Any state to false_positive / accepted_risk ──────────────────────


def test_any_state_can_go_to_false_positive(vs):
    for state in ("observed", "suspected", "validated"):
        vs2 = VerificationStates()
        vs2._states["f1"] = state  # set directly
        assert vs2.can_transition(state, "false_positive") is True


def test_any_state_can_go_to_accepted_risk(vs):
    for state in ("observed", "suspected", "validated"):
        vs2 = VerificationStates()
        vs2._states["f1"] = state
        assert vs2.can_transition(state, "accepted_risk") is True


# ── Same-state transition is no-op success ───────────────────────────


def test_same_state_transition_is_noop(vs):
    vs.transition("f1", "suspected", "a", "r")
    ok = vs.transition("f1", "suspected", "a", "r again")
    assert ok is True
    assert vs.get_state("f1") == "suspected"


# ── Transition history ───────────────────────────────────────────────


def test_transition_history_recorded(vs):
    vs.transition("f1", "suspected", "analyst1", "Looks likely")
    vs.transition("f1", "validated", "nuclei", "Template match")
    history = vs.get_transition_history("f1")
    assert len(history) == 2
    assert history[0]["from_state"] == "observed"
    assert history[0]["to_state"] == "suspected"
    assert history[0]["source"] == "analyst1"
    assert history[0]["reason"] == "Looks likely"
    assert history[1]["from_state"] == "suspected"
    assert history[1]["to_state"] == "validated"
    assert history[1]["source"] == "nuclei"
    assert "timestamp" in history[0]


# ── get_findings_by_state ────────────────────────────────────────────


def test_get_findings_by_state(vs):
    vs.transition("f1", "suspected", "a", "r")
    vs.transition("f1", "validated", "a", "r")
    vs.transition("f2", "suspected", "a", "r")
    # f2 stays in suspected
    vs.transition("f3", "suspected", "a", "r")
    vs.transition("f3", "false_positive", "a", "r")
    # f4 remains observed (default) — explicitly set it so it's tracked
    vs.transition("f4", "observed", "system", "initial")
    suspected = vs.get_findings_by_state("suspected")
    assert "f2" in suspected
    validated = vs.get_findings_by_state("validated")
    assert "f1" in validated
    fp = vs.get_findings_by_state("false_positive")
    assert "f3" in fp
    observed = vs.get_findings_by_state("observed")
    assert "f4" in observed


# ── list_states ──────────────────────────────────────────────────────


def test_list_states(vs):
    vs.transition("f1", "suspected", "a", "r")
    states = vs.list_states()
    assert states["f1"] == "suspected"
    # f2 not yet seen → not in dict
    assert "f2" not in states
