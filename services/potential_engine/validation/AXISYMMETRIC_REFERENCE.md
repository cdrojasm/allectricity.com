# Axisymmetric finite-radius reference (experimental)

`axisymmetric_fv.py` is a separate SciPy-based finite-volume solution of
`div(sigma grad(V)) = 0` in an axisymmetric soil half-space. A cylindrical rod
from grade to depth `L` is held at 1 V, the ground surface is insulating, and
the far radial and bottom boundaries are held at 0 V. Current is integrated
across the cylinder side and its tip. This is an independent discretization
and physical model from the production thin-wire method of moments.

Run a standalone reference:

```sh
python services/potential_engine/validation/axisymmetric_fv.py 0.1
```

Compare the finite-radius cylinder with the thin-wire engine:

```sh
python services/potential_engine/validation/compare_axisymmetric_rod.py --cell-size 0.1
```

The comparison reports the relative difference in resistance. This number is
an estimate of model-form difference only after mesh-size and domain-size
convergence have been checked. It is not a correction factor. The reference is
currently limited to one vertical rod in homogeneous soil. It does not model
multiple electrodes, rings, layered soil, contact impedance, surface voltage
maxima, or commercial software. It is not independently reviewed and must not
be used to claim code compliance or commercial validation.

The far-field boundaries are finite, so repeat at larger `--radial-extent` and
`--depth-extent` as well as smaller `--cell-size`. The current unit checks
ensure positive finite resistance, exact linear scaling with resistivity, and
mesh refinement stability for one reproducible case; they do not establish a
general error bound.

For a diagnostic case (`rho=100 ohm m`, `a=10 mm`, `L=2 m`), the engine gives
45.257 ohm. The FV result at a 40 m × 40 m domain is 45.101 ohm for `h=0.1 m`
and 44.810 ohm for `h=0.05 m` (about −0.99% relative to the engine at the finer
mesh). At `h=0.1 m`, increasing the domain from 20 m × 20 m to 40 m × 40 m
changes FV resistance from 44.731 ohm to 45.101 ohm. This visible domain and
mesh sensitivity is why these values are diagnostics, not a declared model
error bound or validation result.

## Remaining validation gaps

- SV-22 is only a first vertical-rod prototype. Add a mesh convergence report,
  an analytic benchmark (e.g. hemispherical electrode), layered soil with
  interface-aligned finite-volume cells, rods crossing interfaces, and
  ring/rod-ring cases before relying on it as an arbiter.
- SV-23 remains open. This repository has no newly sourced licensed CDEGS,
  XGSLAB, or equivalent multi-layer reference. Existing IEEE 80 Annex H values
  remain the only external multi-layer checks, with their recorded tolerances
  and provenance in `reference_cases.json`.
- SV-01 remains partial: the existing reference suite is useful regression
  coverage, but an independent competent engineering review is still needed.
