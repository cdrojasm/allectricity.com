import React from "react";

// Overlay of an optimizer alternative on the base design: kept conductor in grey, added in green, removed in red dashes.
// The optimizer returns its network cut at every junction while a drawn plan keeps whole strokes, so the two are compared
// by geometric coverage, not by endpoints: a base stroke split into pieces that are all still there counts as kept.
const EPS = 1e-3;
const len = (s) => Math.hypot(s.end.x - s.start.x, s.end.y - s.start.y);
const at = (s, t) => ({ x: s.start.x + (s.end.x - s.start.x) * t, y: s.start.y + (s.end.y - s.start.y) * t });

// Parameter of point p along s (0 at start, 1 at end) when p lies on the line of s; null otherwise.
function along(s, p) {
  const L = len(s);
  if (L < EPS) return null;
  const ux = (s.end.x - s.start.x) / L, uy = (s.end.y - s.start.y) / L;
  const dx = p.x - s.start.x, dy = p.y - s.start.y;
  if (Math.abs(dx * uy - dy * ux) > EPS) return null;
  return (dx * ux + dy * uy) / L;
}

// The parts of `s` not covered by any segment of `others` lying on the same line.
function uncovered(s, others) {
  const L = len(s);
  if (L < EPS) return [];
  const intervals = others.map((o) => {
    const a = along(s, o.start), b = along(s, o.end);
    return a == null || b == null ? null : [Math.max(0, Math.min(a, b)), Math.min(1, Math.max(a, b))];
  }).filter((iv) => iv && iv[1] - iv[0] > EPS / L).sort((p, q) => p[0] - q[0]);
  const gaps = [];
  let cursor = 0;
  for (const [a, b] of intervals) {
    if (a > cursor + EPS / L) gaps.push([cursor, a]);
    cursor = Math.max(cursor, b);
  }
  if (cursor < 1 - EPS / L) gaps.push([cursor, 1]);
  return gaps.map(([a, b]) => ({ start: at(s, a), end: at(s, b) }));
}

const sum = (segments) => segments.reduce((total, s) => total + len(s), 0);
const rodKey = (p) => `${Math.round(p.x * 100)},${Math.round(p.y * 100)}`;

export function diffGeometry(base, alternative) {
  const baseLines = base.conductors || [], altLines = alternative.conductors || [];
  const addedConductors = altLines.flatMap((s) => uncovered(s, baseLines));
  const removedConductors = baseLines.flatMap((s) => uncovered(s, altLines));
  const baseRods = new Map((base.rods || []).map((p) => [rodKey(p), p]));
  const altRods = new Map((alternative.rods || []).map((p) => [rodKey(p), p]));
  const lengthOf = (rod, geometry) => Number(rod.length_m ?? geometry.rod_length_m ?? NaN);
  const keptRods = [], resizedRods = [];
  for (const [key, rod] of altRods) {
    if (!baseRods.has(key)) continue;
    const before = lengthOf(baseRods.get(key), base), after = lengthOf(rod, alternative);
    (Number.isFinite(before) && Number.isFinite(after) && Math.abs(before - after) > EPS ? resizedRods : keptRods).push(rod);
  }
  return {
    keptConductors: altLines, addedConductors, removedConductors,
    addedLengthM: sum(addedConductors), removedLengthM: sum(removedConductors),
    keptRods, resizedRods,
    addedRods: [...altRods].filter(([k]) => !baseRods.has(k)).map(([, v]) => v),
    removedRods: [...baseRods].filter(([k]) => !altRods.has(k)).map(([, v]) => v),
  };
}

const areaPoints = (a) => a.polygon || (a.x_min != null ? [
  { x: a.x_min, y: a.y_min }, { x: a.x_max, y: a.y_min }, { x: a.x_max, y: a.y_max }, { x: a.x_min, y: a.y_max }] : null);
const meters = (value) => `${value.toLocaleString("es-CO", { maximumFractionDigits: 0 })} m`;

export default function TopologyPreview({ base, alternative }) {
  if (!base?.length_m || !base?.width_m || !alternative) return null;
  const d = diffGeometry(base, alternative);
  const W = Number(base.length_m), H = Number(base.width_m);
  const flip = (p) => `${p.x},${H - p.y}`;
  const line = (s, i, cls) => <line key={`${cls}${i}`} className={cls} x1={s.start.x} y1={H - s.start.y} x2={s.end.x} y2={H - s.end.y}/>;
  const rod = (p, i, cls) => <circle key={`${cls}${i}`} className={cls} cx={p.x} cy={H - p.y} r={Math.max(W, H) / 80}/>;
  return <figure className="topology-preview">
    <svg viewBox={`${-W * 0.02} ${-H * 0.02} ${W * 1.04} ${H * 1.04}`} role="img" aria-label="Alternativa sobre el diseño base">
      <rect x="0" y="0" width={W} height={H} className="site"/>
      {(base.areas || []).filter((a) => areaPoints(a)).map((a, i) =>
        <polygon key={`a${i}`} className={a.type === "non_intervenible" ? "blocked" : "allowed"} points={areaPoints(a).map(flip).join(" ")}/>)}
      {(base.structures || []).filter((s) => s.x != null).map((s, i) =>
        <rect key={`s${i}`} className="blocked" x={s.x - s.width / 2} y={H - s.y - s.height / 2} width={s.width} height={s.height}/>)}
      {d.removedConductors.map((s, i) => line(s, i, "removed"))}
      {d.keptConductors.map((s, i) => line(s, i, "kept"))}
      {d.addedConductors.map((s, i) => line(s, i, "added"))}
      {d.removedRods.map((p, i) => rod(p, i, "removed"))}
      {d.keptRods.map((p, i) => rod(p, i, "kept"))}
      {d.resizedRods.map((p, i) => rod(p, i, "resized"))}
      {d.addedRods.map((p, i) => rod(p, i, "added"))}
    </svg>
    <figcaption>
      <span className="legend added">Añadido: {meters(d.addedLengthM)} de conductor · {d.addedRods.length} varillas</span>
      <span className="legend removed">Quitado: {meters(d.removedLengthM)} de conductor · {d.removedRods.length} varillas</span>
      <span className="legend kept">Se mantienen: {d.keptRods.length} varillas{d.resizedRods.length ? ` · ${d.resizedRods.length} con otro largo` : ""}</span>
    </figcaption>
  </figure>;
}
