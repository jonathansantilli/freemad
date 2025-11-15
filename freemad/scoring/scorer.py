from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Set

from freemad import Config
from freemad import ScoreAction


@dataclass(frozen=True)
class ScoreEvent:
    round: int
    agent_id: str
    action: ScoreAction  # initial|keep|change
    deltas: Dict[str, float]  # {answer_id: delta}
    contributors: Dict[str, int]  # after this event


class ScoreTracker:
    """Implements FREE-MAD scoring with decay and contributor-based normalization.

    Raw score per answer accumulates event deltas. Normalized score is
    raw / contributors_count(answer).
    """

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self._raw: Dict[str, float] = {}  # answer_id -> raw score
        self._contributors: Dict[str, Set[str]] = {}  # answer_id -> set(agent_id)
        self._history: Dict[str, List[ScoreEvent]] = {}  # answer_id -> events

    def _decay(self, round_idx: int) -> float:
        return 1.0 / (round_idx + 1)

    def _add(self, answer_id: str, delta: float, contributor: Optional[str], round_idx: int, agent_id: str, action: str) -> None:
        self._raw[answer_id] = self._raw.get(answer_id, 0.0) + delta
        if contributor:
            s = self._contributors.setdefault(answer_id, set())
            s.add(contributor)
        # record event snapshot
        contrib_counts = {k: len(v) for k, v in self._contributors.items()}
        ev = ScoreEvent(round=round_idx, agent_id=agent_id, action=ScoreAction(action), deltas={answer_id: delta}, contributors=contrib_counts)
        self._history.setdefault(answer_id, []).append(ev)

    def record_initial(self, *, agent_id: str, answer_id: str, round_idx: int = 0) -> None:
        f = self._decay(round_idx)
        w1, _, _, _ = self.cfg.scoring.weights
        self._add(answer_id, w1 * f, contributor=agent_id, round_idx=round_idx, agent_id=agent_id, action=ScoreAction.INITIAL.value)

    def record_keep(self, *, agent_id: str, answer_id: str, round_idx: int) -> None:
        f = self._decay(round_idx)
        _, _, _, w4 = self.cfg.scoring.weights
        self._add(answer_id, w4 * f, contributor=agent_id, round_idx=round_idx, agent_id=agent_id, action=ScoreAction.KEEP.value)

    def record_change(self, *, agent_id: str, old_answer_id: str, new_answer_id: str, round_idx: int) -> None:
        f = self._decay(round_idx)
        _, w2, w3, _ = self.cfg.scoring.weights
        # penalize old answer
        self._add(old_answer_id, -w2 * f, contributor=None, round_idx=round_idx, agent_id=agent_id, action=ScoreAction.CHANGE.value)
        # reward new answer and add contributor
        self._add(new_answer_id, w3 * f, contributor=agent_id, round_idx=round_idx, agent_id=agent_id, action=ScoreAction.CHANGE.value)

    def get_raw_scores(self) -> Dict[str, float]:
        return dict(self._raw)

    def get_all_scores(self) -> Dict[str, float]:
        out: Dict[str, float] = {}
        for ans, raw in self._raw.items():
            c = max(1, len(self._contributors.get(ans, set()))) if self.cfg.scoring.normalize else 1
            out[ans] = raw / c
        return out

    def explain_score(self, answer_id: str) -> List[ScoreEvent]:
        return list(self._history.get(answer_id, []))
