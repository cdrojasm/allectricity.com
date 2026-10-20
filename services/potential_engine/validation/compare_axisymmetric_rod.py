"""Compare the finite-radius FV rod with the production thin-wire engine.

Run from the repository root: `python services/potential_engine/validation/compare_axisymmetric_rod.py --cell-size 0.1`.
Requires SciPy and a built `spat-potential-engine` executable.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "backend"))

from src.infrastructure.calculations.potential_engine_client import (  # noqa: E402
    ElectrodeSegment,
    HomogeneousSoil,
    PotentialEngineClient,
)
from axisymmetric_fv import RodCase, solve_rod  # noqa: E402


def compare(case: RodCase, executable: str | None = None) -> dict[str, object]:
    reference = solve_rod(case)
    engine = PotentialEngineClient(executable=executable).calculate(
        soil=HomogeneousSoil(case.resistivity_ohm_m),
        segments=[ElectrodeSegment("rod", "rod", "rod", (0, 0, 0), (0, 0, -case.length_m), case.radius_m)],
        injections_a={"rod": 1.0}, points=[],
    )
    thin_wire_r = engine["groups"]["rod"]["resistance_to_remote_earth_ohm"]
    if thin_wire_r is None:
        raise RuntimeError("engine did not report resistance to remote earth")
    return {
        "case": case.__dict__,
        "reference_method": "axisymmetric finite-volume Laplace solve, finite-radius cylinder",
        "reference": reference,
        "thin_wire_engine_resistance_ohm": thin_wire_r,
        "finite_radius_minus_thin_wire_relative": reference["resistance_ohm"] / thin_wire_r - 1.0,
        "interpretation": "model-form discrepancy estimate for this mesh and truncated domain; converge both before engineering use",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cell-size", type=float, default=0.1)
    parser.add_argument("--radius", type=float, default=0.01)
    parser.add_argument("--length", type=float, default=2.0)
    parser.add_argument("--resistivity", type=float, default=100.0)
    parser.add_argument("--radial-extent", type=float, default=20.0)
    parser.add_argument("--depth-extent", type=float, default=20.0)
    parser.add_argument("--engine")
    args = parser.parse_args()
    case = RodCase(args.resistivity, args.radius, args.length, args.radial_extent, args.depth_extent, args.cell_size)
    print(json.dumps(compare(case, args.engine), indent=2))
