"""Wenner / Schlumberger soundings over horizontally layered soil (2-8 layers): forward model and fit.

This is the sounding model for surface arrays only. It is unrelated to the grounding kernel of the
C++ potential engine (buried segments, `n-layer` soil line), which solves its own Green function;
the two share the physics, not the code.

Forward model. A point current I on the surface of a layered earth gives
    V(r) = I / (2 pi) * int_0^inf T(lambda) J0(lambda r) dlambda,
with the resistivity transform T computed bottom-up by Pekeris' recurrence
    T_N = rho_N,  T_k = (T_{k+1} + rho_k tanh(lambda h_k)) / (1 + T_{k+1} tanh(lambda h_k) / rho_k)
(Koefoed, "Geosounding Principles 1", Elsevier 1979, ch. 2-3; Ghosh, Geophys. Prosp. 19, 1971).
T - rho_1 is approximated by real exponentials sum_k a_k exp(-lambda b_k) on a fixed geometric
grid of depths b_k (10 per decade), fitted by rank-revealing least squares; by the Lipschitz integral
each term is an image, so V(r) = I / (2 pi) * [rho_1 / r + sum_k a_k / sqrt(r^2 + b_k^2)] exactly
(the complex-image approach to multilayer soundings: Zhang, Cui, Li & He, IEEE Trans. Power Deliv.
20(2), 2005, here with real images on a fixed grid instead of Prony's method). The grid spans
min(min spacing / 200, thinnest layer / 2) to 2e5 x max spacing and the fit covers lambda in [1e-5 / a_max, 40 / b_min]:
the four-electrode combination suppresses lower wavenumbers as (lambda a)^2, which bounds their
contribution by (max/min resistivity) x 1e-10 <= 1e-6 within the engine's contrast limit, and
T - rho_1 decays as exp(-2 lambda h) with h >= 2 b_min, well inside the range. Checked against the exact two-layer series of
`soil_model` and the published USGS curves in the tests (Haines & Campbell, OFR 80-190, 1980; El
Kahwagy, OFR 81-160, 1981).

Fit. Least squares in log apparent resistivity over ln(rho_k) and ln(h_k) by Levenberg-Marquardt
from several deterministic starts. A reading is excluded as atypical when the model fitted without
it misses it by more than `outlier_threshold` (leave-one-out over the 3 largest residuals, worst
first, one at a time) while more readings than parameters remain. One-sigma relative uncertainty
of each parameter comes from the Jacobian at the solution. Cost is bounded: starts are screened with
a few iterations, only the best is refined, and a time budget (60 s) returns the best fit so far
with a warning. The layer count is chosen by the user: a sounding does not determine it uniquely. Parameters are kept inside the range
the potential engine accepts (0.01-1e6 ohm-m, max/min resistivity <= 1e4, thickness 0.01-1000 m),
so the fitted layers can be stored in an artifact and calculated. Pure standard library on purpose.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from math import ceil, exp, isfinite, log, log10, sqrt, tanh
from time import monotonic

from src.infrastructure.calculations.soil_model import SCHLUMBERGER, WENNER, ResistivityMeasurement

MIN_RHO_OHM_M, MAX_RHO_OHM_M = 1e-2, 1e6
MAX_CONTRAST = 1e4
MIN_THICKNESS_M, MAX_THICKNESS_M = 0.01, 1000.0
DEFAULT_OUTLIER_THRESHOLD = 0.15
OUTLIER_CANDIDATES = 3
# Cost limits of a fit (the endpoint is synchronous): starts are screened with a few iterations and
# only the best is refined; leave-one-out refits are warm-started; past the time budget the best
# fit so far is returned with a warning.
SCREENING_ITERATIONS = 10
REFIT_ITERATIONS = 20
DEFAULT_TIME_BUDGET_S = 60.0
IMAGES_PER_DECADE = 10
RANK_CUT = 1e-10
FORWARD_MODEL = ("koefoed-transform;real-exponential-images-10-per-decade;householder-qr-column-pivoting;"
                 "lipschitz-integral")


@dataclass(frozen=True)
class SoilLayer:
    resistivity_ohm_m: float
    thickness_m: float | None = None


@dataclass(frozen=True)
class NLayerSoil:
    """Top-to-bottom layers; the final layer is a half-space."""

    layers: tuple[SoilLayer, ...]

    def __post_init__(self):
        if not 2 <= len(self.layers) <= 8:
            raise ValueError("an n-layer model must contain between 2 and 8 layers")
        for i, layer in enumerate(self.layers):
            rho, depth = layer.resistivity_ohm_m, layer.thickness_m
            if not isfinite(rho) or not 1e-2 <= rho <= 1e7:
                raise ValueError(f"layer {i}: resistivity must be between 0.01 and 1e7 ohm-m")
            if i == len(self.layers) - 1:
                if depth is not None:
                    raise ValueError("the bottom layer must be a half-space (thickness_m=null)")
            elif depth is None or not isfinite(depth) or depth <= 0:
                raise ValueError(f"layer {i}: finite layers need a positive thickness")


def resistivity_transform(soil: NLayerSoil, wavenumber_per_m: float) -> float:
    """Layered-earth resistivity transform T(lambda), evaluated bottom-up (Pekeris recurrence)."""
    if wavenumber_per_m < 0 or not isfinite(wavenumber_per_m):
        raise ValueError("wavenumber must be finite and non-negative")
    value = soil.layers[-1].resistivity_ohm_m
    for layer in reversed(soil.layers[:-1]):
        rho, t = layer.resistivity_ohm_m, tanh(wavenumber_per_m * layer.thickness_m)
        value = (value + rho * t) / (1.0 + value * t / rho)
    return value


class _ImageFit:
    """Fixed image grid and its least-squares operator for spacings in [a_min, a_max]."""

    def __init__(self, a_min: float, a_max: float, b_min: float):
        b_max = 2.0e5 * a_max
        count = ceil(log10(b_max / b_min) * IMAGES_PER_DECADE) + 1
        self.depths = [b_min * (b_max / b_min) ** (k / (count - 1)) for k in range(count)]
        low, high = 1e-5 / a_max, 40.0 / b_min
        samples = int(2.5 * count * log10(high / low) / log10(b_max / b_min)) + 1
        self.wavenumbers = [low * (high / low) ** (k / (samples - 1)) for k in range(samples)]
        columns = [[exp(-lam * b) for lam in self.wavenumbers] for b in self.depths]
        self._factor(columns)

    def _factor(self, columns: list[list[float]]) -> None:
        """Householder QR with column pivoting, truncated where |R_kk| < RANK_CUT |R_00|."""
        n = len(columns)
        a = [column[:] for column in columns]
        order = list(range(n))
        reflectors: list[tuple[int, list[float]]] = []
        first = None
        for k in range(n):
            norms = [sum(v * v for v in a[j][k:]) for j in range(k, n)]
            pivot = k + max(range(len(norms)), key=norms.__getitem__)
            a[k], a[pivot] = a[pivot], a[k]
            order[k], order[pivot] = order[pivot], order[k]
            column = a[k]
            alpha = sqrt(sum(v * v for v in column[k:]))
            first = alpha if first is None else first
            if alpha <= RANK_CUT * first:
                break
            alpha = -alpha if column[k] > 0 else alpha
            v = column[k:]
            v[0] -= alpha
            vnorm2 = sum(x * x for x in v)
            for j in range(k + 1, n):
                target = a[j]
                dot = sum(x * y for x, y in zip(v, target[k:])) * 2.0 / vnorm2
                for i in range(len(v)):
                    target[k + i] -= dot * v[i]
            reflectors.append((k, v))
            column[k] = alpha
        rank = len(reflectors)
        self._reflectors = reflectors
        # Upper-triangular rows of R from the diagonal on, read after every column swap.
        self._rows = [[a[j][k] for j in range(k, n)] for k in range(rank)]
        self._order = order
        self._rank = len(reflectors)

    def coefficients(self, values: list[float]) -> list[float]:
        y = values[:]
        for k, v in self._reflectors:
            vnorm2 = sum(x * x for x in v)
            dot = sum(x * z for x, z in zip(v, y[k:])) * 2.0 / vnorm2
            for i in range(len(v)):
                y[k + i] -= dot * v[i]
        solution = [0.0] * self._rank
        for k in range(self._rank - 1, -1, -1):
            row = self._rows[k]
            solution[k] = (y[k] - sum(row[j - k] * solution[j] for j in range(k + 1, self._rank))) / row[0]
        result = [0.0] * len(self.depths)
        for k in range(self._rank):
            result[self._order[k]] = solution[k]
        return result

    def images(self, soil: NLayerSoil) -> list[tuple[float, float]]:
        rho1 = soil.layers[0].resistivity_ohm_m
        values = [resistivity_transform(soil, lam) - rho1 for lam in self.wavenumbers]
        return list(zip(self.coefficients(values), self.depths))


@lru_cache(maxsize=16)
def _image_fit(a_min: float, a_max: float, b_min: float) -> _ImageFit:
    """Image grid for distances in [a_min, a_max] and layers at least 2 b_min thick."""
    return _ImageFit(a_min, a_max, b_min)


def _pairs(array: str, spacing_m: float, potential_spacing_m: float | None) -> tuple[tuple[float, float], ...]:
    """(sign, distance) of the current-potential electrode pairs AM, AN, BM, BN."""
    if array not in (WENNER, SCHLUMBERGER):
        raise ValueError(f"array must be one of {(WENNER, SCHLUMBERGER)}")
    if not isfinite(spacing_m) or spacing_m <= 0:
        raise ValueError("spacing must be positive and finite")
    if array == WENNER:
        return (1.0, spacing_m), (-1.0, 2 * spacing_m), (-1.0, 2 * spacing_m), (1.0, spacing_m)
    b = potential_spacing_m
    if b is None or not isfinite(b) or b <= 0 or b >= 2 * spacing_m:
        raise ValueError("Schlumberger MN must be positive and smaller than AB")
    return (1.0, spacing_m - b / 2), (-1.0, spacing_m + b / 2), (-1.0, spacing_m + b / 2), (1.0, spacing_m - b / 2)


def _apparent(soil: NLayerSoil, images: list[tuple[float, float]], pairs) -> float:
    rho1 = soil.layers[0].resistivity_ohm_m
    geometric = sum(sign / r for sign, r in pairs)
    voltage = sum(sign * (rho1 / r + sum(a / sqrt(r * r + b * b) for a, b in images)) for sign, r in pairs)
    apparent = voltage / geometric
    if not isfinite(apparent) or apparent <= 0:
        raise ArithmeticError("n-layer forward model produced a non-positive apparent resistivity")
    return apparent


def apparent_resistivity_n_layer(
    soil: NLayerSoil,
    array: str,
    spacing_m: float,
    potential_spacing_m: float | None = None,
) -> float:
    """Wenner (`spacing_m` = a) or Schlumberger (`spacing_m` = AB/2, MN given) apparent resistivity."""
    pairs = _pairs(array, spacing_m, potential_spacing_m)
    distances = [r for _, r in pairs]
    thinnest = min(layer.thickness_m for layer in soil.layers[:-1])
    fit = _image_fit(min(distances), max(distances), min(min(distances) / 200.0, thinnest / 2.0))
    return _apparent(soil, fit.images(soil), pairs)


@dataclass(frozen=True)
class NLayerFit:
    array: str
    model: NLayerSoil
    rms_error_percent: float
    residuals_percent: list[float]  # model/measured - 1 for every input reading, in %
    iterations: int
    warnings: list[str]
    # One-sigma relative uncertainty (%) per layer: {"resistivity_ohm_m": .., "thickness_m": ..}.
    relative_uncertainty_percent: list[dict[str, float | None]] = field(default_factory=list)
    excluded: list[int] = field(default_factory=list)
    uniform_resistivity_ohm_m: float | None = None
    uniform_rms_error_percent: float | None = None
    forward_model: str = FORWARD_MODEL


def _solve(a: list[list[float]], b: list[float]) -> list[float] | None:
    n = len(b)
    m = [row[:] + [value] for row, value in zip(a, b)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda row: abs(m[row][col]))
        if abs(m[pivot][col]) < 1e-300:
            return None
        m[col], m[pivot] = m[pivot], m[col]
        for row in range(n):
            if row == col:
                continue
            factor = m[row][col] / m[col][col]
            for j in range(col, n + 1):
                m[row][j] -= factor * m[col][j]
    return [m[i][n] / m[i][i] for i in range(n)]


def _validate(measurements: list[ResistivityMeasurement], layer_count: int, array: str) -> None:
    if not 2 <= layer_count <= 8:
        raise ValueError("layer_count must be between 2 and 8")
    if array not in (WENNER, SCHLUMBERGER):
        raise ValueError(f"array must be one of {(WENNER, SCHLUMBERGER)}")
    if len(measurements) < 2 * layer_count:
        raise ValueError(f"at least {2 * layer_count} readings are required for {layer_count} layers "
                         f"({2 * layer_count - 1} parameters plus one degree of freedom)")
    previous = 0.0
    for i, m in enumerate(measurements):
        if not all(isinstance(v, (int, float)) and isfinite(v) and v > 0 for v in (m.spacing_m, m.apparent_resistivity_ohm_m)):
            raise ValueError(f"reading {i}: spacing and apparent resistivity must be positive finite numbers")
        if m.spacing_m <= previous:
            raise ValueError("spacings must be strictly increasing")
        previous = m.spacing_m
        if array == SCHLUMBERGER and (m.potential_spacing_m is None or not isfinite(m.potential_spacing_m) or
                                      not 0 < m.potential_spacing_m < 2 * m.spacing_m):
            raise ValueError(f"reading {i}: Schlumberger MN must be positive and smaller than AB")


class _Problem:
    """Log-parameter decoding with the engine's bounds, and residuals of a set of readings."""

    def __init__(self, measurements: list[ResistivityMeasurement], layer_count: int, array: str):
        self.layer_count, self.array = layer_count, array
        self.pairs = [_pairs(array, m.spacing_m, m.potential_spacing_m) for m in measurements]
        distances = [r for pairs in self.pairs for _, r in pairs]
        spacings = [m.spacing_m for m in measurements]
        self.h_low = log(max(MIN_THICKNESS_M, spacings[0] / 100.0))
        self.fit = _image_fit(min(distances), max(distances), min(min(distances) / 200.0, exp(self.h_low) / 2.0))
        self.h_high = log(min(MAX_THICKNESS_M, spacings[-1] * 100.0))
        if self.h_low > self.h_high:
            raise ValueError("the spacings do not allow layer thicknesses within 0.01-1000 m")

    def clamp(self, theta: list[float]) -> list[float]:
        n = self.layer_count
        rhos = [min(max(v, log(MIN_RHO_OHM_M)), log(MAX_RHO_OHM_M)) for v in theta[:n]]
        center, half = (max(rhos) + min(rhos)) / 2, (log(MAX_CONTRAST) - 1e-9) / 2
        if max(rhos) - min(rhos) > 2 * half:
            rhos = [min(max(v, center - half), center + half) for v in rhos]
        return rhos + [min(max(v, self.h_low), self.h_high) for v in theta[n:]]

    def decode(self, theta: list[float]) -> NLayerSoil:
        n = self.layer_count
        return NLayerSoil(tuple([SoilLayer(exp(theta[i]), exp(theta[n + i])) for i in range(n - 1)] +
                                [SoilLayer(exp(theta[n - 1]), None)]))

    def model_values(self, theta: list[float], indices: list[int]) -> list[float]:
        soil = self.decode(theta)
        images = self.fit.images(soil)
        return [_apparent(soil, images, self.pairs[i]) for i in indices]


def _residuals(problem: _Problem, theta, indices, measurements) -> list[float]:
    return [log(v) - log(measurements[i].apparent_resistivity_ohm_m)
            for v, i in zip(problem.model_values(theta, indices), indices)]


def _jacobian(problem: _Problem, theta, indices, measurements, base=None, step=1e-6) -> list[list[float]]:
    """Forward-difference Jacobian of the log residuals (one model evaluation per parameter)."""
    base = base if base is not None else _residuals(problem, theta, indices, measurements)
    columns = []
    for p in range(len(theta)):
        plus = theta[:]
        plus[p] += step
        columns.append([(a - b) / step for a, b in zip(_residuals(problem, plus, indices, measurements), base)])
    return [[columns[p][i] for p in range(len(theta))] for i in range(len(indices))]


def _levenberg_marquardt(problem, theta, indices, measurements, max_iterations, deadline=float("inf")):
    theta = problem.clamp(theta)
    values = _residuals(problem, theta, indices, measurements)
    error = sum(v * v for v in values)
    damping, iterations, count = 1e-3, 0, len(theta)
    for iterations in range(1, max_iterations + 1):
        if monotonic() > deadline:
            break
        jac = _jacobian(problem, theta, indices, measurements, values)
        normal = [[sum(row[i] * row[j] for row in jac) for j in range(count)] for i in range(count)]
        gradient = [sum(row[i] * r for row, r in zip(jac, values)) for i in range(count)]
        improved = done = False
        while damping < 1e10:
            matrix = [[normal[i][j] + (damping * max(normal[i][i], 1e-12) if i == j else 0.0)
                       for j in range(count)] for i in range(count)]
            delta = _solve(matrix, [-g for g in gradient])
            if delta is None:
                damping *= 10
                continue
            candidate = problem.clamp([t + d for t, d in zip(theta, delta)])
            candidate_values = _residuals(problem, candidate, indices, measurements)
            candidate_error = sum(v * v for v in candidate_values)
            if candidate_error < error:
                done = error - candidate_error < 1e-12 * (1.0 + error) or max(map(abs, delta)) < 1e-8
                theta, values, error = candidate, candidate_values, candidate_error
                damping = max(1e-12, damping / 10)
                improved = True
                break
            damping *= 10
        if not improved or done:
            break
    return theta, error, iterations


def _starts(problem: _Problem, measurements, indices) -> list[list[float]]:
    n = problem.layer_count
    readings = [measurements[i] for i in indices]
    first, last = readings[0], readings[-1]
    starts = []
    for shape in ("linear", "data"):
        if shape == "linear":
            rhos = [log(first.apparent_resistivity_ohm_m) + (log(last.apparent_resistivity_ohm_m) -
                    log(first.apparent_resistivity_ohm_m)) * i / (n - 1) for i in range(n)]
        else:
            rhos = [log(readings[round(i * (len(readings) - 1) / (n - 1))].apparent_resistivity_ohm_m) for i in range(n)]
        for scale in (0.3, 1.0, 3.0):
            depths = [first.spacing_m * (last.spacing_m / first.spacing_m) ** ((i + 1) / n) * scale for i in range(n - 1)]
            thicknesses = [depths[0]] + [b - a for a, b in zip(depths, depths[1:])]
            starts.append(rhos + [log(max(t, 1e-6)) for t in thicknesses])
    return starts


def fit_n_layer(
    measurements: list[ResistivityMeasurement],
    layer_count: int,
    array: str = WENNER,
    max_iterations: int = 60,
    outlier_threshold: float = DEFAULT_OUTLIER_THRESHOLD,
    time_budget_s: float = DEFAULT_TIME_BUDGET_S,
) -> NLayerFit:
    """Fit a fixed number of layers to a sounding; see the module docstring for the method."""
    deadline = monotonic() + time_budget_s
    _validate(measurements, layer_count, array)
    if not 0 < outlier_threshold < 1:
        raise ValueError("outlier_threshold must be between 0 and 1")
    problem = _Problem(measurements, layer_count, array)
    parameter_count = 2 * layer_count - 1
    kept = list(range(len(measurements)))
    excluded: list[int] = []
    best = None
    for theta in _starts(problem, measurements, kept):
        result = _levenberg_marquardt(problem, theta, kept, measurements, SCREENING_ITERATIONS, deadline)
        if best is None or result[1] < best[1]:
            best = result
    best = _levenberg_marquardt(problem, best[0], kept, measurements, max_iterations, deadline)
    # Leave-one-out exclusion: a reading is atypical when the model fitted without it misses it by
    # more than the threshold. Candidates are the readings with the largest residuals.
    while len(kept) - 1 > parameter_count:
        values = problem.model_values(best[0], kept)
        relative = [v / measurements[i].apparent_resistivity_ohm_m - 1 for v, i in zip(values, kept)]
        candidates = sorted(range(len(kept)), key=lambda k: -abs(relative[k]))[:OUTLIER_CANDIDATES]
        worst = None
        for k in candidates:
            others = kept[:k] + kept[k + 1:]
            refit = _levenberg_marquardt(problem, best[0], others, measurements, REFIT_ITERATIONS, deadline)
            miss = abs(problem.model_values(refit[0], [kept[k]])[0] / measurements[kept[k]].apparent_resistivity_ohm_m - 1)
            if miss > outlier_threshold and (worst is None or miss > worst[0]):
                worst = (miss, k, refit)
        if worst is None:
            break
        excluded.append(kept.pop(worst[1]))
        best = _levenberg_marquardt(problem, worst[2][0], kept, measurements, max_iterations, deadline)
    values = problem.model_values(best[0], kept)
    relative = [v / measurements[i].apparent_resistivity_ohm_m - 1 for v, i in zip(values, kept)]
    theta, error, iterations = best
    model = problem.decode(theta)

    warnings = ["El número de capas se fijó antes del ajuste; varias estratigrafías pueden explicar las mismas mediciones."]
    if monotonic() > deadline:
        warnings.append(f"Ajuste detenido al agotar el presupuesto de {time_budget_s:g} s; el modelo puede no ser el óptimo.")
    if excluded:
        warnings.append(f"Lecturas excluidas por residuo mayor que {100 * outlier_threshold:g} %: {sorted(excluded)}.")
    if any(abs(r) > outlier_threshold for r in relative):
        warnings.append("Quedan lecturas con residuo alto y no hay puntos suficientes para excluirlas.")
    names = [("resistivity_ohm_m", i) for i in range(layer_count)] + [("thickness_m", i) for i in range(layer_count - 1)]
    uncertainty: list[dict[str, float | None]] = [{"resistivity_ohm_m": None, "thickness_m": None} for _ in range(layer_count)]
    dof = len(kept) - parameter_count
    if dof > 0:
        jac = _jacobian(problem, theta, kept, measurements)
        normal = [[sum(row[i] * row[j] for row in jac) for j in range(parameter_count)] for i in range(parameter_count)]
        variance = error / dof
        for p, (name, layer) in enumerate(names):
            column = _solve(normal, [1.0 if i == p else 0.0 for i in range(parameter_count)])
            if column is not None and column[p] > 0 and isfinite(column[p]):
                uncertainty[layer][name] = 100.0 * sqrt(variance * column[p])
        for p, (name, layer) in enumerate(names):
            value = uncertainty[layer][name]
            if value is None or value > 50:
                warnings.append(f"Capa {layer + 1}: {'resistividad' if name.startswith('res') else 'espesor'} mal "
                                "determinado por las mediciones (incertidumbre > 50 % o indefinida).")
    else:
        warnings.append("Sin grados de libertad suficientes para estimar la incertidumbre del ajuste.")
    if any(min(abs(v - problem.h_low), abs(v - problem.h_high)) < 1e-9 for v in theta[layer_count:]):
        warnings.append("Algún espesor quedó en el límite del rango explorado (1/100 del menor a 100 veces el mayor "
                        "espaciamiento): las mediciones no lo resuelven.")
    rhos = [layer.resistivity_ohm_m for layer in model.layers]
    if max(rhos) / min(rhos) > 0.999 * MAX_CONTRAST:
        warnings.append("El contraste de resistividades llegó al máximo admitido por el motor (1e4).")

    all_values = problem.model_values(theta, list(range(len(measurements))))
    logs = [log(measurements[i].apparent_resistivity_ohm_m) for i in kept]
    uniform = exp(sum(logs) / len(logs))
    uniform_rms = sqrt(sum((uniform / measurements[i].apparent_resistivity_ohm_m - 1.0) ** 2 for i in kept) / len(kept))
    return NLayerFit(
        array=array,
        model=model,
        rms_error_percent=100 * sqrt(sum(r * r for r in relative) / len(relative)),
        residuals_percent=[100 * (v / m.apparent_resistivity_ohm_m - 1) for v, m in zip(all_values, measurements)],
        iterations=iterations,
        warnings=warnings,
        relative_uncertainty_percent=uncertainty,
        excluded=sorted(excluded),
        uniform_resistivity_ohm_m=uniform,
        uniform_rms_error_percent=100 * uniform_rms,
    )


def soil_layers_record(model: NLayerSoil) -> list[dict[str, float | None]]:
    """Serialize the model to artifact layer records, top to bottom (`depth_m` = layer thickness)."""
    return [{"resistivity_ohm_m": layer.resistivity_ohm_m, "depth_m": layer.thickness_m}
            for layer in model.layers]
