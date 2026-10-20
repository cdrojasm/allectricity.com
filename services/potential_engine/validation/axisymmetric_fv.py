"""Independent axisymmetric finite-volume reference for a finite-radius vertical rod.

This is an optional validation tool, not a production solver. It solves the
axisymmetric conductivity equation on a structured (r, z) mesh with an
equipotential cylindrical rod and an insulating ground surface. SciPy is only
needed to run it. Domain truncation and mesh convergence must be reported with
any result; this small model does not cover rings, arbitrary geometry, or
layered soil yet.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import log, pi

import numpy as np
from scipy.sparse import lil_matrix
from scipy.sparse.linalg import spsolve


@dataclass(frozen=True)
class RodCase:
    resistivity_ohm_m: float = 100.0
    radius_m: float = 0.01
    length_m: float = 2.0
    radial_extent_m: float = 20.0
    depth_extent_m: float = 20.0
    cell_size_m: float = 0.1


def _edges(end: float, step: float, cuts: tuple[float, ...] = ()) -> np.ndarray:
    values = [0.0]
    while values[-1] + step < end - 1e-12:
        values.append(values[-1] + step)
    values.append(end)
    values.extend(c for c in cuts if 0 < c < end)
    return np.array(sorted(set(round(x, 12) for x in values)))


def solve_rod(case: RodCase = RodCase()) -> dict[str, float | int]:
    """Return rod current, resistance, and mesh/domain metadata for 1 V at rod."""
    if min(case.resistivity_ohm_m, case.radius_m, case.length_m, case.cell_size_m) <= 0:
        raise ValueError("resistivity, rod dimensions, and cell size must be positive")
    if case.radial_extent_m <= case.radius_m or case.depth_extent_m <= case.length_m:
        raise ValueError("domain must extend beyond the rod")
    dr = dz = case.cell_size_m
    re = _edges(case.radial_extent_m, dr, (case.radius_m,))
    ze = _edges(case.depth_extent_m, dz, (case.length_m,))
    rc, zc = (re[:-1] + re[1:]) / 2, (ze[:-1] + ze[1:]) / 2
    nr, nz = len(rc), len(zc)
    electrode = np.array([[re[i + 1] <= case.radius_m + 1e-12 and ze[j + 1] <= case.length_m + 1e-12
                           for j in range(nz)] for i in range(nr)])
    ids = -np.ones((nr, nz), dtype=int)
    ids[~electrode] = np.arange((~electrode).sum())
    n = int((~electrode).sum())
    matrix = lil_matrix((n, n), dtype=float)
    rhs = np.zeros(n)
    conductivity = 1.0 / case.resistivity_ohm_m

    def edge(i: int, j: int, ni: int, nj: int, conductance: float) -> None:
        a, b = ids[i, j], ids[ni, nj]
        if a >= 0:
            matrix[a, a] += conductance
            if b >= 0:
                matrix[a, b] -= conductance
            else:
                rhs[a] += conductance  # electrode is held at 1 V
        if b >= 0:
            matrix[b, b] += conductance
            if a >= 0:
                matrix[b, a] -= conductance
            else:
                rhs[b] += conductance

    for i in range(nr):
        for j in range(nz):
            area = pi * (re[i + 1] ** 2 - re[i] ** 2)
            if i + 1 < nr:
                face = re[i + 1]
                if electrode[i, j]:
                    g = 2 * pi * conductivity * (ze[j + 1] - ze[j]) / log(rc[i + 1] / face)
                else:
                    g = 2 * pi * conductivity * (ze[j + 1] - ze[j]) / log(rc[i + 1] / rc[i])
                edge(i, j, i + 1, j, g)
            else:  # outer radial boundary at zero potential
                a = ids[i, j]
                if a >= 0:
                    g = 2 * pi * conductivity * (ze[j + 1] - ze[j]) / log(case.radial_extent_m / rc[i])
                    matrix[a, a] += g
            if j + 1 < nz:
                if electrode[i, j]:
                    g = conductivity * area / (zc[j + 1] - case.length_m)
                else:
                    g = conductivity * area / (zc[j + 1] - zc[j])
                edge(i, j, i, j + 1, g)
            else:  # bottom boundary at zero potential
                a = ids[i, j]
                if a >= 0:
                    g = conductivity * area / (case.depth_extent_m - zc[j])
                    matrix[a, a] += g

    voltage = np.ones((nr, nz))
    voltage[~electrode] = spsolve(matrix.tocsr(), rhs)

    # Integrate current leaving the cylindrical side and the flat tip. Face
    # conductances use distance from the physical metal surface to soil-cell center.
    current = 0.0
    for j in range(nz):
        if ze[j] < case.length_m - 1e-12 and ze[j + 1] <= case.length_m + 1e-12 and nr > 1:
            soil_i = int(np.searchsorted(re, case.radius_m, side="right") - 1) + 1
            soil_i = min(soil_i, nr - 1)
            dz_cell = ze[j + 1] - ze[j]
            g = 2 * pi * conductivity * dz_cell / log(rc[soil_i] / case.radius_m)
            current += g * (1.0 - voltage[soil_i, j])
    tip_j = int(np.searchsorted(ze, case.length_m, side="left") - 1)
    if tip_j + 1 < nz:
        below = tip_j + 1
        for i in range(nr):
            if re[i + 1] <= case.radius_m + 1e-12:
                area = pi * (re[i + 1] ** 2 - re[i] ** 2)
                g = conductivity * area / (zc[below] - case.length_m)
                current += g * (1.0 - voltage[i, below])

    return {"current_a_at_1v": float(current), "resistance_ohm": float(1.0 / current),
            "radial_cells": nr, "depth_cells": nz, "cell_size_m": case.cell_size_m,
            "radial_extent_m": case.radial_extent_m, "depth_extent_m": case.depth_extent_m}


if __name__ == "__main__":
    import json
    import sys

    h = float(sys.argv[1]) if len(sys.argv) > 1 else 0.1
    print(json.dumps(solve_rod(RodCase(cell_size_m=h)), indent=2))
