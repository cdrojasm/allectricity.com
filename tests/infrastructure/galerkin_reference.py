"""Independent Galerkin reference for the potential engine's thin-wire system (SV-04).

Same physical model as the engine (piecewise-constant current per segment, reduced kernel
1/sqrt(d^2 + a^2) with the source radius a, equal potential over the segments of a group, insulating
air boundary by images) and none of its numerics: the target-segment average of the potential of
each source image is integrated with adaptive QUADPACK (`scipy.integrate.quad`) split at every point
where the integrand has a kink or a peak, and the system is assembled and solved with numpy.
The inner line integral uses the textbook closed form for the reduced kernel, checked against
numerical quadrature in `test_inner_closed_form_matches_numerical_quadrature`.

Soil: homogeneous, or two-layer (Sunde/Tagg image series) written here from the published point-source
formulas in terms of source depth s and observation depth t, not copied from the engine's tables.

Units: coefficients are in 1/m (multiply by rho/4pi for ohm).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from scipy.integrate import quad

Vec = np.ndarray

_GL_X, _GL_W = np.polynomial.legendre.leggauss(24)


@dataclass(frozen=True)
class Seg:
    a: tuple[float, float, float]
    b: tuple[float, float, float]
    radius: float
    group: str = "g"

    @property
    def length(self) -> float:
        return float(np.linalg.norm(np.subtract(self.b, self.a)))

    @property
    def mid_depth(self) -> float:
        return -0.5 * (self.a[2] + self.b[2])


def line_integral(p: Vec, a: Vec, b: Vec, radius: float) -> float:
    """Integral of 1/sqrt(|p - x|^2 + radius^2) along the straight segment a-b."""
    length = float(np.linalg.norm(b - a))
    d = (b - a) / length
    t = float(np.dot(p - a, d))
    perp2 = max(float(np.dot(p - a, p - a)) - t * t, 0.0)
    rho = math.sqrt(perp2 + radius * radius)
    return math.asinh((length - t) / rho) + math.asinh(t / rho)


def _kinks(target: Seg, a: Vec, b: Vec) -> list[float]:
    """Target parameters where the inner integral changes character: projection onto the source
    ends, and the closest approach (sampled, then refined)."""
    ta, tb = np.asarray(target.a, float), np.asarray(target.b, float)
    length = float(np.linalg.norm(b - a))
    d = (b - a) / length
    points: set[float] = set()
    delta = float(np.dot(tb - ta, d))
    for end in (0.0, length):
        if abs(delta) > 1e-14:
            points.add(float((end - np.dot(ta - a, d)) / delta))
    us = np.linspace(0.0, 1.0, 401)
    dist = []
    for u in us:
        p = ta + (tb - ta) * u
        t = min(max(float(np.dot(p - a, d)), 0.0), length)
        dist.append(float(np.linalg.norm(p - (a + d * t))))
    k = int(np.argmin(dist))
    points.update(float(us[j]) for j in (k - 1, k, k + 1) if 0 <= j <= 400)
    return sorted(u for u in points if 1e-12 < u < 1 - 1e-12)


def image_coefficient(target: Seg, source: Seg, a: Vec, b: Vec) -> float:
    """Average over `target` of the potential of the image segment a-b carrying unit total current
    (1/m): (1/L_s) * integral_0^1 line_integral(x(u)) du."""
    ta, tb = np.asarray(target.a, float), np.asarray(target.b, float)
    r = source.radius

    def f(u: float) -> float:
        return line_integral(ta + (tb - ta) * u, a, b, r)

    scale = float(np.linalg.norm(b - a))
    span = float(np.linalg.norm(tb - ta))
    gap = min(float(np.linalg.norm(0.5 * (ta + tb) - 0.5 * (a + b))), 1e99)
    if gap > 6.0 * (scale + span):  # smooth: fixed 24-point Gauss-Legendre is exact to double precision
        total = 0.5 * sum(w * f(0.5 * (x + 1.0)) for x, w in zip(_GL_X, _GL_W))
    else:
        total, _ = quad(f, 0.0, 1.0, points=_kinks(target, a, b) or None, limit=500, epsabs=0.0, epsrel=1e-12)
    return total / scale


def _mirror(p: Vec) -> Vec:
    return np.array([p[0], p[1], -p[2]])


def depth_image(source: Seg, sign: float, offset: float) -> tuple[Vec, Vec]:
    """Source segment mapped to depth s_img = sign * s + offset (depth = -z)."""
    def move(p):
        return np.array([p[0], p[1], -(sign * (-p[2]) + offset)])
    return move(np.asarray(source.a, float)), move(np.asarray(source.b, float))


# ---- soil models: list of (weight relative to rho_ref, sign, offset) for (source layer, observation layer)

@dataclass(frozen=True)
class Homogeneous:
    rho: float

    def layer(self, depth: float) -> int:
        return 0

    @property
    def rho_ref(self) -> float:
        return self.rho

    def images(self, src_layer: int, obs_layer: int, s_unused: float = 0.0) -> list[tuple[float, float, float]]:
        return [(1.0, 1.0, 0.0), (1.0, -1.0, 0.0)]


@dataclass(frozen=True)
class TwoLayer:
    rho1: float
    rho2: float
    h: float
    tolerance: float = 1e-13

    @property
    def rho_ref(self) -> float:
        return self.rho1

    @property
    def k(self) -> float:
        return (self.rho2 - self.rho1) / (self.rho2 + self.rho1)

    def layer(self, depth: float) -> int:
        return 0 if depth < self.h else 1

    def _terms(self) -> int:
        k = abs(self.k)
        if k == 0.0:
            return 0
        return min(int(math.ceil(math.log(self.tolerance) / math.log(k))) + 2, 20000)

    def images(self, src_layer: int, obs_layer: int, s_unused: float = 0.0) -> list[tuple[float, float, float]]:
        k, h, n_max = self.k, self.h, self._terms()
        if (src_layer, obs_layer) == (0, 0):
            out = [(1.0, 1.0, 0.0), (1.0, -1.0, 0.0)]
            for n in range(1, n_max + 1):
                for sgn in (1, -1):  # n and -n terms: 1/R(t-s+2nh) -> s_img = s - 2nh; 1/R(t+s+2nh) -> s_img = -s - 2nh
                    out += [(k ** n, 1.0, -2.0 * n * h * sgn), (k ** n, -1.0, -2.0 * n * h * sgn)]
            return out
        if (src_layer, obs_layer) == (0, 1):
            # (1 + K) K^n [1/R(t - s + 2nh) + 1/R(t + s + 2nh)]
            return [item for n in range(n_max + 1)
                    for item in [((1 + k) * k ** n, 1.0, -2.0 * n * h), ((1 + k) * k ** n, -1.0, -2.0 * n * h)]]
        if (src_layer, obs_layer) == (1, 0):
            # (1 + K) K^n [1/R(s - t + 2nh) + 1/R(s + t + 2nh)]
            return [item for n in range(n_max + 1)
                    for item in [((1 + k) * k ** n, 1.0, 2.0 * n * h), ((1 + k) * k ** n, -1.0, -2.0 * n * h)]]
        r = self.rho2 / self.rho1
        out = [(r, 1.0, 0.0), (-r * k, -1.0, 2.0 * h)]
        out += [(r * (1 - k * k) * k ** n, -1.0, -2.0 * n * h) for n in range(n_max + 1)]
        return out


def coefficient(target: Seg, source: Seg, soil) -> float:
    """Galerkin coefficient (1/m, relative to rho_ref / 4 pi) for a target and a source segment."""
    sl, tl = soil.layer(source.mid_depth), soil.layer(target.mid_depth)
    total = 0.0
    for weight, sign, offset in soil.images(sl, tl):
        a, b = depth_image(source, sign, offset)
        total += weight * image_coefficient(target, source, a, b)
    return total


@dataclass
class Solution:
    resistance_ohm: float
    currents_a: np.ndarray
    matrix: np.ndarray


def solve_group(segments: list[Seg], soil, current_a: float = 1.0) -> Solution:
    """Single equipotential group injecting `current_a`: returns the resistance to remote earth and
    the per-segment currents."""
    n = len(segments)
    z = np.empty((n, n))
    for i, target in enumerate(segments):
        for j, source in enumerate(segments):
            z[i, j] = coefficient(target, source, soil)
    z *= soil.rho_ref / (4.0 * math.pi)
    system = np.zeros((n + 1, n + 1))
    system[:n, :n] = z
    system[:n, n] = -1.0
    system[n, :n] = 1.0
    rhs = np.zeros(n + 1)
    rhs[n] = current_a
    x = np.linalg.solve(system, rhs)
    return Solution(resistance_ohm=float(x[n] / current_a), currents_a=x[:n], matrix=z)
