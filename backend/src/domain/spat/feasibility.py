"""Formal feasibility states for an evaluated grounding design (OPT-005).

Every `Vs`/`Vt` the solver reports is attained at a real surface point, so a value above its limit
proves a violation whatever the search. The converse is not true: the searches sample the surface,
and the benchmark found designs that a sampled search declared compliant while a better-sampled
one showed a violation. Compliance is therefore never concluded from sampling alone.

VIOLATED   at least one criterion is exceeded at an evaluated point. Conclusive at every level.
UNKNOWN    no violation was found, or the design could not be assessed. This is the most a sampled
           search can say, however fine the sampling.
CERTIFIED  compliance holds with a justified guarantee, for example a proven upper bound of Vs and
           Vt over the whole search area including discretization error. Reserved: it needs a method
           listed in `CERTIFYING_METHODS`, and none exists yet, so nothing is certified today.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class FeasibilityStatus(str, Enum):
    VIOLATED = "VIOLATED"
    UNKNOWN = "UNKNOWN"
    CERTIFIED = "CERTIFIED"


# Methods whose guarantee has been justified and validated. Deliberately empty.
CERTIFYING_METHODS: frozenset[str] = frozenset()


@dataclass(frozen=True)
class Certificate:
    """The guarantee behind a CERTIFIED claim: which method, what it bounds, and why it holds."""

    method: str
    guarantee: str
    justification: str


def classify(*, violated: bool, evaluable: bool, certificate: Certificate | None = None) -> FeasibilityStatus:
    """VIOLATED beats everything; CERTIFIED needs a registered certifying method; otherwise UNKNOWN."""
    if violated:
        return FeasibilityStatus.VIOLATED
    if certificate is None:
        return FeasibilityStatus.UNKNOWN
    if certificate.method not in CERTIFYING_METHODS:
        raise ValueError(f"method {certificate.method!r} is not a registered certifying method; "
                         "a sampled search cannot certify compliance")
    if not (certificate.guarantee.strip() and certificate.justification.strip()):
        raise ValueError("a certificate must state its guarantee and justification")
    return FeasibilityStatus.CERTIFIED if evaluable else FeasibilityStatus.UNKNOWN
