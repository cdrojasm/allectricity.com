"""Independent reference for the potential of a point current in horizontally layered soil (tests only).

At every wavenumber lambda the Hankel-transformed potential of each layer, A_j exp(-lambda (t - d_j)) +
B_j exp(-lambda (d_{j+1} - t)), is found from the full boundary-condition system (zero normal current
at the insulating surface; continuous potential and normal current density at every interface),
2N-1 unknowns solved by Gaussian elimination with partial pivoting. The potential follows from the
Lipschitz integral 1/R = int exp(-lambda |z|) J0(lambda r) dlambda (Sunde 1949, ch. 2) by composite
Gauss-Legendre quadrature in lambda; J0 uses the trapezoidal rule on Bessel's integral, exact to
rounding when the node count exceeds x/2 + 20 (Trefethen & Weideman, SIAM Rev. 56, 2014).

It shares no code with the engine (no generalized-reflection recursion, no exponential fit); it is
slow and meant for a few dozen evaluations in tests. Pure standard library.
"""

from __future__ import annotations

from math import cos, exp, inf, pi, sin, sqrt

_NODES = (-0.9739065285171717, -0.8650633666889845, -0.6794095682990244, -0.4333953941292472,
          -0.1488743389816312, 0.1488743389816312, 0.4333953941292472, 0.6794095682990244,
          0.8650633666889845, 0.9739065285171717)
_WEIGHTS = (0.0666713443086881, 0.1494513491505806, 0.2190863625159820, 0.2692667193099963,
            0.2955242247147529, 0.2955242247147529, 0.2692667193099963, 0.2190863625159820,
            0.1494513491505806, 0.0666713443086881)


def j0(x: float) -> float:
    n = int(abs(x) / 2) + 24
    return sum(cos(x * sin(pi * (k + 0.5) / n)) for k in range(n)) / n


def _solve(matrix: list[list[float]], rhs: list[float]) -> list[float]:
    n = len(rhs)
    m = [row[:] + [value] for row, value in zip(matrix, rhs)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda row: abs(m[row][col]))
        m[col], m[pivot] = m[pivot], m[col]
        for row in range(col + 1, n):
            factor = m[row][col] / m[col][col]
            if factor:
                for k in range(col, n + 1):
                    m[row][k] -= factor * m[col][k]
    x = [0.0] * n
    for row in range(n - 1, -1, -1):
        x[row] = (m[row][n] - sum(m[row][k] * x[k] for k in range(row + 1, n))) / m[row][row]
    return x


def layer_of(depth: float, tops: list[float]) -> int:
    return max(k for k, top in enumerate(tops) if depth >= top)


def reflected_field(rhos: list[float], thicknesses: list[float], s: float, t: float, lam: float) -> float:
    """Transformed potential at depth t of a unit current at depth s, without the direct term."""
    n = len(rhos)
    tops = [0.0]
    for h in thicknesses:
        tops.append(tops[-1] + h)
    bottoms = tops[1:] + [inf]
    i, j = layer_of(s, tops), layer_of(t, tops)
    e = [exp(-lam * h) for h in thicknesses] + [0.0]
    u = exp(-lam * (s - tops[i]))
    v = exp(-lam * (bottoms[i] - s)) if i < n - 1 else 0.0
    size = 2 * n - 1  # A_0..A_{n-1}, B_0..B_{n-2}
    a_index, b_index = (lambda k: k), (lambda k: n + k)
    matrix = [[0.0] * size for _ in range(size)]
    rhs = [0.0] * size
    rho_i, sigma = rhos[i], [1.0 / r for r in rhos]
    # Surface: dF/dt = 0 at t = 0.
    matrix[0][a_index(0)] = -1.0
    if n > 1:
        matrix[0][b_index(0)] = e[0]
    if i == 0:
        rhs[0] = -rho_i * u
    row = 1
    for k in range(1, n):
        # Potential continuity at the top of layer k.
        matrix[row][a_index(k - 1)] += e[k - 1]
        matrix[row][b_index(k - 1)] += 1.0
        matrix[row][a_index(k)] -= 1.0
        if k < n - 1:
            matrix[row][b_index(k)] -= e[k]
        rhs[row] = (rho_i * u if i == k else 0.0) - (rho_i * v if i == k - 1 else 0.0)
        row += 1
        # Normal current continuity (divided by lambda).
        matrix[row][a_index(k - 1)] += -sigma[k - 1] * e[k - 1]
        matrix[row][b_index(k - 1)] += sigma[k - 1]
        matrix[row][a_index(k)] += sigma[k]
        if k < n - 1:
            matrix[row][b_index(k)] -= sigma[k] * e[k]
        rhs[row] = sigma[k - 1] * (rho_i * v if i == k - 1 else 0.0) + sigma[k] * (rho_i * u if i == k else 0.0)
        row += 1
    x = _solve(matrix, rhs)
    field = x[a_index(j)] * exp(-lam * (t - tops[j]))
    if j < n - 1:
        field += x[b_index(j)] * exp(-lam * (bottoms[j] - t))
    return field


def green(rhos: list[float], thicknesses: list[float], r: float, s: float, t: float) -> float:
    """Potential (V) at horizontal distance r and depth t of 1 A injected at depth s (depths positive down)."""
    tops = [0.0]
    for h in thicknesses:
        tops.append(tops[-1] + h)
    bottoms = tops[1:] + [inf]
    i, j = layer_of(s, tops), layer_of(t, tops)
    direct = rhos[i] / sqrt(r * r + (t - s) ** 2) if i == j else 0.0
    # Slowest exponential decay of the reflected field: the shortest reflected or transmitted path.
    if i == j:
        gaps = [s + t - 2 * tops[i]] + ([2 * bottoms[i] - s - t] if i < len(rhos) - 1 else [])
    else:
        gaps = [abs(t - s)]
    decay = max(min(gaps), 1e-3)
    upper = 46.0 / decay
    width = min(pi / r if r > 0 else inf, 1.0 / decay, upper / 40)

    def gauss(low: float, high: float) -> float:
        half, mid = 0.5 * (high - low), 0.5 * (high + low)
        return half * sum(w * reflected_field(rhos, thicknesses, s, t, mid + half * x) * j0((mid + half * x) * r)
                          for x, w in zip(_NODES, _WEIGHTS))

    # The field varies on the scale of the slowest multiple reflection near lambda = 0 (a resistive
    # basement under conductive layers puts a near-pole there): grade the first interval
    # geometrically towards zero, down to width * 2^-40.
    total = sum(gauss(width * 2.0 ** -(k + 1), width * 2.0 ** -k) for k in range(40))
    low = width
    while low < upper:
        high = min(low + width, upper)
        total += gauss(low, high)
        low = high
    return (direct + total) / (4 * pi)


def segment_points(start, end, count=4):
    """Gauss-Legendre points (x, y, depth) and weights (summing to 1) along a straight segment."""
    nodes = {2: ((-0.5773502691896258, 1.0), (0.5773502691896258, 1.0)),
             4: ((-0.8611363115940526, 0.3478548451374538), (-0.3399810435848563, 0.6521451548625461),
                 (0.3399810435848563, 0.6521451548625461), (0.8611363115940526, 0.3478548451374538))}[count]
    return [((start[0] + (end[0] - start[0]) * (x + 1) / 2, start[1] + (end[1] - start[1]) * (x + 1) / 2,
              -(start[2] + (end[2] - start[2]) * (x + 1) / 2)), w / 2) for x, w in nodes]


def segment_to_point(rhos, thicknesses, start, end, point, count=4) -> float:
    """Potential (V) at a surface point of 1 A leaking uniformly from a straight segment."""
    return sum(w * green(rhos, thicknesses, sqrt((x - point[0]) ** 2 + (y - point[1]) ** 2), depth, -point[2])
               for (x, y, depth), w in segment_points(start, end, count))


def segment_to_segment(rhos, thicknesses, source, target, count=2) -> float:
    """Mean potential (V) along `target` of 1 A leaking uniformly from `source` (both (start, end))."""
    total = 0.0
    for (x, y, depth), w in segment_points(*target, count):
        for (xs, ys, ds), ws in segment_points(*source, count):
            total += w * ws * green(rhos, thicknesses, sqrt((x - xs) ** 2 + (y - ys) ** 2), ds, depth)
    return total


def j1(x: float) -> float:
    n = int(abs(x)) + 32
    return sum(cos(2 * pi * k / n - x * sin(2 * pi * k / n)) for k in range(n)) / n


def resistivity_transform(rhos: list[float], thicknesses: list[float], lam: float) -> float:
    from math import tanh
    value = rhos[-1]
    for rho, h in zip(reversed(rhos[:-1]), reversed(thicknesses)):
        t = tanh(lam * h)
        value = (value + rho * t) / (1 + value * t / rho)
    return value


def ideal_schlumberger(rhos: list[float], thicknesses: list[float], half_spacing: float) -> float:
    """Schlumberger apparent resistivity in the MN -> 0 limit, s^2 int T(lambda) J1(lambda s) lambda dlambda,
    by direct quadrature (graded towards lambda = 0, 10-point Gauss between J1 half-periods)."""
    s, decay = half_spacing, 2 * thicknesses[0]
    upper = 46.0 / decay
    width = min(pi / s, 1.0 / decay, upper / 40)

    def gauss(low: float, high: float) -> float:
        half, mid = 0.5 * (high - low), 0.5 * (high + low)
        return half * sum(w * (resistivity_transform(rhos, thicknesses, mid + half * x) - rhos[0]) *
                          j1((mid + half * x) * s) * (mid + half * x) for x, w in zip(_NODES, _WEIGHTS))

    total = sum(gauss(width * 2.0 ** -(k + 1), width * 2.0 ** -k) for k in range(40))
    low = width
    while low < upper:
        total += gauss(low, min(low + width, upper))
        low += width
    return rhos[0] + s * s * total
