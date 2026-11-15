"""Adaptive choice among atomic and large-neighbourhood moves (OPT-011).

Arms are the nine atomic operator kinds (eight proposable at random) and the six destroy-and-repair
pairs of `geometry_lns`. Each arm has a weight, and moves are drawn by roulette on the weights. Every
`segment` outcomes the weights are re-estimated the way adaptive large-neighbourhood search does:
  w <- (1 - reaction) * w + reaction * (score earned in the segment / times used)
with these scores: a new incumbent 10, a move that improves the current design 5, a new valid design
that does not improve it 2, anything invalid or already seen 0. An arm that stops paying loses weight
(never below `floor`), and one that starts paying gains it.

Two contexts keep separate weights, because what repairs a violating design is not what makes a compliant
one cheaper: "improve" (the current design complies) and "repair" (it violates). In the repair context the
atomic arms that add conductors and rods start with the prior of `geometry_operators.REPAIR_WEIGHTS`.

The selector is plain, deterministic state: it draws only from the search's random generator and learns only
from outcomes that the search reproduces exactly on a replay, so a resumed run ends with the same weights.
"""

from __future__ import annotations

import random
from collections import Counter

from src.domain.spat import geometry_graph as gg
from src.domain.spat.geometry_lns import DESTROY, REPAIR, make_region, plan
from src.domain.spat.geometry_operators import KINDS, REPAIR_WEIGHTS, OperatorConstraints, random_operator

SCORES = {"incumbent": 10.0, "improving": 5.0, "novel": 2.0, "duplicate": 0.0, "invalid": 0.0}
LNS_ARMS = tuple(f"lns:{d}+{r}" for d in DESTROY for r in REPAIR)
ARMS = tuple(f"atomic:{k}" for k in KINDS) + LNS_ARMS


class AdaptiveOperatorSelector:
    def __init__(self, domain: dict, constraints: OperatorConstraints = OperatorConstraints(), *,
                 reaction: float = 0.3, segment: int = 20, floor: float = 0.05, use_lns: bool = True,
                 plan_attempts: int = 3, scores: dict[str, float] | None = None):
        self.domain, self.constraints = domain, constraints
        self.reaction, self.segment, self.floor, self.plan_attempts = reaction, segment, floor, plan_attempts
        self.scores = {**SCORES, **(scores or {})}
        self.arms = ARMS if use_lns else tuple(a for a in ARMS if not a.startswith("lns:"))
        self.region = make_region(domain)
        prior = dict(zip((f"atomic:{k}" for k in KINDS), REPAIR_WEIGHTS))
        self.weights = {"improve": {a: 1.0 for a in self.arms},
                        "repair": {a: prior.get(a, 1.0) for a in self.arms}}
        self._score: dict[str, Counter] = {"improve": Counter(), "repair": Counter()}
        self._uses: dict[str, Counter] = {"improve": Counter(), "repair": Counter()}
        self._since = Counter()
        self.history: Counter = Counter()          # (context, arm, outcome) -> count, for reporting

    def propose(self, graph: gg.GeometryGraph, rng: random.Random, repairing: bool):
        context = "repair" if repairing else "improve"
        weights = self.weights[context]
        point, cumulative = rng.random() * sum(weights[a] for a in self.arms), 0.0
        arm = self.arms[-1]
        for candidate in self.arms:
            cumulative += weights[candidate]
            if point <= cumulative:
                arm = candidate
                break
        if arm.startswith("lns:"):
            destroy, repair = arm[4:].split("+")
            # A plan often fails for want of a fitting region or limb: draw again before giving up on the arm.
            for _ in range(self.plan_attempts):
                move = plan(graph, rng, destroy, repair, self.region, self.constraints)
                if move is not None:
                    return arm, move
            return arm, None
        return arm, random_operator(graph, rng, kind=arm[7:], orthogonal=self.constraints.orthogonal)

    def report(self, arm: str, outcome: str, repairing: bool) -> None:
        context = "repair" if repairing else "improve"
        self._score[context][arm] += self.scores[outcome]
        self._uses[context][arm] += 1
        self.history[(context, arm, outcome)] += 1
        self._since[context] += 1
        if self._since[context] >= self.segment:
            for name in self.arms:
                if self._uses[context][name]:
                    estimate = self._score[context][name] / self._uses[context][name]
                    self.weights[context][name] = max(self.floor, (1 - self.reaction) * self.weights[context][name] + self.reaction * estimate)
            self._score[context].clear()
            self._uses[context].clear()
            self._since[context] = 0

    def stats(self) -> dict:
        rows: dict = {}
        for (context, arm, outcome), count in sorted(self.history.items()):
            rows.setdefault(context, {}).setdefault(arm, Counter())[outcome] += count
        return {"weights": {c: {a: round(w, 3) for a, w in ws.items()} for c, ws in self.weights.items()},
                "outcomes": {c: {a: dict(o) for a, o in arms.items()} for c, arms in rows.items()}}
