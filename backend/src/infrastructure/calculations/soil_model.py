"""Two-layer soil model from Wenner or Schlumberger resistivity soundings.

Forward model: the potential of a point current source on the surface of a two-layer earth is
the image series

    V(r) = rho1 I / (2 pi) * [1/r + 2 sum_{n>=1} K^n / sqrt(r^2 + (2 n h)^2)],   K = (rho2 - rho1)/(rho2 + rho1)

(E. D. Sunde, "Earth Conduction Effects in Transmission Systems", Van Nostrand, 1949, ch. 2;
G. F. Tagg, "Earth Resistances", Newnes, 1964, ch. 4). Superposing the four electrodes of any
surface array gives the apparent resistivity; for the Wenner array this reduces to Tagg's formula

    rho_a = rho1 [1 + 4 sum K^n (1/sqrt(1 + (2nh/a)^2) - 1/sqrt(4 + (2nh/a)^2))].

Inversion: least squares in log apparent resistivity over ln(rho1), ln(rho2), ln(h) with a
Levenberg-Marquardt iteration from several starting points. Readings whose relative residual
exceeds `outlier_threshold` are excluded one at a time (worst first) while enough points remain.

Out of scope: models with more than two layers. The usual linear Hankel-filter forward model needs
published filter coefficients that are not reproduced here; add it with a cited coefficient set.
Pure standard library on purpose: the backend has no numpy/scipy dependency.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from math import exp, isfinite, log, sqrt

WENNER = "wenner"
SCHLUMBERGER = "schlumberger"
ARRAYS = (WENNER, SCHLUMBERGER)
MIN_POINTS = 4
DEFAULT_OUTLIER_THRESHOLD = 0.15  # 15 % relative residual
MIN_RHO_OHM_M, MAX_RHO_OHM_M = 1e-2, 1e7
# Search bounds: |K| <= 0.998 and h within two decades of the measured spacings. Beyond them the
# image series converges too slowly and a sounding cannot resolve the parameters anyway.
MAX_RESISTIVITY_RATIO = 1e3
H_SPACING_FACTOR = 100.0
SERIES_TOLERANCE = 1e-9
NEAR_UNIFORM_K = 0.02


@dataclass(frozen=True)
class ResistivityMeasurement:
    """One sounding reading.

    `spacing_m` is the Wenner probe spacing a, or the Schlumberger half current-electrode spacing
    AB/2. `potential_spacing_m` is the Schlumberger potential-electrode spacing MN (not used for
    Wenner).
    """

    spacing_m: float
    apparent_resistivity_ohm_m: float
    potential_spacing_m: float | None = None


@dataclass(frozen=True)
class TwoLayerSoil:
    rho1_ohm_m: float
    rho2_ohm_m: float
    h_m: float  # thickness of the upper layer

    @property
    def k(self) -> float:
        return (self.rho2_ohm_m - self.rho1_ohm_m) / (self.rho2_ohm_m + self.rho1_ohm_m)


@dataclass(frozen=True)
class SoilModelFit:
    array: str
    model: TwoLayerSoil
    rms_error_percent: float
    # One-sigma relative uncertainty of rho1, rho2 and h from the Jacobian; None if not identifiable.
    relative_uncertainty_percent: dict[str, float | None]
    residuals_percent: list[float]  # model/measured - 1 for every input reading, in %
    excluded: list[int]  # indices of readings excluded as outliers
    uniform_resistivity_ohm_m: float
    uniform_rms_error_percent: float
    iterations: int
    warnings: list[str] = field(default_factory=list)


def _electrodes(array: str, spacing: float, potential_spacing: float | None) -> list[tuple[float, float]]:
    """(sign, distance) of the four current-potential electrode pairs: AM, AN, BM, BN."""
    if array == WENNER:
        a = spacing
        return [(1.0, a), (-1.0, 2 * a), (-1.0, 2 * a), (1.0, a)]
    s, b = spacing, potential_spacing
    return [(1.0, s - b / 2), (-1.0, s + b / 2), (-1.0, s + b / 2), (1.0, s - b / 2)]


_GAUSS_NODES = (-0.9602898564975363, -0.7966664774136267, -0.5255324099163290, -0.1834346424956498,
                0.1834346424956498, 0.5255324099163290, 0.7966664774136267, 0.9602898564975363)
_GAUSS_WEIGHTS = (0.1012285362903763, 0.2223810344533745, 0.3137066458778873, 0.3626837833783620,
                  0.3626837833783620, 0.3137066458778873, 0.2223810344533745, 0.1012285362903763)
DIRECT_TERMS = 200


def _tail(g, x0: float, scale: float) -> float:
    """Euler-Maclaurin estimate of sum_{m >= x0} g(m) for a smooth, decaying g.

    sum ~= integral_{x0}^{inf} g + g(x0)/2 - g'(x0)/12; the integral uses 8-point Gauss-Legendre on
    geometrically growing intervals. Accurate when g varies slowly over unit steps, which holds once
    the direct sum has passed DIRECT_TERMS terms (see `apparent_resistivity`).
    """
    total, left, width = 0.0, x0, max(scale, 1.0)
    for _ in range(200):
        right = left + width
        part = 0.5 * width * sum(w * g(left + 0.5 * width * (x + 1.0)) for x, w in zip(_GAUSS_NODES, _GAUSS_WEIGHTS))
        total += part
        if abs(part) < SERIES_TOLERANCE * 1e-3 * (1.0 + abs(total)):
            break
        left, width = right, 2.0 * width
    derivative = (g(x0 + 0.5) - g(x0 - 0.5))
    return total + 0.5 * g(x0) - derivative / 12.0


def apparent_resistivity(soil: TwoLayerSoil, array: str, spacing_m: float,
                         potential_spacing_m: float | None = None) -> float:
    """Apparent resistivity (ohm-m) a surface array reads over a two-layer earth."""
    pairs = _electrodes(array, spacing_m, potential_spacing_m)
    geometric = sum(sign / r for sign, r in pairs)
    k, two_h = soil.k, 2.0 * soil.h_m

    def f(n: float) -> float:
        z2 = (n * two_h) ** 2
        return sum(sign / sqrt(r * r + z2) for sign, r in pairs) / geometric

    total, power = 0.0, 1.0
    for n in range(1, DIRECT_TERMS + 1):
        power *= k
        if power == 0.0:
            return soil.rho1_ohm_m * (1.0 + 2.0 * total)
        term = power * f(n)
        total += term
        # Terms fall as K^n / n^3 (the four-electrode sum cancels the 1/z and 1/z^2 orders),
        # so the remainder after n is at most about |term| * max(n / 2, |K| / (1 - |K|)).
        tail = abs(term) * max(n / 2.0, abs(k) / max(1.0 - abs(k), 1e-12))
        if tail < SERIES_TOLERANCE * (1.0 + abs(total)):
            return soil.rho1_ohm_m * (1.0 + 2.0 * total)
    # Slowly converging case: thin upper layer and strong contrast. Sum the rest as an integral of
    # a smooth function; for K < 0, pair consecutive terms so the summand does not alternate.
    q = abs(k)
    scale = max(spacing_m / two_h, 1.0 / max(-log(q), 1e-12))
    if k > 0:
        rest = _tail(lambda x: exp(x * log(q)) * f(x), DIRECT_TERMS + 1.0, scale)
    else:
        m0 = (DIRECT_TERMS + 2) // 2  # pairs (2m-1, 2m) start right after the direct sum
        rest = _tail(lambda m: exp((2 * m - 1) * log(q)) * (-f(2 * m - 1) + q * f(2 * m)), float(m0), scale / 2)
    return soil.rho1_ohm_m * (1.0 + 2.0 * (total + rest))


def _validate(measurements: list[ResistivityMeasurement], array: str) -> list[str]:
    if array not in ARRAYS:
        raise ValueError(f"array must be one of {ARRAYS}")
    if len(measurements) < MIN_POINTS:
        raise ValueError(f"at least {MIN_POINTS} readings are required to fit rho1, rho2 and h")
    warnings: list[str] = []
    previous = 0.0
    for index, m in enumerate(measurements):
        values = [m.spacing_m, m.apparent_resistivity_ohm_m]
        if not all(isinstance(v, (int, float)) and isfinite(v) and v > 0 for v in values):
            raise ValueError(f"reading {index}: spacing and apparent resistivity must be positive finite numbers")
        if m.spacing_m <= previous:
            raise ValueError("spacings must be strictly increasing")
        previous = m.spacing_m
        if array == SCHLUMBERGER:
            b = m.potential_spacing_m
            if b is None or not isfinite(b) or b <= 0:
                raise ValueError(f"reading {index}: Schlumberger readings need a positive MN spacing")
            if b >= 2 * m.spacing_m:
                raise ValueError(f"reading {index}: MN must be smaller than AB")
            if b > 2 * m.spacing_m / 5:
                warnings.append(f"Lectura {index}: MN supera AB/5; la aproximación de Schlumberger pierde precisión.")
    return warnings


def _model(theta: list[float]) -> TwoLayerSoil:
    return TwoLayerSoil(exp(theta[0]), exp(theta[1]), exp(theta[2]))


def _clamp(theta: list[float], readings) -> list[float]:
    rho_low, rho_high = log(MIN_RHO_OHM_M), log(MAX_RHO_OHM_M)
    rho1 = min(max(theta[0], rho_low), rho_high)
    ratio = log(MAX_RESISTIVITY_RATIO)
    rho2 = min(max(theta[1], rho1 - ratio, rho_low), rho1 + ratio, rho_high)
    h_low = log(readings[0].spacing_m / H_SPACING_FACTOR)
    h_high = log(readings[-1].spacing_m * H_SPACING_FACTOR)
    return [rho1, rho2, min(max(theta[2], h_low), h_high)]


def _residuals(theta, readings, array) -> list[float]:
    soil = _model(theta)
    return [log(apparent_resistivity(soil, array, m.spacing_m, m.potential_spacing_m))
            - log(m.apparent_resistivity_ohm_m) for m in readings]


def _jacobian(theta, readings, array, step=1e-6) -> list[list[float]]:
    columns = []
    for p in range(3):
        up, down = list(theta), list(theta)
        up[p] += step
        down[p] -= step
        r_up, r_down = _residuals(up, readings, array), _residuals(down, readings, array)
        columns.append([(u - d) / (2 * step) for u, d in zip(r_up, r_down)])
    return [[columns[p][i] for p in range(3)] for i in range(len(readings))]


def _solve3(a: list[list[float]], b: list[float]) -> list[float] | None:
    """Gaussian elimination with partial pivoting for a 3x3 system."""
    m = [row[:] + [v] for row, v in zip(a, b)]
    for col in range(3):
        pivot = max(range(col, 3), key=lambda r: abs(m[r][col]))
        if abs(m[pivot][col]) < 1e-300:
            return None
        m[col], m[pivot] = m[pivot], m[col]
        for r in range(3):
            if r != col:
                factor = m[r][col] / m[col][col]
                for c in range(col, 4):
                    m[r][c] -= factor * m[col][c]
    return [m[i][3] / m[i][i] for i in range(3)]


def _normal(jac, res):
    a = [[sum(row[i] * row[j] for row in jac) for j in range(3)] for i in range(3)]
    g = [sum(row[i] * r for row, r in zip(jac, res)) for i in range(3)]
    return a, g


def _levenberg_marquardt(theta, readings, array, max_iterations=200):
    theta = _clamp(theta, readings)
    res = _residuals(theta, readings, array)
    ssr = sum(r * r for r in res)
    damping, iterations = 1e-3, 0
    for iterations in range(1, max_iterations + 1):
        a, g = _normal(_jacobian(theta, readings, array), res)
        improved = False
        while damping < 1e12:
            damped = [[a[i][j] + (damping * a[i][i] if i == j else 0.0) for j in range(3)] for i in range(3)]
            for i in range(3):
                damped[i][i] += 1e-15
            step = _solve3(damped, [-v for v in g])
            if step is None:
                damping *= 10
                continue
            candidate = _clamp([t + s for t, s in zip(theta, step)], readings)
            candidate_res = _residuals(candidate, readings, array)
            candidate_ssr = sum(r * r for r in candidate_res)
            if candidate_ssr < ssr:
                done = ssr - candidate_ssr < 1e-14 * (1.0 + ssr) or max(abs(s) for s in step) < 1e-10
                theta, res, ssr = candidate, candidate_res, candidate_ssr
                damping = max(damping / 10, 1e-12)
                improved = True
                break
            damping *= 10
        if not improved or done:
            break
    return theta, ssr, iterations


def _fit(readings, array):
    rho_first = readings[0].apparent_resistivity_ohm_m
    rho_last = readings[-1].apparent_resistivity_ohm_m
    spans = [readings[0].spacing_m * f for f in (0.1, 0.3, 1.0)] + [m.spacing_m for m in readings[1::2]]
    starts = []
    for h in spans:
        starts.append([log(rho_first), log(rho_last), log(h)])
        starts.append([log(rho_first), log(rho_last * (rho_last / rho_first)), log(h)])
    best = None
    for start in starts:
        theta, ssr, iterations = _levenberg_marquardt(start, readings, array)
        if best is None or ssr < best[1]:
            best = (theta, ssr, iterations)
    return best


def _relative(soil: TwoLayerSoil, readings, array) -> list[float]:
    return [apparent_resistivity(soil, array, m.spacing_m, m.potential_spacing_m) / m.apparent_resistivity_ohm_m - 1.0
            for m in readings]


def fit_two_layer(measurements: list[ResistivityMeasurement], array: str = WENNER,
                  outlier_threshold: float = DEFAULT_OUTLIER_THRESHOLD) -> SoilModelFit:
    """Fit rho1, rho2 and h to a resistivity sounding; see the module docstring for the method."""
    warnings = _validate(measurements, array)
    if not 0 < outlier_threshold < 1:
        raise ValueError("outlier_threshold must be between 0 and 1")
    kept = list(range(len(measurements)))
    excluded: list[int] = []
    while True:
        readings = [measurements[i] for i in kept]
        theta, ssr, iterations = _fit(readings, array)
        relative = _relative(_model(theta), readings, array)
        worst = max(range(len(kept)), key=lambda i: abs(relative[i]))
        if abs(relative[worst]) <= outlier_threshold or len(kept) - 1 < MIN_POINTS:
            break
        excluded.append(kept.pop(worst))
    soil = _model(theta)
    if excluded:
        warnings.append(f"Lecturas excluidas por residuo mayor que {100 * outlier_threshold:g} %: {sorted(excluded)}.")
    if any(abs(r) > outlier_threshold for r in relative):
        warnings.append("Quedan lecturas con residuo alto y no hay puntos suficientes para excluirlas.")

    jac = _jacobian(theta, readings, array)
    a, _ = _normal(jac, [0.0] * len(readings))
    dof = len(readings) - 3
    names = ("rho1", "rho2", "h")
    uncertainty: dict[str, float | None] = dict.fromkeys(names)
    if dof > 0:
        variance = ssr / dof
        for p in range(3):
            unit = [1.0 if i == p else 0.0 for i in range(3)]
            column = _solve3(a, unit)
            if column is not None and column[p] > 0 and isfinite(column[p]):
                uncertainty[names[p]] = 100.0 * sqrt(variance * column[p])
    else:
        warnings.append("Sin grados de libertad: no se estima la incertidumbre de los parámetros.")
    logs = [log(m.apparent_resistivity_ohm_m) for m in readings]
    uniform = exp(sum(logs) / len(logs))
    if abs(soil.k) < NEAR_UNIFORM_K:
        warnings.append(f"Suelo prácticamente homogéneo (|K| < {NEAR_UNIFORM_K:g}): use el modelo homogéneo de "
                        f"{uniform:.4g} ohm-m; el espesor h no es identificable.")
    else:
        if soil.h_m > readings[-1].spacing_m:
            warnings.append("El espesor h supera el mayor espaciamiento medido: rho2 queda poco restringido.")
        if soil.h_m < readings[0].spacing_m / 3:
            warnings.append("El espesor h es menor que un tercio del menor espaciamiento: rho1 queda poco restringido.")
        for name in names:
            value = uncertainty[name]
            if dof > 0 and (value is None or value > 50):
                warnings.append(f"Parámetro {name} mal determinado por las mediciones (incertidumbre > 50 % o indefinida).")

    uniform_rms = sqrt(sum((uniform / m.apparent_resistivity_ohm_m - 1.0) ** 2 for m in readings) / len(readings))
    rms = sqrt(sum(r * r for r in relative) / len(relative))
    return SoilModelFit(
        array=array,
        model=soil,
        rms_error_percent=100.0 * rms,
        relative_uncertainty_percent=uncertainty,
        residuals_percent=[100.0 * r for r in _relative(soil, measurements, array)],
        excluded=sorted(excluded),
        uniform_resistivity_ohm_m=uniform,
        uniform_rms_error_percent=100.0 * uniform_rms,
        iterations=iterations,
        warnings=warnings,
    )


def to_soil_layers(model: TwoLayerSoil | SoilModelFit) -> list[dict[str, float | None]]:
    """Layers in the artifact `SoilLayerRequest` format: depth_m is the upper-layer thickness."""
    soil = model.model if isinstance(model, SoilModelFit) else model
    return [
        {"resistivity_ohm_m": soil.rho1_ohm_m, "depth_m": soil.h_m},
        {"resistivity_ohm_m": soil.rho2_ohm_m, "depth_m": None},
    ]
