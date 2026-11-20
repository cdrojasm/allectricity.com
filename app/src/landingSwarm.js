// Particle swarm for the public landing. One set of particles flies between "formations",
// each one a picture of a step in Allectricity's workflow (documents → graph, soil, grid, potential, study).
// Plain canvas 2D, no dependencies; positions live in a small 3D world projected by a slow camera.

const TAU = Math.PI * 2;
const COLORS = ["158,240,216", "62,168,148", "255,150,96"]; // mint, teal, hot (unsafe touch voltage)
const ALPHA_LEVELS = 4;

function seeded(seed) {
  let s = seed >>> 0;
  return () => {
    s = (s * 1664525 + 1013904223) >>> 0;
    return s / 4294967296;
  };
}

function normal(r) {
  return (r() + r() + r() + r() - 2) * 0.866;
}

function formation(n) {
  return { points: new Float32Array(n * 3), tone: new Uint8Array(n) };
}

function put(f, i, x, y, z, tone = 0) {
  f.points[i * 3] = x;
  f.points[i * 3 + 1] = y;
  f.points[i * 3 + 2] = z;
  f.tone[i] = tone;
}

function surfaceGrid(n, share, half) {
  const side = Math.max(8, Math.floor(Math.sqrt(n * share)));
  const cells = [];
  for (let a = 0; a < side; a += 1) {
    for (let b = 0; b < side; b += 1) cells.push([-half + (2 * half * a) / (side - 1), -half + (2 * half * b) / (side - 1)]);
  }
  return cells;
}

// Hero: a field of points rolling like ground potential after current is injected.
function buildHero(n) {
  const f = formation(n);
  const r = seeded(11);
  const cells = surfaceGrid(n, 1, 1.25);
  f.base = new Float32Array(n * 2);
  for (let i = 0; i < n; i += 1) {
    const [x, z] = cells[i] || [(r() * 2 - 1) * 1.25, (r() * 2 - 1) * 1.25];
    f.base[i * 2] = x + (r() - 0.5) * 0.012;
    f.base[i * 2 + 1] = z + (r() - 0.5) * 0.012;
  }
  f.pulses = [];
  f.nextPulse = 0.6;
  f.update = (t) => {
    if (t > f.nextPulse) {
      f.pulses.push({ x: (r() - 0.5) * 1.6, z: (r() - 0.5) * 1.2, t0: t });
      f.nextPulse = t + 3.2 + r() * 2.2;
    }
    f.pulses = f.pulses.filter((p) => t - p.t0 < 7);
    for (let i = 0; i < n; i += 1) {
      const x = f.base[i * 2];
      const z = f.base[i * 2 + 1];
      let y = 0.05 * Math.sin(1.7 * x + t * 0.55) * Math.cos(1.3 * z - t * 0.4) + 0.03 * Math.sin(3.1 * (x + z) - t * 0.8);
      let hot = 0;
      for (const p of f.pulses) {
        const age = t - p.t0;
        const d = Math.hypot(x - p.x, z - p.z);
        const front = d - age * 0.62;
        const ring = Math.exp(-front * front * 26) * Math.exp(-age * 0.45);
        y += 0.2 * ring * Math.cos(front * 9);
        y += 0.24 * Math.exp(-d * d * 9) * Math.exp(-age * 1.6);
        hot = Math.max(hot, ring);
      }
      put(f, i, x, y - 0.1, z, hot > 0.45 ? 2 : hot > 0.1 || Math.hypot(x, z) < 0.55 ? 0 : 1);
    }
  };
  f.pulse = (t, x = 0, z = 0) => f.pulses.push({ x, z, t0: t });
  f.update(0);
  return f;
}

// 01 — documents become a knowledge graph: clusters (claims) linked by edges (evidence).
function buildGraph(n) {
  const f = formation(n);
  const r = seeded(23);
  const nodes = [];
  for (let k = 0; k < 17; k += 1) {
    const u = r() * TAU;
    const v = Math.acos(2 * r() - 1);
    const rad = 0.45 + r() * 0.65;
    nodes.push([rad * Math.sin(v) * Math.cos(u), rad * Math.cos(v) * 0.8, rad * Math.sin(v) * Math.sin(u), 0.04 + r() * 0.06]);
  }
  nodes[0] = [0, 0, 0, 0.13];
  const edges = [];
  nodes.forEach((a, ia) => {
    const near = nodes
      .map((b, ib) => [ib, Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2])])
      .filter(([ib]) => ib !== ia)
      .sort((p, q) => p[1] - q[1])
      .slice(0, 2);
    near.forEach(([ib]) => edges.push([ia, ib]));
    if (ia > 0 && ia % 3 === 0) edges.push([ia, 0]);
  });
  for (let i = 0; i < n; i += 1) {
    if (r() < 0.42) {
      const node = nodes[Math.floor(r() * nodes.length)];
      put(f, i, node[0] + normal(r) * node[3], node[1] + normal(r) * node[3], node[2] + normal(r) * node[3], r() < 0.25 ? 2 : 0);
    } else {
      const [ia, ib] = edges[Math.floor(r() * edges.length)];
      const a = nodes[ia];
      const b = nodes[ib];
      const s = r();
      put(f, i, a[0] + (b[0] - a[0]) * s + normal(r) * 0.008, a[1] + (b[1] - a[1]) * s + normal(r) * 0.008, a[2] + (b[2] - a[2]) * s + normal(r) * 0.008, 1);
    }
  }
  return f;
}

// 02 — stratified soil with a Wenner array: layer interfaces, probes and current lines.
function buildSoil(n) {
  const f = formation(n);
  const r = seeded(37);
  const interfaces = [
    { y: 0.42, wave: 0.02, share: 0.24, tone: 0 },
    { y: 0.12, wave: 0.06, share: 0.2, tone: 1 },
    { y: -0.32, wave: 0.09, share: 0.16, tone: 1 },
    { y: -0.78, wave: 0.03, share: 0.1, tone: 1 },
  ];
  const probes = [-0.9, -0.3, 0.3, 0.9];
  for (let i = 0; i < n; i += 1) {
    const pick = r();
    let acc = 0;
    const layer = interfaces.find((it) => (acc += it.share) > pick);
    if (layer) {
      const x = (r() * 2 - 1) * 1.25;
      const z = (r() * 2 - 1) * 0.85;
      const y = layer.y + layer.wave * Math.sin(x * 3.1 + z * 1.7) + layer.wave * 0.6 * Math.cos(z * 4.3);
      put(f, i, x, y, z, layer.tone);
    } else if (pick < 0.78) {
      const p = probes[Math.floor(r() * probes.length)];
      put(f, i, p + normal(r) * 0.006, 0.42 + r() * 0.34, normal(r) * 0.006, 0);
    } else {
      // current lines between the outer probes, dipping into the soil
      const depth = 0.25 + Math.floor(r() * 4) * 0.17;
      const s = r() * Math.PI;
      put(f, i, -0.9 * Math.cos(s), 0.42 - Math.sin(s) * depth * 1.6, (r() - 0.5) * 0.04, 2);
    }
  }
  return f;
}

const MESH = 6; // conductors per direction
const HALF = 0.85;

// 03 — grounding grid: buried conductors and rods.
function buildGrid(n) {
  const f = formation(n);
  const r = seeded(41);
  const lines = MESH;
  const rods = [];
  for (let a = 0; a < lines; a += 1) {
    for (let b = 0; b < lines; b += 1) {
      const edge = a === 0 || b === 0 || a === lines - 1 || b === lines - 1;
      if (edge && (a + b) % 2 === 0) rods.push([-HALF + (2 * HALF * a) / (lines - 1), -HALF + (2 * HALF * b) / (lines - 1)]);
    }
  }
  for (let i = 0; i < n; i += 1) {
    const pick = r();
    if (pick < 0.68) {
      const fixed = -HALF + (2 * HALF * Math.floor(r() * lines)) / (lines - 1);
      const run = (r() * 2 - 1) * HALF;
      const jitter = normal(r) * 0.006;
      if (r() < 0.5) put(f, i, fixed + jitter, jitter, run, 0);
      else put(f, i, run, jitter, fixed + jitter, 0);
    } else if (pick < 0.9) {
      const [x, z] = rods[Math.floor(r() * rods.length)];
      put(f, i, x + normal(r) * 0.006, -r() * 0.62, z + normal(r) * 0.006, 2);
    } else {
      put(f, i, (r() * 2 - 1) * 1.3, 0.32 + normal(r) * 0.004, (r() * 2 - 1) * 1.3, 1); // ground surface hint
    }
  }
  return f;
}

// 04 — surface potential over the grid; corner meshes exceed the tolerable touch voltage.
function buildSafety(n) {
  const f = formation(n);
  const r = seeded(53);
  const cells = surfaceGrid(n, 0.8, 1.2);
  const surfaceCount = cells.length;
  f.base = new Float32Array(n * 2);
  f.kind = new Uint8Array(n);
  for (let i = 0; i < n; i += 1) {
    if (i < surfaceCount) {
      f.base[i * 2] = cells[i][0];
      f.base[i * 2 + 1] = cells[i][1];
    } else {
      const fixed = -HALF + (2 * HALF * Math.floor(r() * MESH)) / (MESH - 1);
      const run = (r() * 2 - 1) * HALF;
      const flip = r() < 0.5;
      f.base[i * 2] = flip ? fixed : run;
      f.base[i * 2 + 1] = flip ? run : fixed;
      f.kind[i] = 1;
    }
  }
  const pitch = (2 * HALF) / (MESH - 1);
  f.update = (t) => {
    const breathe = 1 + 0.05 * Math.sin(t * 1.1);
    for (let i = 0; i < n; i += 1) {
      const x = f.base[i * 2];
      const z = f.base[i * 2 + 1];
      if (f.kind[i]) {
        put(f, i, x, -0.42, z, 1);
        continue;
      }
      const dx = Math.max(0, Math.abs(x) - HALF);
      const dz = Math.max(0, Math.abs(z) - HALF);
      const outside = Math.hypot(dx, dz);
      let v = 0.62 / (1 + (outside / 0.32) ** 2);
      let touch = 0;
      if (outside === 0) {
        const sx = Math.sin((Math.PI * (x + HALF)) / pitch) ** 2;
        const sz = Math.sin((Math.PI * (z + HALF)) / pitch) ** 2;
        const edgeFactor = 0.6 + 0.8 * Math.max(Math.abs(x), Math.abs(z)) / HALF;
        touch = 0.07 * (sx + sz) * 0.5 * edgeFactor;
        v -= touch;
      }
      const tone = touch > 0.042 && Math.abs(x) > 0.48 && Math.abs(z) > 0.48 ? 2 : outside > 0.05 ? 1 : 0;
      put(f, i, x, v * breathe - 0.18, z, tone);
    }
  };
  f.update(0);
  return f;
}

// 05 — the shareable study: a page with headings, text, a contour plot and a signature.
function buildStudy(n) {
  const f = formation(n);
  const r = seeded(67);
  const W = 0.68;
  const H = 0.92;
  const rows = [0.5, 0.42, 0.34, 0.26, 0.18];
  for (let i = 0; i < n; i += 1) {
    const pick = r();
    let x;
    let y;
    let tone = 0;
    if (pick < 0.16) {
      if (r() < W / (W + H)) { x = -W + r() * 2 * W; y = r() < 0.5 ? H : -H; }
      else { x = r() < 0.5 ? W : -W; y = -H + r() * 2 * H; }
      tone = 1;
    } else if (pick < 0.27) {
      x = -W + 0.1 + r() * 0.75;
      y = 0.72 + normal(r) * 0.022;
    } else if (pick < 0.55) {
      const row = rows[Math.floor(r() * rows.length)];
      const length = row === 0.18 ? 0.7 : 1.16;
      x = -W + 0.1 + r() * length;
      y = row + normal(r) * 0.006;
      tone = 1;
    } else if (pick < 0.88) {
      const ring = 1 + Math.floor(r() * 5);
      const a = r() * TAU;
      const rad = ring * 0.062;
      x = 0.05 + Math.cos(a) * rad * 1.35;
      y = -0.38 + Math.sin(a) * rad;
      tone = ring <= 1 ? 2 : 0;
    } else {
      x = 0.12 + r() * 0.42;
      y = -0.8 + Math.sin(x * 22) * 0.02;
      tone = 1;
    }
    put(f, i, x, y, normal(r) * 0.01, tone);
  }
  return f;
}

const BUILDERS = [buildHero, buildGraph, buildSoil, buildGrid, buildSafety, buildStudy];

// Camera per formation: ox/oy screen anchor, scale relative to the short side, pitch and yaw speed.
const CAMERAS = [
  { ox: 0.66, oy: 0.6, scale: 0.46, pitch: 0.5, yaw: 0.04, mobile: { ox: 0.5, oy: 0.74, scale: 0.6 } },
  { ox: 0.68, oy: 0.5, scale: 0.4, pitch: 0.2, yaw: 0.12, mobile: { ox: 0.5, oy: 0.3, scale: 0.42 } },
  { ox: 0.68, oy: 0.5, scale: 0.3, pitch: 0.3, yaw: 0.06, mobile: { ox: 0.5, oy: 0.3, scale: 0.34 } },
  { ox: 0.68, oy: 0.52, scale: 0.38, pitch: 0.52, yaw: 0.08, mobile: { ox: 0.5, oy: 0.3, scale: 0.42 } },
  { ox: 0.68, oy: 0.56, scale: 0.34, pitch: 0.62, yaw: 0.06, mobile: { ox: 0.5, oy: 0.32, scale: 0.36 } },
  { ox: 0.68, oy: 0.52, scale: 0.36, pitch: 0.05, yaw: 0.0, face: -0.28, mobile: { ox: 0.5, oy: 0.3, scale: 0.3 } },
];

export function createSwarm(canvas, { reducedMotion = false } = {}) {
  const ctx = canvas.getContext("2d");
  let width = 0;
  let height = 0;
  let dpr = 1;
  const small = window.matchMedia("(max-width: 820px)").matches;
  const n = small ? 1800 : 4200;
  const formations = BUILDERS.map((build) => build(n));
  const px = new Float32Array(n);
  const py = new Float32Array(n);
  const pz = new Float32Array(n);
  const vx = new Float32Array(n);
  const vy = new Float32Array(n);
  const vz = new Float32Array(n);
  const sx = new Float32Array(n); // screen-space push from the pointer
  const sy = new Float32Array(n);
  const stiffness = new Float32Array(n);
  const owner = new Uint8Array(n); // formation each particle currently follows
  const release = new Float32Array(n);
  const buckets = Array.from({ length: COLORS.length * ALPHA_LEVELS }, () => new Int32Array(n));
  const bucketSize = new Int32Array(buckets.length);
  const screenX = new Float32Array(n);
  const screenY = new Float32Array(n);
  const screenS = new Float32Array(n);
  const r = seeded(97);
  for (let i = 0; i < n; i += 1) {
    const a = r() * TAU;
    const rad = 1.6 + r() * 1.4;
    px[i] = Math.cos(a) * rad;
    py[i] = normal(r) * 0.6;
    pz[i] = Math.sin(a) * rad;
    stiffness[i] = 2.4 + r() * 3.6;
    release[i] = r() * 0.9;
  }
  let active = 0;
  let pending = 0;
  let switchedAt = 0;
  const cam = { ...CAMERAS[0], yawAngle: -0.5 };
  const pointer = { x: -9999, y: -9999, tx: 0, ty: 0, px: 0, py: 0 };
  let frame = 0;
  let running = true;
  let last = performance.now();
  let clock = 0;

  function resize() {
    dpr = Math.min(window.devicePixelRatio || 1, 2);
    width = canvas.clientWidth;
    height = canvas.clientHeight;
    canvas.width = Math.round(width * dpr);
    canvas.height = Math.round(height * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    if (reducedMotion) draw();
  }

  function target(i) {
    const f = formations[owner[i]];
    return f.points;
  }

  function cameraFor(index) {
    const base = CAMERAS[index];
    return small ? { ...base, ...base.mobile } : base;
  }

  function step(dt) {
    clock += dt;
    for (const f of formations) if (f.update && (f === formations[active] || f === formations[pending])) f.update(clock);
    const goal = cameraFor(pending);
    const ease = 1 - Math.exp(-dt * 2.2);
    for (const key of ["ox", "oy", "scale", "pitch"]) cam[key] += (goal[key] - cam[key]) * ease;
    cam.yawAngle += dt * goal.yaw + (pointer.tx * 0.25 - pointer.px) * ease * 0.6;
    if (goal.face !== undefined) {
      // formations meant to be read (the study page) turn to face the viewer
      const delta = ((((goal.face - cam.yawAngle) % TAU) + TAU + Math.PI) % TAU) - Math.PI;
      cam.yawAngle += delta * ease;
    }
    pointer.px += (pointer.tx * 0.25 - pointer.px) * ease * 0.6;
    pointer.py += (pointer.ty * 0.12 - pointer.py) * ease * 0.6;
    const since = clock - switchedAt;
    for (let i = 0; i < n; i += 1) {
      if (owner[i] !== pending && since > release[i]) owner[i] = pending;
      const pts = target(i);
      const tone = formations[owner[i]].tone[i];
      const tx = pts[i * 3];
      const ty = pts[i * 3 + 1];
      const tz = pts[i * 3 + 2];
      const dx = tx - px[i];
      const dy = ty - py[i];
      const dz = tz - pz[i];
      const k = stiffness[i];
      const damping = 2 * Math.sqrt(k) * 0.78;
      const dist = Math.min(1.2, Math.hypot(dx, dy, dz));
      // tangential swirl while migrating gives the flock its curve; it fades as the particle arrives
      const radial = Math.hypot(px[i], pz[i]) + 0.2;
      const swirl = (dist * 1.6) / radial;
      const wob = 0.045 + (tone === 2 ? 0.03 : 0);
      vx[i] += (dx * k - vx[i] * damping - pz[i] * swirl + Math.sin(clock * 1.3 + i * 0.37) * wob) * dt;
      vy[i] += (dy * k - vy[i] * damping + Math.cos(clock * 1.1 + i * 0.73) * wob) * dt;
      vz[i] += (dz * k - vz[i] * damping + px[i] * swirl + Math.sin(clock * 0.9 + i * 0.51) * wob) * dt;
      px[i] += vx[i] * dt;
      py[i] += vy[i] * dt;
      pz[i] += vz[i] * dt;
      sx[i] *= 0.92;
      sy[i] *= 0.92;
    }
    if (since > 1.2) active = pending;
  }

  function project() {
    const cy = Math.cos(cam.yawAngle);
    const syaw = Math.sin(cam.yawAngle);
    const pitch = cam.pitch + pointer.py;
    const cp = Math.cos(pitch);
    const sp = Math.sin(pitch);
    const scale = Math.min(width, height) * cam.scale * (small ? 1 : 1.15);
    const ox = width * cam.ox;
    const oy = height * cam.oy;
    const radius = 110;
    for (let i = 0; i < n; i += 1) {
      const x1 = px[i] * cy - pz[i] * syaw;
      const z1 = px[i] * syaw + pz[i] * cy;
      const y2 = py[i] * cp - z1 * sp;
      const z2 = py[i] * sp + z1 * cp;
      const s = 5 / (5 + z2);
      let x = ox + x1 * s * scale;
      let y = oy - y2 * s * scale;
      const mx = x - pointer.x;
      const my = y - pointer.y;
      const d2 = mx * mx + my * my;
      if (d2 < radius * radius && d2 > 1) {
        const d = Math.sqrt(d2);
        const push = (1 - d / radius) * 2.6;
        sx[i] += (mx / d) * push;
        sy[i] += (my / d) * push;
      }
      screenX[i] = x + sx[i];
      screenY[i] = y + sy[i];
      screenS[i] = s;
    }
  }

  function draw() {
    if (reducedMotion) {
      // Static picture: snap every particle onto the active formation.
      for (const f of formations) f.update?.(4);
      const pts = formations[pending].points;
      for (let i = 0; i < n; i += 1) { owner[i] = pending; px[i] = pts[i * 3]; py[i] = pts[i * 3 + 1]; pz[i] = pts[i * 3 + 2]; }
      Object.assign(cam, cameraFor(pending));
    }
    project();
    ctx.clearRect(0, 0, width, height);
    bucketSize.fill(0);
    for (let i = 0; i < n; i += 1) {
      const tone = formations[owner[i]].tone[i];
      const depth = Math.max(0, Math.min(ALPHA_LEVELS - 1, Math.floor(((screenS[i] - 0.8) / 0.42) * ALPHA_LEVELS)));
      const b = tone * ALPHA_LEVELS + depth;
      buckets[b][bucketSize[b]++] = i;
    }
    for (let b = 0; b < buckets.length; b += 1) {
      if (!bucketSize[b]) continue;
      const tone = Math.floor(b / ALPHA_LEVELS);
      const depth = b % ALPHA_LEVELS;
      ctx.fillStyle = `rgba(${COLORS[tone]},${0.34 + depth * 0.21})`;
      const list = buckets[b];
      const sizeBase = tone === 2 ? 2.4 : 1.8;
      for (let k = 0; k < bucketSize[b]; k += 1) {
        const i = list[k];
        const size = sizeBase * screenS[i];
        ctx.fillRect(screenX[i] - size / 2, screenY[i] - size / 2, size, size);
      }
    }
  }

  function loop(now) {
    if (!running) return;
    const dt = Math.min(0.033, (now - last) / 1000);
    last = now;
    step(dt);
    draw();
    frame = requestAnimationFrame(loop);
  }

  resize();
  window.addEventListener("resize", resize);
  if (reducedMotion) draw();
  else frame = requestAnimationFrame(loop);

  return {
    setFormation(index) {
      if (index === pending) return;
      pending = index;
      switchedAt = clock;
      for (let i = 0; i < n; i += 1) release[i] = Math.random() * 0.9;
      if (reducedMotion) draw();
    },
    pointer(x, y) {
      pointer.x = x;
      pointer.y = y;
      pointer.tx = width ? (x / width - 0.5) : 0;
      pointer.ty = height ? (y / height - 0.5) : 0;
    },
    leave() {
      pointer.x = -9999;
      pointer.y = -9999;
      pointer.tx = 0;
      pointer.ty = 0;
    },
    strike() {
      formations[0].pulse?.(clock, (Math.random() - 0.5) * 0.8, (Math.random() - 0.5) * 0.6);
    },
    destroy() {
      running = false;
      cancelAnimationFrame(frame);
      window.removeEventListener("resize", resize);
    },
  };
}
