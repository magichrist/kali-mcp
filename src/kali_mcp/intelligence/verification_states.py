"""Finding Lifecycle Manager — verification state transitions.

Manages the lifecycle of findings through states:

    observed → suspected → validated → remediated

Terminal states: false_positive, accepted_risk (no outgoing transitions).

Each transition records a timestamp, source (tool or analyst), and reason.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat() + "Z"


# All valid lifecycle states
STATES = {
    "observed",
    "suspected",
    "validated",
    "remediated",
    "false_positive",
    "accepted_risk",
}

# Terminal states — no outgoing transitions
TERMINAL_STATES = {"false_positive", "accepted_risk"}

# Allowed transitions: from_state -> set of to_states
_TRANSITIONS: dict[str, set[str]] = {
    "observed": {"suspected", "false_positive", "accepted_risk"},
    "suspected": {"validated", "false_positive", "accepted_risk"},
    "validated": {"remediated", "false_positive", "accepted_risk"},
    "remediated": set(),  # no further transitions
    "false_positive": set(),  # terminal
    "accepted_risk": set(),  # terminal
}


@dataclass
class StateTransition:
    """A single lifecycle state transition record."""

    finding_id: str
    from_state: str
    to_state: str
    source: str  # tool name or analyst identifier
    reason: str
    timestamp: str = field(default_factory=_now_utc)

    def to_dict(self) -> dict[str, Any]:
        return {
            "finding_id": self.finding_id,
            "from_state": self.from_state,
            "to_state": self.to_state,
            "source": self.source,
            "reason": self.reason,
            "timestamp": self.timestamp,
        }


class VerificationStates:
    """Manages finding lifecycle state transitions and history."""

    def __init__(self) -> None:
        self._states: dict[str, str] = {}  # finding_id -> current state
        self._history: dict[str, list[StateTransition]] = {}  # finding_id -> transitions

    # ── public API ────────────────────────────────────────────────────

    def transition(self, finding_id: str, new_state: str, source: str, reason: str) -> bool:
        """Transition a finding to a new lifecycle state.

        Args:
            finding_id: The finding to transition.
            new_state: Target state (observed, suspected, validated,
                remediated, false_positive, accepted_risk).
            source: Who/what initiated the transition (tool or analyst).
            reason: Human-readable reason for the transition.

        Returns:
            True if the transition succeeded, False if invalid.
        """
        if new_state not in STATES:
            return False

        current = self._states.get(finding_id, "observed")

        # Same-state transition: record the finding as tracked, no history entry
        if current == new_state:
            self._states[finding_id] = new_state
            return True

        if not self.can_transition(current, new_state):
            return False

        transition = StateTransition(
            finding_id=finding_id,
            from_state=current,
            to_state=new_state,
            source=source,
            reason=reason,
        )
        self._states[finding_id] = new_state
        self._history.setdefault(finding_id, []).append(transition)
        return True

    def get_state(self, finding_id: str) -> str:
        """Return the current lifecycle state of a finding."""
        return self._states.get(finding_id, "observed")

    def can_transition(self, from_state: str, to_state: str) -> bool:
        """Return True if a transition from_state → to_state is allowed."""
        if from_state not in STATES or to_state not in STATES:
            return False
        if from_state in TERMINAL_STATES:
            return False
        return to_state in _TRANSITIONS.get(from_state, set())

    def get_findings_by_state(self, state: str) -> list[str]:
        """Return list of finding IDs currently in the given state."""
        return [fid for fid, st in self._states.items() if st == state]

    def get_transition_history(self, finding_id: str) -> list[dict[str, Any]]:
        """Return the full transition history for a finding."""
        return [t.to_dict() for t in self._history.get(finding_id, [])]

    def list_states(self) -> dict[str, str]:
        """Return a copy of all finding_id → state mappings."""
        return dict(self._states)

    def is_terminal(self, state: str) -> bool:
        """Return True if the state is terminal (false_positive or accepted_risk)."""
        return state in TERMINAL_STATES
