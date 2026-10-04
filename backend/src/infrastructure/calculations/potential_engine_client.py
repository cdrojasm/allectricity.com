"""Python pipe client for the standalone C++ grounding-potential solver."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import math
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any
from math import ceil

PROTOCOL = "SPAT-POTENTIAL-2"
# Operational limits mirrored from services/potential_engine/src/main.cpp.
MAX_SEGMENTS = 1500
MAX_POINTS = 100_000
MAX_POINT_SEGMENT_WORK = 2.0e7
MAX_COORDINATE_M = 1.0e5
MAX_DEPTH_M = 1000.0
MIN_RADIUS_M = 1.0e-4
MAX_RADIUS_M = 0.5
MIN_LENGTH_TO_RADIUS = 5.0
MAX_RESISTIVITY_OHM_M = 1.0e6
MAX_CURRENT_A = 1.0e6
DEFAULT_TIMEOUT_S = 60.0
DEFAULT_MEMORY_LIMIT_MB = 512


@dataclass(frozen=True)
class ElectrodeSegment:
    id: str
    group: str
    kind: str
    start_m: tuple[float, float, float]
    end_m: tuple[float, float, float]
    radius_m: float


@dataclass(frozen=True)
class PotentialPoint:
    id: str
    xyz_m: tuple[float, float, float]


class PotentialEngineError(RuntimeError):
    pass


def _distance(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    return math.dist(a, b)


def _segment_distance(p1, q1, p2, q2) -> float:
    """Closest distance between two 3D segments."""
    d1 = [q - p for p, q in zip(p1, q1)]
    d2 = [q - p for p, q in zip(p2, q2)]
    r = [a - b for a, b in zip(p1, p2)]
    dot = lambda u, v: sum(x * y for x, y in zip(u, v))  # noqa: E731
    a, e, f, c, b = dot(d1, d1), dot(d2, d2), dot(d2, r), dot(d1, r), dot(d1, d2)
    denom = a * e - b * b
    s = min(max((b * f - c * e) / denom, 0.0), 1.0) if denom > 1e-12 * a * e else 0.0
    t = (b * s + f) / e
    if t < 0.0:
        t, s = 0.0, min(max(-c / a, 0.0), 1.0)
    elif t > 1.0:
        t, s = 1.0, min(max((b - c) / a, 0.0), 1.0)
    return _distance(tuple(p + d * s for p, d in zip(p1, d1)), tuple(p + d * t for p, d in zip(p2, d2)))


def validate_request(
    soil_resistivity_ohm_m: float,
    segments: list[ElectrodeSegment],
    injections_a: dict[str, float],
    points: list[PotentialPoint],
    injection_origins: dict[str, str] | None = None,
) -> None:
    """Reject requests outside the engine's validated operating range before starting a process."""
    rho = float(soil_resistivity_ohm_m)
    if not math.isfinite(rho) or not 0 < rho <= MAX_RESISTIVITY_OHM_M:
        raise ValueError("soil resistivity must be in (0, 1e6] ohm-m")
    if not segments or len(segments) > MAX_SEGMENTS:
        raise ValueError(f"segment count must be between 1 and {MAX_SEGMENTS}")
    if len(points) > MAX_POINTS or len(points) * len(segments) > MAX_POINT_SEGMENT_WORK:
        raise ValueError(f"at most {MAX_POINTS} points and 2e7 points x segments per request")
    groups: set[str] = set()
    ids: set[str] = set()
    for segment in segments:
        _token(segment.id, "segment id"), _token(segment.group, "group id"), _token(segment.kind, "element kind")
        if segment.id in ids:
            raise ValueError(f"duplicate segment id: {segment.id}")
        ids.add(segment.id)
        groups.add(segment.group)
        coordinates = (*segment.start_m, *segment.end_m, segment.radius_m)
        if len(segment.start_m) != 3 or len(segment.end_m) != 3 or not all(map(math.isfinite, coordinates)):
            raise ValueError(f"segment {segment.id} coordinates must be finite x, y, z")
        for x, y, z in (segment.start_m, segment.end_m):
            if abs(x) > MAX_COORDINATE_M or abs(y) > MAX_COORDINATE_M or abs(z) > MAX_DEPTH_M:
                raise ValueError(f"segment {segment.id} coordinates exceed the supported extent")
            if z > 0:
                raise ValueError(f"segment {segment.id} must be at or below z=0")
        if not MIN_RADIUS_M <= segment.radius_m <= MAX_RADIUS_M:
            raise ValueError(f"segment {segment.id} radius must be between 1e-4 and 0.5 m")
        if _distance(segment.start_m, segment.end_m) < MIN_LENGTH_TO_RADIUS * segment.radius_m:
            raise ValueError(f"segment {segment.id} must be at least 5 radii long (thin-wire model)")
        if -0.5 * (segment.start_m[2] + segment.end_m[2]) < segment.radius_m:
            raise ValueError(f"segment {segment.id} lies on the surface; bury its mid-point at least one radius")
    seen: dict[tuple, str] = {}
    for segment in segments:
        ends = tuple(sorted((tuple(round(c, 9) for c in segment.start_m), tuple(round(c, 9) for c in segment.end_m))))
        if ends in seen:
            raise ValueError(f"duplicate segment geometry: {seen[ends]} and {segment.id}")
        seen[ends] = segment.id
    for i, p in enumerate(segments):
        for q in segments[i + 1:]:
            if p.group != q.group and _segment_distance(p.start_m, p.end_m, q.start_m, q.end_m) <= p.radius_m + q.radius_m:
                raise ValueError(f"segments of different groups touch or cross: {p.id} and {q.id}")
    for group, current in injections_a.items():
        _token(group, "injection group")
        if group not in groups:
            raise ValueError(f"injection group has no electrode segments: {group}")
        if not math.isfinite(float(current)) or abs(float(current)) > MAX_CURRENT_A:
            raise ValueError(f"injected current for {group} must be finite and at most 1e6 A")
    for group, origin in (injection_origins or {}).items():
        _token(origin, "injection origin")
        if group not in injections_a:
            raise ValueError(f"injection origin given for a group without injection: {group}")
    point_ids: set[str] = set()
    for point in points:
        _token(point.id, "point id")
        if point.id in point_ids:
            raise ValueError(f"duplicate point id: {point.id}")
        point_ids.add(point.id)
        x, y, z = point.xyz_m
        if not all(map(math.isfinite, point.xyz_m)) or abs(x) > MAX_COORDINATE_M or abs(y) > MAX_COORDINATE_M:
            raise ValueError(f"point {point.id} coordinates are invalid")
        if not 0 <= z <= MAX_DEPTH_M:
            raise ValueError("potential query points must be at or above z=0")


def _limit_memory(limit_mb: int):
    """Return a pre-exec hook that caps the engine's address space where the OS enforces it."""
    if not sys.platform.startswith("linux") or not limit_mb:
        return None

    def apply() -> None:
        import resource
        limit = int(limit_mb) * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (limit, limit))

    return apply


def potential_difference_v(result: dict[str, Any], point_a_id: str, point_b_id: str) -> float:
    """Return absolute potential difference between two queried surface points."""
    potentials = result["potentials_v"]
    return abs(float(potentials[point_a_id]) - float(potentials[point_b_id]))


def touch_voltage_v(result: dict[str, Any], electrode_group: str, surface_point_id: str) -> float:
    """Return potential difference from an equipotential metal group to a surface point."""
    metal_v = result["groups"][electrode_group]["potential_v"]
    soil_v = result["potentials_v"][surface_point_id]
    return abs(float(metal_v) - float(soil_v))


def _token(value: str, label: str) -> str:
    allowed = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.:-"
    if not value or len(value) > 80 or any(char not in allowed for char in value):
        raise ValueError(f"{label} must use at most 80 letters, digits, _, ., : or -")
    return value


def _floats(values: tuple[float, float, float]) -> str:
    if len(values) != 3:
        raise ValueError("coordinates must contain x, y, z")
    return " ".join(format(float(value), ".17g") for value in values)


class PotentialEngineClient:
    """Runs the compiled engine once per calculation using a Popen stdin/stdout pipe."""

    def __init__(
        self,
        executable: str | os.PathLike[str] | None = None,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        memory_limit_mb: int = DEFAULT_MEMORY_LIMIT_MB,
    ):
        default = Path(__file__).resolve().parents[4] / "services" / "potential_engine" / "build" / "spat-potential-engine"
        self.executable = str(executable or os.getenv("SPAT_POTENTIAL_ENGINE", default))
        self.timeout_s = timeout_s
        self.memory_limit_mb = memory_limit_mb

    def calculate(
        self,
        *,
        soil_resistivity_ohm_m: float,
        segments: list[ElectrodeSegment],
        injections_a: dict[str, float],
        points: list[PotentialPoint],
        injection_origins: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Solve and return currents, potentials, solver diagnostics and a traceability record.

        `injection_origins` maps each injected group to a token naming where its current came
        from (for example `user`, `fault:bus-7`); it defaults to `unspecified`.
        """
        validate_request(soil_resistivity_ohm_m, segments, injections_a, points, injection_origins)
        origins = {group: (injection_origins or {}).get(group, "unspecified") for group in injections_a}
        lines = [PROTOCOL, f"{float(soil_resistivity_ohm_m):.17g} {len(segments)}"]
        for segment in segments:
            row = [
                segment.id, segment.group, segment.kind, _floats(segment.start_m),
                _floats(segment.end_m), format(float(segment.radius_m), ".17g"),
            ]
            lines.append(" ".join(row))
        lines.append(str(len(injections_a)))
        for group, current in injections_a.items():
            lines.append(f"{group} {float(current):.17g} {origins[group]}")
        lines.append(str(len(points)))
        for point in points:
            lines.append(f"{point.id} {_floats(point.xyz_m)}")
        lines.append("END")
        payload = "\n".join(lines) + "\n"

        started = time.monotonic()
        try:
            process = subprocess.Popen(
                [self.executable], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True, preexec_fn=_limit_memory(self.memory_limit_mb),
            )
        except OSError as exc:
            raise PotentialEngineError(f"could not start C++ potential engine: {exc}") from exc
        try:
            stdout, stderr = process.communicate(payload, timeout=self.timeout_s)
        except subprocess.TimeoutExpired as exc:
            process.kill()
            process.communicate()
            raise PotentialEngineError("C++ potential calculation exceeded its time limit") from exc
        if process.returncode:
            message = stdout.strip().split("\t", 2)
            detail = message[2] if len(message) > 2 and message[1] == "ERROR" else stderr.strip()
            raise PotentialEngineError(detail or f"C++ engine exited with status {process.returncode}")
        result = self._decode(stdout)
        result["trace"] = {
            **result.pop("metadata"),
            "engine_executable": self.executable,
            "engine_sha256": _file_sha256(self.executable),
            "request_sha256": hashlib.sha256(payload.encode()).hexdigest(),
            "calculated_at": datetime.now(timezone.utc).isoformat(),
            "duration_s": round(time.monotonic() - started, 6),
            "injections": [
                {"group": group, "current_a": float(current), "origin": origins[group]}
                for group, current in injections_a.items()
            ],
            "segments": [asdict(segment) for segment in segments],
        }
        return result

    @staticmethod
    def _decode(stdout: str) -> dict[str, Any]:
        rows = stdout.splitlines()
        if not rows or rows[0] != f"{PROTOCOL}\tOK" or rows[-1] != "END":
            raise PotentialEngineError("C++ engine returned an invalid response")
        result: dict[str, Any] = {
            "segment_currents_a": {}, "groups": {}, "potentials_v": {},
            "diagnostics": {}, "warnings": [], "metadata": {},
        }
        for row in rows[1:-1]:
            fields = row.split("\t")
            if fields[0] == "SEGMENT" and len(fields) == 3:
                result["segment_currents_a"][fields[1]] = float(fields[2])
            elif fields[0] == "GROUP" and len(fields) == 8:
                result["groups"][fields[1]] = {
                    "injected_current_a": float(fields[2]),
                    "potential_v": float(fields[3]),
                    "resistance_to_remote_earth_ohm": None if fields[4] == "null" else float(fields[4]),
                    "injection_origin": fields[5],
                    "current_balance_error_a": float(fields[6]),
                    "potential_spread_v": float(fields[7]),
                }
            elif fields[0] == "POINT" and len(fields) == 3:
                result["potentials_v"][fields[1]] = float(fields[2])
            elif fields[0] == "DIAG" and len(fields) == 3:
                result["diagnostics"][fields[1]] = float(fields[2])
            elif fields[0] == "META" and len(fields) == 3:
                result["metadata"][fields[1]] = fields[2]
            elif fields[0] == "WARNING" and len(fields) == 3:
                result["warnings"].append({"code": fields[1], "message": fields[2]})
            else:
                raise PotentialEngineError("C++ engine returned an invalid data row")
        return result


def _file_sha256(path: str) -> str | None:
    try:
        with open(path, "rb") as handle:
            return hashlib.file_digest(handle, "sha256").hexdigest()
    except OSError:
        return None


def rectangular_grid_segments(
    *,
    length_m: float,
    width_m: float,
    conductor_spacing_m: float,
    burial_depth_m: float,
    conductor_radius_m: float,
    group: str = "grid",
    rods_count: int = 0,
    rod_length_m: float = 2.4,
    discretization_m: float | None = None,
) -> list[ElectrodeSegment]:
    """Create a centered rectangular mesh and perimeter ground rods as line elements."""
    values = (length_m, width_m, conductor_spacing_m, burial_depth_m,
              conductor_radius_m, rod_length_m)
    if any(float(value) <= 0 for value in values) or rods_count < 0:
        raise ValueError("grid dimensions, spacing, burial depth, radius and rod length must be positive")
    max_piece = float(discretization_m or conductor_spacing_m)
    if max_piece <= 0:
        raise ValueError("discretization_m must be positive")
    step = min(float(conductor_spacing_m), max_piece)
    result: list[ElectrodeSegment] = []

    def axis_positions(span: float, target_spacing: float) -> list[float]:
        count = max(2, int(ceil(span / target_spacing)) + 1)
        return [-span / 2 + i * span / (count - 1) for i in range(count)]

    def add_line(prefix: str, kind: str, start: tuple[float, float, float], end: tuple[float, float, float], radius: float) -> None:
        pieces = max(1, int(ceil(sum((b-a)**2 for a, b in zip(start, end)) ** 0.5 / step)))
        for piece in range(pieces):
            t0, t1 = piece / pieces, (piece + 1) / pieces
            a = tuple(start[i] + (end[i] - start[i]) * t0 for i in range(3))
            b = tuple(start[i] + (end[i] - start[i]) * t1 for i in range(3))
            result.append(ElectrodeSegment(f"{prefix}_{piece}", group, kind, a, b, radius))

    z = -float(burial_depth_m)
    spacing = float(conductor_spacing_m)
    for index, y in enumerate(axis_positions(float(width_m), spacing)):
        add_line(f"grid_x{index}", "grid", (-length_m / 2, y, z), (length_m / 2, y, z), conductor_radius_m)
    for index, x in enumerate(axis_positions(float(length_m), spacing)):
        add_line(f"grid_y{index}", "grid", (x, -width_m / 2, z), (x, width_m / 2, z), conductor_radius_m)

    perimeter = 2.0 * (float(length_m) + float(width_m))
    for index in range(rods_count):
        position = perimeter * index / max(rods_count, 1)
        if position < length_m:
            x, y = -length_m / 2 + position, -width_m / 2
        elif position < length_m + width_m:
            x, y = length_m / 2, -width_m / 2 + position - length_m
        elif position < 2 * length_m + width_m:
            x, y = length_m / 2 - (position - length_m - width_m), width_m / 2
        else:
            x, y = -length_m / 2, width_m / 2 - (position - 2 * length_m - width_m)
        add_line(f"rod{index}", "rod", (x, y, z), (x, y, z - rod_length_m), conductor_radius_m)
    return result


def rectangular_surface_points(
    *, x_min_m: float, x_max_m: float, y_min_m: float, y_max_m: float,
    spacing_m: float, z_m: float = 0.0,
) -> list[PotentialPoint]:
    """Create a regular set of points for plotting surface-potential contours."""
    if spacing_m <= 0 or x_max_m <= x_min_m or y_max_m <= y_min_m or z_m < 0:
        raise ValueError("surface bounds, spacing and elevation are invalid")
    nx = int(ceil((x_max_m - x_min_m) / spacing_m))
    ny = int(ceil((y_max_m - y_min_m) / spacing_m))
    return [
        PotentialPoint(f"surface_{ix}_{iy}", (x_min_m + (x_max_m-x_min_m)*ix/nx,
                                               y_min_m + (y_max_m-y_min_m)*iy/ny, z_m))
        for iy in range(ny + 1) for ix in range(nx + 1)
    ]
