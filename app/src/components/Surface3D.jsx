import React, { useEffect, useMemo, useRef, useState } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { X } from "lucide-react";
import { InfoTip } from "./ResultBlocks.jsx";
import { Icon3D, IconPrint } from "../icons.jsx";

// Vertex budget per resolution: the raster is decimated so the surface never exceeds it.
const RESOLUTIONS = { baja: 2500, media: 10000, completa: 40000 };
const RESOLUTION_LABELS = { baja: "Baja", media: "Media", completa: "Completa" };
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
export default function Surface3D({ calculation, plan, onClose, embedded = false, initialMode = "touch", title: fixedTitle = null }) {
  const mount = useRef(null);
  useEffect(() => {
    if (embedded) return undefined;
    const onKey = (event) => { if (event.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  const [mode, setMode] = useState(initialMode);
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
    // Frame the area actually drawn (in «contacto», only the grid), not the whole raster.
    const { x0: ex0, x1: ex1, y0: ey0, y1: ey1 } = data.extent;
    const size = Math.max(ex1 - ex0, ey1 - ey0) || 1;
    const cx = (ex0 + ex1) / 2, cz = -(ey0 + ey1) / 2;
    // Potential is drawn relative to its minimum so the surface rests on the ground above the grid.
    const base = mode === "touch" ? 0 : data.min;
    const top = mode === "touch" ? Math.max(data.max, tolerable || 0) : data.max - base;
    const heightScale = (0.35 * size * exaggeration) / (top || 1);
    const scene = new THREE.Scene();
    scene.background = new THREE.Color("#f6f9f8");
    const camera = new THREE.PerspectiveCamera(45, node.clientWidth / node.clientHeight, size / 100, size * 20);
    camera.position.set(cx + size * 0.9, size * 0.75, cz + size * 1.05);
    // preserveDrawingBuffer keeps the last frame readable for «Imprimir».
    const renderer = new THREE.WebGLRenderer({ antialias: true, preserveDrawingBuffer: true });
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
    // Plan coordinates → solver coordinates: the grid's corner in the plan sits where the raster says the grid starts.
    // (Centering on the site was only right when the grid filled the whole site.)
    const planXs = plan.lines.flatMap(([a, b]) => [a[0], b[0]]), planYs = plan.lines.flatMap(([a, b]) => [a[1], b[1]]);
    const offX = field.grid_width_m && planXs.length ? field.x_min_m + (field.grid_x_m || 0) - Math.min(...planXs) : -plan.length / 2;
    const offY = field.grid_height_m && planYs.length ? field.y_min_m + (field.grid_y_m || 0) - Math.min(...planYs) : -plan.width / 2;
    const z0 = -plan.burialDepth * depthScale;
    plan.lines.forEach(([[x1, y1], [x2, y2]]) => segments.push(x1 + offX, z0, -(y1 + offY), x2 + offX, z0, -(y2 + offY)));
    plan.rods.forEach(([x, y]) => segments.push(x + offX, z0, -(y + offY), x + offX, z0 - plan.rodLength * depthScale, -(y + offY)));
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
    controls.target.set(cx, (top * heightScale) / 4, cz);
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

  const touchMode = mode === "touch";
  const title = touchMode ? "Tensión de contacto sobre la malla" : "Potencial en la superficie del terreno";
  const subtitle = touchMode
    ? "Diferencia entre la malla y el suelo: lo que sentiría una persona que toca una estructura conectada durante la falla."
    : "Tensión del suelo respecto a tierra remota durante la falla, incluido el margen exterior a la malla.";
  const span = data.max - data.min || 1;
  const tolerableShare = touchMode && tolerable && tolerable >= data.min && tolerable <= data.max ? (tolerable - data.min) / span : null;
  const tolerableOutside = touchMode && tolerable && tolerableShare === null ? (tolerable < data.min ? "below" : "above") : null;
  const ticks = [1, 0.75, 0.5, 0.25, 0].map((t) => ({ t, value: data.min + t * span }));
  function print() {
    const canvas = mount.current?.querySelector("canvas");
    if (!canvas) return;
    const image = canvas.toDataURL("image/png");
    const sheet = window.open("", "_blank", "width=1100,height=800");
    if (!sheet) return;
    const rows = [
      [touchMode ? "Rango de tensión de contacto" : "Rango de potencial", `${fmt(data.min)} – ${fmt(data.max)} V`],
      ...(touchMode && tolerable ? [["Tensión de contacto tolerable (plano verde)", `${fmt(tolerable)} V`]] : []),
      ["Peor tensión de contacto", `${fmt(result.max_touch_v?.value)} V`],
      ["Peor tensión de paso", `${fmt(result.max_step_v?.value)} V`],
      ["Rejilla de cálculo", `${field.nx} × ${field.ny} puntos cada ${fmt(field.spacing_m, 2)} m`],
    ];
    const escape = (text) => String(text).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
    sheet.document.write(`<!doctype html><html lang="es"><head><meta charset="utf-8"><title>${escape(title)} · versión ${calculation.artifact_version}</title><style>body{font-family:"DM Sans",system-ui,sans-serif;color:#273443;margin:28px}h1{font-size:20px;margin:0 0 4px}p{color:#5f6f68;margin:0 0 16px;font-size:12px}img{width:100%;border:1px solid #dce5e0;border-radius:8px}table{border-collapse:collapse;margin-top:16px;font-size:12px;width:100%}td{padding:6px 8px;border-bottom:1px solid #e5ebe8}td:first-child{color:#5f6f68}small{display:block;margin-top:16px;color:#8a9690;font-size:10px}</style></head><body><h1>${escape(title)}</h1><p>Versión ${calculation.artifact_version} del diseño · ${escape(subtitle)}</p><img src="${image}" alt="${escape(title)}"><table>${rows.map(([a, b]) => `<tr><td>${escape(a)}</td><td><strong>${escape(b)}</strong></td></tr>`).join("")}</table><small>Escala de color del azul (menor) al rojo (mayor). Verificación de prefactibilidad; requiere revisión de un ingeniero competente.</small></body></html>`);
    sheet.document.close();
    // The image must decode before printing; whichever fires first prints, once.
    let printed = false;
    const go = () => { if (printed || sheet.closed) return; printed = true; sheet.focus(); sheet.print(); };
    sheet.addEventListener("load", go);
    setTimeout(go, 700);
  }
  const stage = <>
        <div className="surface3d-stage">
          <div className="surface3d-canvas" ref={mount}/>
          <div className="surface3d-colorbar" aria-label={`Escala de color de ${fmt(data.min)} a ${fmt(data.max)} V`}>
            <strong>{touchMode ? "Contacto" : "Potencial"} (V)</strong>
            <div className="surface3d-colorbar-scale">
              <i/>
              <ol>{ticks.map(({ t, value }) => <li key={t} style={{ bottom: `${t * 100}%` }}>{fmt(value, 0)}</li>)}</ol>
              {tolerableShare !== null && <span className="surface3d-colorbar-limit" style={{ bottom: `${tolerableShare * 100}%` }}>Tolerable {fmt(tolerable, 0)}</span>}
            </div>
            {tolerableOutside && <small className="surface3d-colorbar-out">Tolerable {fmt(tolerable, 0)} V<br/>{tolerableOutside === "below" ? "toda la superficie lo supera" : "ningún punto lo alcanza"}</small>}
          </div>
          <p className="surface3d-hint">Arrastra para rotar · rueda para acercar · clic derecho para desplazar</p>
        </div>
  </>;
  // In a published report: the same view inline, without the dialog and its controls.
  if (embedded) return <figure className="surface3d-embed">
    <div className="surface3d-embed-stage">{stage}</div>
    <figcaption><strong>{fixedTitle || title}</strong><span>{subtitle} Peor contacto: {fmt(result.max_touch_v?.value)} V · peor paso: {fmt(result.max_step_v?.value)} V{touchMode && tolerable ? ` · tolerable: ${fmt(tolerable)} V (plano verde)` : ""}.</span></figcaption>
  </figure>;
  return <div className="surface3d-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <section className="surface3d-panel" role="dialog" aria-modal="true" aria-labelledby="surface3d-title">
      <header className="surface3d-header">
        <div className="surface3d-title"><span className="app-dialog-icon"><Icon3D size={18}/></span><div><div className="eyebrow">VISTA 3D · VERSIÓN {calculation.artifact_version}</div><h2 id="surface3d-title">{title}</h2></div></div>
        <div className="surface3d-actions">
          <button type="button" className="button" onClick={print}><IconPrint size={15}/> Imprimir</button>
          <button type="button" className="icon-button" aria-label="Cerrar vista 3D" onClick={onClose}><X size={17}/></button>
        </div>
      </header>
      <div className="surface3d-body">
        {stage}
        <aside className="surface3d-side">
          <section>
            <h3>Qué muestra</h3>
            <p>{subtitle}</p>
            <div className="app-segmented" role="group" aria-label="Magnitud">
              <button type="button" className={touchMode ? "active" : ""} aria-pressed={touchMode} onClick={() => setMode("touch")}>Tensión de contacto</button>
              <button type="button" className={!touchMode ? "active" : ""} aria-pressed={!touchMode} onClick={() => setMode("potential")}>Potencial</button>
            </div>
          </section>
          <section>
            <h3>Puntos críticos</h3>
            <dl className="surface3d-facts">
              <div className="touch"><dt><i/>Peor tensión de contacto <InfoTip text="El punto sobre la malla donde la diferencia entre la estructura y el suelo es mayor. Se marca con una esfera roja."/></dt><dd>{fmt(result.max_touch_v?.value)} V<small>Esfera roja en la vista</small></dd></div>
              <div className="step"><dt><i/>Peor tensión de paso <InfoTip text="Los dos puntos del suelo, separados 1 m, con la mayor diferencia de potencial. Se marcan con una línea morada."/></dt><dd>{fmt(result.max_step_v?.value)} V<small>Línea morada en la vista</small></dd></div>
              {touchMode && tolerable && <div className="plane"><dt><i/>Plano verde · tolerable <InfoTip text="La tensión de contacto que el cuerpo soporta según IEEE 80. Lo que sobresale por encima del plano no cumple."/></dt><dd>{fmt(tolerable)} V{data.max > tolerable && <small>La superficie lo supera: hay zonas que no cumplen.</small>}</dd></div>}
            </dl>
          </section>
          <section>
            <h3>Escala</h3>
            <p>Color y altura representan la misma magnitud: del azul ({fmt(data.min)} V) al rojo ({fmt(data.max)} V).{!touchMode && " En «Potencial» la altura se mide desde el valor mínimo."}</p>
            <label className="surface3d-range"><span>Exageración de la altura <InfoTip text="Solo cambia el dibujo para ver mejor el relieve; no modifica los valores."/></span><input type="range" min="0.3" max="3" step="0.1" value={exaggeration} onChange={(e) => setExaggeration(Number(e.target.value))} aria-valuetext={`${fmt(exaggeration)} veces`}/><output>× {fmt(exaggeration)}</output></label>
          </section>
          <section>
            <h3>Resolución <InfoTip text="Cuántos puntos del cálculo se dibujan. «Baja» es más fluida en equipos lentos; los valores calculados no cambian."/></h3>
            <div className="app-segmented" role="group" aria-label="Resolución">
              {Object.keys(RESOLUTIONS).map((key) => <button type="button" key={key} className={resolution === key ? "active" : ""} aria-pressed={resolution === key} onClick={() => setResolution(key)}>{RESOLUTION_LABELS[key]}</button>)}
            </div>
            <p className="surface3d-note">Rejilla de {field.nx} × {field.ny} puntos cada {fmt(field.spacing_m, 2)} m{data.step > 1 ? `; se dibuja 1 de cada ${data.step}` : ""}.</p>
          </section>
          <section>
            <h3>La malla enterrada</h3>
            <p>Las líneas café bajo la superficie son los conductores y las varillas. La profundidad está exagerada para que se vean.{touchMode && " En «Tensión de contacto» solo se dibuja el área de la malla, donde se evalúa."}</p>
          </section>
        </aside>
      </div>
    </section>
  </div>;
}
