import React, { useEffect, useMemo, useRef, useState } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { X } from "lucide-react";

// Vertex budget per resolution: the raster is decimated so the surface never exceeds it.
const RESOLUTIONS = { completa: 40000, media: 10000, baja: 2500 };
const fmt = (value, digits = 1) => Number(value).toLocaleString("es-CO", { maximumFractionDigits: digits });

function decimation(nx, ny, budget) {
  let step = 1;
  while (Math.ceil(nx / step) * Math.ceil(ny / step) > budget) step += 1;
  return step;
}

function colorFor(t, color) {
  // Same scale as the 2D map: blue (low) to red (high).
  color.setHSL((220 - 220 * Math.min(1, Math.max(0, t))) / 360, 0.78, 0.52);
  return color;
}

/**
 * 3D view of a potential calculation: the surface of touch voltage (GPR − U) or potential U over
 * the plan, the tolerable touch voltage as a translucent plane, the buried grid and rods, and the
 * worst touch and step locations. It renders only when the camera moves.
 */
export default function Surface3D({ calculation, plan, onClose }) {
  const mount = useRef(null);
  const [mode, setMode] = useState("touch");
  const [resolution, setResolution] = useState("completa");
  const [exaggeration, setExaggeration] = useState(1);
  const result = calculation.result;
  const field = result.surface_potential;
  const gpr = result.gpr_v;
  const touch = result.safety?.[0]?.criteria?.find((c) => c.criterion === "touch");
  const tolerable = touch?.tolerable_v;

  const data = useMemo(() => {
    // Touch voltage is only evaluated inside the grid outline: show that area only.
    const inside = mode === "touch" && field.grid_width_m;
    const i0 = inside ? Math.round(field.grid_x_m / field.spacing_m) : 0;
    const j0 = inside ? Math.round(field.grid_y_m / field.spacing_m) : 0;
    const i1 = inside ? Math.min(field.nx - 1, i0 + Math.round(field.grid_width_m / field.spacing_m)) : field.nx - 1;
    const j1 = inside ? Math.min(field.ny - 1, j0 + Math.round(field.grid_height_m / field.spacing_m)) : field.ny - 1;
    const step = decimation(i1 - i0 + 1, j1 - j0 + 1, RESOLUTIONS[resolution]);
    const xs = [], ys = [];
    for (let i = i0; i <= i1; i += step) xs.push(i);
    if (xs[xs.length - 1] !== i1) xs.push(i1);
    for (let j = j0; j <= j1; j += step) ys.push(j);
    if (ys[ys.length - 1] !== j1) ys.push(j1);
    const value = (i, j) => {
      const u = field.values_v[j * field.nx + i];
      return mode === "touch" ? Math.max(0, gpr - u) : u;
    };
    let min = Infinity, max = -Infinity;
    for (const j of ys) for (const i of xs) { const v = value(i, j); if (v < min) min = v; if (v > max) max = v; }
    const x = (i) => field.x_min_m + i * field.spacing_m, y = (j) => field.y_min_m + j * field.spacing_m;
    return { step, xs, ys, value, min, max, extent: { x0: x(i0), x1: x(i1), y0: y(j0), y1: y(j1) } };
  }, [field, gpr, mode, resolution]);

  useEffect(() => {
    const node = mount.current;
    if (!node) return undefined;
    const width = field.spacing_m * (field.nx - 1), depth = field.spacing_m * (field.ny - 1);
    const size = Math.max(width, depth);
    // Potential is drawn relative to its minimum so the surface rests on the ground above the grid.
    const base = mode === "touch" ? 0 : data.min;
    const top = mode === "touch" ? Math.max(data.max, tolerable || 0) : data.max - base;
    const heightScale = (0.35 * size * exaggeration) / (top || 1);
    const scene = new THREE.Scene();
    scene.background = new THREE.Color("#f6f9f8");
    const camera = new THREE.PerspectiveCamera(45, node.clientWidth / node.clientHeight, size / 100, size * 20);
    camera.position.set(size * 0.9, size * 0.75, size * 1.05);
    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setSize(node.clientWidth, node.clientHeight);
    node.appendChild(renderer.domElement);
    scene.add(new THREE.AmbientLight(0xffffff, 0.75));
    const sun = new THREE.DirectionalLight(0xffffff, 0.8);
    sun.position.set(size, size * 2, size * 0.5);
    scene.add(sun);

    // Surface: plan x -> X, plan y -> -Z, value -> Y.
    const { xs, ys, value, min, max } = data;
    const positions = new Float32Array(xs.length * ys.length * 3), colors = new Float32Array(xs.length * ys.length * 3);
    const color = new THREE.Color();
    ys.forEach((j, row) => xs.forEach((i, col) => {
      const k = (row * xs.length + col) * 3, v = value(i, j);
      positions[k] = field.x_min_m + i * field.spacing_m;
      positions[k + 1] = (v - base) * heightScale;
      positions[k + 2] = -(field.y_min_m + j * field.spacing_m);
      colorFor((v - min) / (max - min || 1), color).toArray(colors, k);
    }));
    const indices = [];
    for (let row = 0; row < ys.length - 1; row += 1) for (let col = 0; col < xs.length - 1; col += 1) {
      const a = row * xs.length + col, b = a + 1, c = a + xs.length, d = c + 1;
      indices.push(a, c, b, b, c, d);
    }
    const surfaceGeometry = new THREE.BufferGeometry();
    surfaceGeometry.setAttribute("position", new THREE.BufferAttribute(positions, 3));
    surfaceGeometry.setAttribute("color", new THREE.BufferAttribute(colors, 3));
    surfaceGeometry.setIndex(indices);
    surfaceGeometry.computeVertexNormals();
    scene.add(new THREE.Mesh(surfaceGeometry, new THREE.MeshLambertMaterial({ vertexColors: true, side: THREE.DoubleSide })));

    // Tolerable touch voltage: what rises above this plane does not comply.
    if (mode === "touch" && tolerable) {
      const { x0, x1, y0, y1 } = data.extent;
      const plane = new THREE.Mesh(new THREE.PlaneGeometry(x1 - x0, y1 - y0),
        new THREE.MeshBasicMaterial({ color: 0x23735f, transparent: true, opacity: 0.22, side: THREE.DoubleSide, depthWrite: false }));
      plane.rotation.x = -Math.PI / 2;
      plane.position.set((x0 + x1) / 2, tolerable * heightScale, -(y0 + y1) / 2);
      scene.add(plane);
    }

    // Buried grid and rods, depth exaggerated so they stay readable under the surface.
    const depthScale = Math.max(1, (0.04 * size) / (plan.burialDepth || 0.5));
    const lineMaterial = new THREE.LineBasicMaterial({ color: 0x8a5a12 });
    const segments = [];
    const halfX = plan.length / 2, halfY = plan.width / 2, z0 = -plan.burialDepth * depthScale;
    plan.lines.forEach(([[x1, y1], [x2, y2]]) => segments.push(x1 - halfX, z0, -(y1 - halfY), x2 - halfX, z0, -(y2 - halfY)));
    plan.rods.forEach(([x, y]) => segments.push(x - halfX, z0, -(y - halfY), x - halfX, z0 - plan.rodLength * depthScale, -(y - halfY)));
    const gridGeometry = new THREE.BufferGeometry();
    gridGeometry.setAttribute("position", new THREE.Float32BufferAttribute(segments, 3));
    scene.add(new THREE.LineSegments(gridGeometry, lineMaterial));

    // Worst touch point and worst step.
    const marker = (x, y, h, hex) => {
      const sphere = new THREE.Mesh(new THREE.SphereGeometry(size / 120, 16, 12), new THREE.MeshBasicMaterial({ color: hex }));
      sphere.position.set(x, h, -y);
      scene.add(sphere);
    };
    if (result.max_touch_v?.x_m !== undefined) {
      marker(result.max_touch_v.x_m, result.max_touch_v.y_m, (mode === "touch" ? result.max_touch_v.value : gpr - result.max_touch_v.value - base) * heightScale, 0xc0392b);
    }
    if (result.max_step_v?.from_m && result.max_step_v?.to_m) {
      const [a, b] = [result.max_step_v.from_m, result.max_step_v.to_m];
      const stepGeometry = new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(a[0], 0.02 * size, -a[1]), new THREE.Vector3(b[0], 0.02 * size, -b[1])]);
      scene.add(new THREE.Line(stepGeometry, new THREE.LineBasicMaterial({ color: 0x6c3483 })));
      marker(a[0], a[1], 0.02 * size, 0x6c3483);
    }

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.target.set(0, (top * heightScale) / 4, 0);
    controls.update();
    // Render on demand: no animation loop, only when the camera or the size changes.
    const render = () => renderer.render(scene, camera);
    controls.addEventListener("change", render);
    const resize = new ResizeObserver(() => {
      camera.aspect = node.clientWidth / node.clientHeight;
      camera.updateProjectionMatrix();
      renderer.setSize(node.clientWidth, node.clientHeight);
      render();
    });
    resize.observe(node);
    render();
    return () => {
      resize.disconnect();
      controls.dispose();
      scene.traverse((object) => { object.geometry?.dispose(); object.material?.dispose?.(); });
      renderer.dispose();
      node.removeChild(renderer.domElement);
    };
  }, [data, exaggeration, field, gpr, mode, plan, result, tolerable]);

  const label = mode === "touch" ? "Tensión de contacto (GPR − U)" : "Potencial superficial U (altura desde el mínimo)";
  return <div className="surface3d-backdrop" role="dialog" aria-modal="true" aria-label="Vista 3D del cálculo">
    <div className="surface3d-panel">
      <div className="surface3d-toolbar">
        <strong>Vista 3D · versión {calculation.artifact_version}</strong>
        <div className="surface3d-toggle" role="group" aria-label="Magnitud">
          <button className={mode === "touch" ? "active" : ""} onClick={() => setMode("touch")}>Contacto</button>
          <button className={mode === "potential" ? "active" : ""} onClick={() => setMode("potential")}>Potencial</button>
        </div>
        <label>Resolución<select value={resolution} onChange={(e) => setResolution(e.target.value)}>{Object.keys(RESOLUTIONS).map((key) => <option key={key} value={key}>{key}</option>)}</select></label>
        <label>Altura<input type="range" min="0.3" max="3" step="0.1" value={exaggeration} onChange={(e) => setExaggeration(Number(e.target.value))}/></label>
        <button className="icon-button" aria-label="Cerrar vista 3D" onClick={onClose}><X size={16}/></button>
      </div>
      <div className="surface3d-canvas" ref={mount}/>
      <div className="surface3d-legend">
        <span>{label}: {fmt(data.min)} – {fmt(data.max)} V</span>
        <i/>
        {mode === "touch" && tolerable && <span className="surface3d-plane">Plano verde: tolerable {fmt(tolerable)} V (lo que sobresale no cumple)</span>}
        <span className="surface3d-touch">● peor contacto {fmt(result.max_touch_v?.value)} V</span>
        <span className="surface3d-step">— peor paso {fmt(result.max_step_v?.value)} V</span>
        <span>Malla enterrada en café (profundidad exagerada) · rejilla {field.nx} × {field.ny}{data.step > 1 ? `, se muestra 1 de cada ${data.step}` : ""} · arrastra para rotar, rueda para acercar</span>
        {mode === "touch" && <span>Se muestra el área de la malla, donde se evalúa el contacto; «Potencial» incluye el margen exterior.</span>}
      </div>
    </div>
  </div>;
}
