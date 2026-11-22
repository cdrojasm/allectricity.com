import React, { useEffect, useMemo, useRef, useState } from "react";
import { AlertTriangle, Cable, CircleDot, Download, Maximize2, Minus, Plus, Square, Undo2, Redo2, X, Image, Upload, SlidersHorizontal } from "lucide-react";
import TopologyOptimizerPanel from "./TopologyOptimizerPanel.jsx";
import { awaitJob } from "../asyncJobs.js";

const VIEW = { x: 70, y: 55, width: 860, height: 530 };
const emptyPlan = { length: 40, width: 30, spacing: 5, items: [], areas: [], background: null };
const LAYERS = [
  { id: "intervenible", label: "Áreas intervenibles", swatch: "area" },
  { id: "blocked", label: "No intervenible", swatch: "obstacle" },
  { id: "conductors", label: "Conductores", swatch: "conductor" },
  { id: "electrodes", label: "Electrodos", swatch: "electrode" },
];
const areaPoints = (area) => area.polygon || [
  { x: area.x_min, y: area.y_min }, { x: area.x_max, y: area.y_min },
  { x: area.x_max, y: area.y_max }, { x: area.x_min, y: area.y_max },
];
const areaBounds = (area) => {
  const points = areaPoints(area);
  return { x_min: Math.min(...points.map((p) => p.x)), x_max: Math.max(...points.map((p) => p.x)),
    y_min: Math.min(...points.map((p) => p.y)), y_max: Math.max(...points.map((p) => p.y)) };
};
const DEFAULT_SNAP_M = 0.5;
// Spanish text for the structured conflicts of /geometria/validar (grid_geometry.geometry_conflicts).
function conflictText(conflict) {
  const obstacle = conflict.obstacle ? (conflict.obstacle.label ? `«${conflict.obstacle.label}»` : conflict.obstacle.kind === "area" ? "una zona no intervenible" : "un elemento constructivo") : "";
  const element = { conductor: "El conductor", rod: "El electrodo", structure: "El elemento constructivo", area: "La zona" }[conflict.element] || "La geometría";
  switch (conflict.kind) {
    case "crosses_obstacle": return `${element} atraviesa ${obstacle}, que no es intervenible.`;
    case "inside_obstacle": return `${element} está dentro de ${obstacle}, que no es intervenible.`;
    case "outside_areas": return `${element} queda fuera de las áreas intervenibles.`;
    case "outside_site": return `${element} sale del terreno.`;
    case "regular_grid_over_areas": return "La retícula regular cubre todo el terreno: genera la malla en un área intervenible.";
    case "not_on_conductor": return `${element} no toca ningún conductor.`;
    case "overlap": return `${element} se superpone con otro conductor.`;
    case "duplicate": return `${element} está en el mismo punto que otro electrodo.`;
    case "zero_length": return `${element} tiene longitud cero.`;
    case "bounds": return `${element} necesita mínimos menores que los máximos.`;
    default: return conflict.message;
  }
}

function GroundingPlanDrawer({ projectId, projectName, conversation, token, focusOptimizer = 0, onShowResults }) {
  const [plan, setPlan] = useState(emptyPlan);
  const [artifact, setArtifact] = useState(null);
  const [hydrated, setHydrated] = useState(false);
  const [opened, setOpened] = useState(false);
  const [sourceFiles, setSourceFiles] = useState([]);
  const [backgroundScale, setBackgroundScale] = useState("0.05");
  const [backgroundUrl, setBackgroundUrl] = useState("");
  const [backgroundFile, setBackgroundFile] = useState("");
  const [backgroundPage, setBackgroundPage] = useState("1");
  const [backgroundSize, setBackgroundSize] = useState(null);
  const [calibrationMode, setCalibrationMode] = useState(false);
  const [calibrationPoints, setCalibrationPoints] = useState([]);
  const [calibrationDistance, setCalibrationDistance] = useState("10");
  const [dxfFile, setDxfFile] = useState("");
  const [visionProposal, setVisionProposal] = useState(null);
  const [visionBusy, setVisionBusy] = useState(false);
  const [saveState, setSaveState] = useState("saved");
  const [planCheck, setPlanCheck] = useState({ conflicts: [], warnings: [] });
  const artifactRef = useRef(null);
  const optimizerPanelRef = useRef(null);
  const dirtyRef = useRef(false);
  const planRef = useRef(plan);
  const snapshotRef = useRef(null);
  const saveTimerRef = useRef(null);
  useEffect(() => {
    if (focusOptimizer) setOpened(true);
  }, [focusOptimizer]);
  useEffect(() => {
    if (!focusOptimizer || !opened || !optimizerPanelRef.current) return undefined;
    optimizerPanelRef.current.open = true;
    const frame = requestAnimationFrame(() => {
      optimizerPanelRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
      optimizerPanelRef.current?.querySelector("summary")?.focus({ preventScroll: true });
    });
    return () => cancelAnimationFrame(frame);
  }, [focusOptimizer, opened]);
  useEffect(() => {
    if (!conversation) return;
    let live = true;
    (async () => {
      try {
        const headers = { Authorization: `Bearer ${token}` };
        fetch(`/api/v1/projects/${projectId}/files`, { headers }).then((response) => response.ok ? response.json() : []).then(setSourceFiles).catch(() => {});
        const [stateResponse, artifactsResponse] = await Promise.all([
          fetch(`/api/v1/conversations/${conversation.id}/agent-state`, { headers }),
          fetch(`/api/v1/projects/${projectId}/artefactos-diseno-tierras`, { headers }),
        ]);
        if (!stateResponse.ok || !artifactsResponse.ok) return;
        const [state, artifacts] = await Promise.all([stateResponse.json(), artifactsResponse.json()]);
        const artifact = artifacts.find((row) => row.artifact_id === state.artifact_id) || (artifacts.length === 1 ? artifacts[0] : null);
        const geometry = artifact?.snapshot?.geometry;
        if (!live) return;
        artifactRef.current = artifact || null;
        snapshotRef.current = artifact?.snapshot || null;
        setArtifact(artifact || null);
        if (!geometry) { setHydrated(true); return; }
        const sx = geometry.conductor_spacing_x_m || geometry.conductor_spacing_m || 5;
        const sy = geometry.conductor_spacing_y_m || geometry.conductor_spacing_m || sx;
        // The artifact renderer also draws a regular grid when conductors are implicit.
        // Materialize that same geometry here so the editor can select and edit it.
        const conductors = geometry.conductors?.length ? geometry.conductors : [
          ...axisPositions(geometry.width_m || emptyPlan.width, sy).map((y) => ({ start: { x: 0, y }, end: { x: geometry.length_m || emptyPlan.length, y } })),
          ...axisPositions(geometry.length_m || emptyPlan.length, sx).map((x) => ({ start: { x, y: 0 }, end: { x, y: geometry.width_m || emptyPlan.width } })),
        ];
        const rods = geometry.rods?.length ? geometry.rods : perimeterRods(geometry.rods_count || 0, geometry.length_m || emptyPlan.length, geometry.width_m || emptyPlan.width).map(([x, y]) => ({ x, y }));
        const items = [
          ...conductors.map((line) => ({ id: crypto.randomUUID(), type: "conductor", from: { x: line.start.x, y: line.start.y }, to: { x: line.end.x, y: line.end.y } })),
          ...rods.map((rod) => ({ id: crypto.randomUUID(), type: "electrode", x: rod.x, y: rod.y, ...(rod.length_m ? { length_m: rod.length_m } : {}) })),
          ...(geometry.structures || []).map((item) => ({ id: crypto.randomUUID(), type: "structure", x: item.x, y: item.y, width: item.width, height: item.height, label: item.label || "" })),
        ];
        const next = { length: geometry.length_m || emptyPlan.length, width: geometry.width_m || emptyPlan.width, spacing: sx, items,
          areas: (geometry.areas || []).map((area) => ({ type: area.type, label: area.label || "", polygon: areaPoints(area) })),
          snap: geometry.snap_m || null, background: geometry.background || null };
        setPlan(next);
        planRef.current = next;
        setHydrated(true);
        window.dispatchEvent(new CustomEvent("grounding-plan-updated", { detail: { projectId, plan: next } }));
        if (geometry.background?.upload_id) {
          (async () => {
            const fileResponse = await fetch(`/api/v1/files/${geometry.background.upload_id}/download`, { headers });
            if (!fileResponse.ok || !live) return;
            const file = await fileResponse.json();
            let url = file.url;
            if (file.mime_type === "application/pdf") {
              const page = Math.max(1, Number(geometry.background.source_page) || 1);
              const previewResponse = await fetch(`/api/v1/files/${geometry.background.upload_id}/preview?page=${page}&dpi=144`, { headers });
              if (!previewResponse.ok || !live) return;
              url = URL.createObjectURL(await previewResponse.blob());
            }
            if (!live) return;
            setBackgroundUrl(url);
            setBackgroundSize({ width: geometry.background.width_px, height: geometry.background.height_px });
          })().catch(() => {});
        }
      } catch { /* Keep the editable default if the artifact is unavailable. */ }
    })();
    return () => { live = false; };
  }, [conversation?.id, projectId, token]);
  const [tool, setTool] = useState("select");
  const [anchor, setAnchor] = useState(null);
  const [zoom, setZoom] = useState(1);
  const [selectedId, setSelectedId] = useState(null);
  const [selectedIds, setSelectedIds] = useState([]);
  const [propertiesOpen, setPropertiesOpen] = useState(false);
  const [message, setMessage] = useState("");
  const [contextMenu, setContextMenu] = useState(null);
  const [contextAddOpen, setContextAddOpen] = useState(false);
  const [selectionRect, setSelectionRect] = useState(null);
  const [obstacleWidth, setObstacleWidth] = useState(emptyPlan.spacing);
  const [obstacleHeight, setObstacleHeight] = useState(emptyPlan.spacing);
  const [layers, setLayers] = useState({ intervenible: true, blocked: true, conductors: true, electrodes: true });
  const toggleLayer = (id) => setLayers((current) => ({ ...current, [id]: !current[id] }));
  const canvasRef = useRef(null);
  const gestureRef = useRef(null);
  const selectionRef = useRef(null);
  const [history, setHistory] = useState({ past: [], future: [] });
  const keyX = useMemo(() => makeGrid(plan.length, plan.spacing), [plan.length, plan.spacing]);
  const keyY = useMemo(() => makeGrid(plan.width, plan.spacing), [plan.width, plan.spacing]);
  const selectedItem = plan.items.find((item) => item.id === selectedId) || null;
  const unitsPerPixel = Math.min(VIEW.width / plan.length, VIEW.height / plan.width);
  const drawing = { x: VIEW.x + (VIEW.width - plan.length * unitsPerPixel) / 2, y: VIEW.y + (VIEW.height - plan.width * unitsPerPixel) / 2, width: plan.length * unitsPerPixel, height: plan.width * unitsPerPixel };
  const toCanvas = (x, y) => ({ x: drawing.x + x * unitsPerPixel, y: drawing.y + y * unitsPerPixel });
  const toWorld = (event) => {
    const svg = canvasRef.current;
    if (!svg) return { x: 0, y: 0 };
    const point = svg.createSVGPoint(); point.x = event.clientX; point.y = event.clientY;
    const local = point.matrixTransform(svg.getScreenCTM().inverse());
    return { x: Math.max(0, Math.min(plan.length, (local.x - drawing.x) / unitsPerPixel)), y: Math.max(0, Math.min(plan.width, (local.y - drawing.y) / unitsPerPixel)) };
  };
  const toUnboundedWorld = (event) => {
    const svg = canvasRef.current;
    if (!svg) return { x: 0, y: 0 };
    const point = svg.createSVGPoint(); point.x = event.clientX; point.y = event.clientY;
    const local = point.matrixTransform(svg.getScreenCTM().inverse());
    return { x: (local.x - drawing.x) / unitsPerPixel, y: (local.y - drawing.y) / unitsPerPixel };
  };
  const nearest = (values, value) => values.reduce((best, candidate) => Math.abs(candidate - value) < Math.abs(best - value) ? candidate : best, values[0]);
  const blockers = plan.items.filter((item) => item.type === "structure");
  const electrodes = plan.items.filter((item) => item.type === "electrode");
  const drawnConductors = plan.items.filter((item) => item.type === "conductor");
  const cellFor = (point) => ({ col: cellIndex(keyX, point.x), row: cellIndex(keyY, point.y) });
  const step = plan.snap || DEFAULT_SNAP_M;
  // Editor-only rules; collisions with structures and zones come from the backend (one source of truth).
  const issues = [];
  for (let i = 0; i < blockers.length; i++) for (let j = i + 1; j < blockers.length; j++) if (rectsOverlap(worldRect(blockers[i]), worldRect(blockers[j]))) issues.push({ id: blockers[j].id, text: "El elemento constructivo se superpone con otro." });
  for (const electrode of electrodes) {
    const cell = cellFor(electrode);
    if (electrodes.some((other) => other.id !== electrode.id && cellFor(other).col === cell.col && cellFor(other).row === cell.row)) issues.push({ id: electrode.id, text: "Ya existe un electrodo en esta celda de la retícula." });
  }
  const elementIds = { conductor: drawnConductors.map((item) => item.id), rod: electrodes.map((item) => item.id), structure: blockers.map((item) => item.id) };
  for (const conflict of planCheck.conflicts) issues.push({ id: conflict.element === "area" ? `area-${conflict.index}` : elementIds[conflict.element]?.[conflict.index] || "grid", text: conflictText(conflict) });
  const warnings = planCheck.warnings.map((warning) => warning.kind === "disconnected" ? `La malla tiene ${warning.parts} partes separadas: el cálculo las trata como un solo conductor, lo que solo es cierto si un conductor de unión las conecta.` : warning.message);

  function geometryFromPlan(value) {
    return {
      length_m: Number(value.length), width_m: Number(value.width), burial_depth_m: snapshotRef.current?.geometry?.burial_depth_m || 0.5,
      conductor_spacing_m: Number(value.spacing),
      conductors: value.items.filter((item) => item.type === "conductor").map((item) => ({ start: item.from, end: item.to })),
      rods_count: value.items.filter((item) => item.type === "electrode").length,
      rod_length_m: snapshotRef.current?.geometry?.rod_length_m || 2.4,
      // A rod keeps its own length (the optimizer sizes each one); a new rod uses the common rod_length_m.
      rods: value.items.filter((item) => item.type === "electrode").map((item) => ({ x: item.x, y: item.y, ...(item.length_m ? { length_m: item.length_m } : {}) })),
      structures: value.items.filter((item) => item.type === "structure").map((item) => ({ x: item.x, y: item.y, width: item.width, height: item.height, label: item.label || null })),
      areas: value.areas || [],
      snap_m: value.snap || null,
      background: value.background || null
    };
  }
  async function prepareBackground() {
    const file = sourceFiles.find((item) => item.upload_id === backgroundFile && item.status === "available");
    if (!file) return setMessage("Selecciona una imagen disponible en Fuentes.");
    const headers = { Authorization: `Bearer ${token}` };
    let previewUrl;
    let sourcePage = null;
    if (file.mime_type === "application/pdf") {
      sourcePage = Math.max(1, Number(backgroundPage) || 1);
      const response = await fetch(`/api/v1/files/${file.upload_id}/preview?page=${sourcePage}&dpi=144`, { headers });
      if (!response.ok) return setMessage("No se pudo rasterizar esa página del PDF.");
      previewUrl = URL.createObjectURL(await response.blob());
    } else {
      const download = await fetch(`/api/v1/files/${file.upload_id}/download`, { headers }).then((response) => response.ok ? response.json() : null);
      if (!download) return setMessage("No se pudo abrir la imagen de fondo.");
      previewUrl = download.url;
    }
    const image = new window.Image();
    image.onload = () => { setBackgroundUrl(previewUrl); setBackgroundSize({ width: image.naturalWidth, height: image.naturalHeight }); setCalibrationPoints([]); setCalibrationMode(true); setMessage("Marca los dos extremos de una distancia conocida sobre la imagen."); };
    image.onerror = () => setMessage("La imagen de fondo no se pudo cargar.");
    image.src = previewUrl;
  }
  function captureCalibration(event) {
    if (!calibrationMode || !backgroundSize) return false;
    event.stopPropagation();
    const point = toWorld(event);
    setCalibrationPoints((current) => {
      const next = current.length >= 2 ? [point] : [...current, point];
      if (next.length === 2) setMessage("Introduce la distancia real y guarda la calibración.");
      return next;
    });
    return true;
  }
  async function attachBackground() {
    const headers = { Authorization: `Bearer ${token}` };
    const file = sourceFiles.find((item) => item.upload_id === backgroundFile && item.status === "available");
    if (!file || !artifactRef.current || calibrationPoints.length !== 2 || !backgroundSize) return setMessage("Marca dos puntos y escribe una distancia real antes de guardar.");
    const pixelDistance = Math.hypot((calibrationPoints[1].x - calibrationPoints[0].x) / plan.length * backgroundSize.width, (calibrationPoints[1].y - calibrationPoints[0].y) / plan.width * backgroundSize.height);
    const distance = Number(calibrationDistance);
    const scale = distance > 0 && pixelDistance > 0 ? distance / pixelDistance : 0;
    if (!scale) return setMessage("La distancia real debe ser positiva.");
    setBackgroundScale(scale.toFixed(6));
    const response = await fetch(`/api/v1/projects/${projectId}/artefactos-diseno-tierras/${artifactRef.current.artifact_id}/versions/${artifactRef.current.version}/background`, { method: "POST", headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" }, body: JSON.stringify({ upload_id: file.upload_id, source_page: file.mime_type === "application/pdf" ? Math.max(1, Number(backgroundPage) || 1) : null, width_px: backgroundSize.width, height_px: backgroundSize.height, scale_m_per_pixel: scale, calibration_points: calibrationPoints, calibration_distance_m: distance, pixel_distance: pixelDistance }) });
    if (!response.ok) return setMessage("No se pudo calibrar el plano de fondo.");
    const saved = await response.json();
    artifactRef.current = saved; snapshotRef.current = saved.snapshot; setArtifact(saved); setPlan((current) => ({ ...current, background: saved.snapshot.geometry.background }));
    setCalibrationMode(false); setCalibrationPoints([]);
  }
  async function importDxf() {
    const file = sourceFiles.find((item) => item.upload_id === dxfFile && item.status === "available");
    if (!file || !artifactRef.current) return setMessage("Selecciona un DXF analizado y un diseño guardado.");
    const response = await fetch(`/api/v1/projects/${projectId}/artefactos-diseno-tierras/${artifactRef.current.artifact_id}/import-dxf`, { method: "POST", headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" }, body: JSON.stringify({ upload_id: file.upload_id }) });
    const proposal = await response.json().catch(() => ({}));
    if (!response.ok) return setMessage(proposal.detail || "No se pudo leer el DXF.");
    const geometry = proposal.geometry;
    const items = [...(geometry.conductors || []).map((line) => ({ id: crypto.randomUUID(), type: "conductor", from: line.start, to: line.end })), ...(geometry.rods || []).map((rod) => ({ id: crypto.randomUUID(), type: "electrode", x: rod.x, y: rod.y }))];
    persist({ ...plan, length: geometry.length_m, width: geometry.width_m, items });
    setMessage(`DXF leído: ${items.length} elementos propuestos. Revisa y confirma el guardado.`);
  }
  async function proposePlanVision() {
    const file = sourceFiles.find((item) => item.upload_id === backgroundFile && item.status === "available");
    if (!file || !artifactRef.current) return setMessage("Selecciona un plano disponible y un diseño guardado.");
    if (!["application/pdf", "image/png", "image/jpeg"].includes(file.mime_type)) return setMessage("La lectura visual requiere un PDF, PNG o JPEG.");
    setVisionBusy(true);
    try {
      const sourcePage = file.mime_type === "application/pdf" ? Math.max(1, Number(backgroundPage) || 1) : null;
      const response = await fetch(`/api/v1/projects/${projectId}/artefactos-diseno-tierras/${artifactRef.current.artifact_id}/versions/${artifactRef.current.version}/plan-revision`, { method: "POST", headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" }, body: JSON.stringify({ upload_id: file.upload_id, source_page: sourcePage }) });
      const accepted = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(accepted.detail || "No se pudo analizar el plano.");
      const proposal = await awaitJob(token, accepted);
      setVisionProposal({ ...proposal.proposal, ...proposal, structures: proposal.proposal?.structures || [] });
      setMessage("Revisión comparada y alerta publicada en el chat. Revisa y confirma los obstáculos antes de incorporarlos.");
    } catch (error) {
      setMessage(error.message);
    } finally {
      setVisionBusy(false);
    }
  }
  function acceptVisionProposal() {
    if (!visionProposal?.structures?.length) return setMessage("La propuesta no contiene obstáculos aplicables.");
    const items = visionProposal.structures.map((item) => ({ id: crypto.randomUUID(), type: "structure", x: item.x, y: item.y, width: item.width, height: item.height, label: item.label || "Elemento constructivo" }));
    persist({ ...plan, items: [...plan.items, ...items] });
    setVisionProposal(null);
    setLayers((current) => ({ ...current, blocked: true }));
    setMessage(`${items.length} obstáculos incorporados como propuesta editable. Revisa y guarda la versión.`);
  }
  function persist(next) {
    planRef.current = next;
    setPlan(next);
    dirtyRef.current = true;
    setSaveState("pending");
    window.dispatchEvent(new CustomEvent("grounding-plan-updated", { detail: { projectId, plan: next } }));
  }
  useEffect(() => {
    if (!hydrated || !dirtyRef.current) return undefined;
    clearTimeout(saveTimerRef.current);
    saveTimerRef.current = setTimeout(async () => {
      const current = planRef.current;
      const base = snapshotRef.current || { schema_version: "1.0", soil_layers: [], fault: {}, conductor: {}, compliance: [] };
      const payload = { ...base, name: base.name || `${projectName} · Plano`, geometry: geometryFromPlan(current) };
      const root = `/api/v1/projects/${projectId}/artefactos-diseno-tierras`;
      const url = artifactRef.current ? `${root}/${artifactRef.current.artifact_id}` : root;
      try {
        const response = await fetch(url, { method: artifactRef.current ? "PUT" : "POST", headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" }, body: JSON.stringify(payload) });
        if (response.status === 422) throw new Error("el plano tiene conflictos; corrígelos (ver «Reglas del plano») y se guardará automáticamente.");
        if (!response.ok) throw new Error((await response.text()).slice(0, 180));
        const saved = await response.json();
        artifactRef.current = saved;
        snapshotRef.current = saved.snapshot;
        setArtifact(saved);
        dirtyRef.current = false;
        setSaveState("saved");
        window.dispatchEvent(new CustomEvent("artifact-version-saved", { detail: saved }));
      } catch (error) {
        setSaveState("error");
        setMessage(`No se pudo guardar el plano: ${error.message}`);
      }
    }, 650);
    return () => clearTimeout(saveTimerRef.current);
  }, [plan, hydrated, projectId, projectName, token]);
  useEffect(() => {
    if (!hydrated) return undefined;
    const controller = new AbortController();
    const timer = setTimeout(async () => {
      try {
        const response = await fetch(`/api/v1/projects/${projectId}/artefactos-diseno-tierras/geometria/validar`, { method: "POST", signal: controller.signal, headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" }, body: JSON.stringify({ geometry: geometryFromPlan(planRef.current) }) });
        if (response.ok) setPlanCheck(await response.json());
      } catch { /* Keep the last check while offline or when the request is superseded. */ }
    }, 200);
    return () => { clearTimeout(timer); controller.abort(); };
  }, [plan, hydrated, projectId, token]);
  function savePlan(update) {
    const next = typeof update === "function" ? update(plan) : { ...plan, ...update };
    setHistory((old) => ({ past: [...old.past, plan], future: [] })); persist(next);
  }
  function undo() {
    if (!history.past.length) return;
    const previous = history.past.at(-1);
    setHistory((old) => ({ past: old.past.slice(0, -1), future: [plan, ...old.future] })); persist(previous); setAnchor(null);
  }
  function redo() {
    if (!history.future.length) return;
    const next = history.future[0];
    setHistory((old) => ({ past: [...old.past, plan], future: old.future.slice(1) })); persist(next); setAnchor(null);
  }
  useEffect(() => {
    function onKeyDown(event) {
      if (!opened || ["INPUT", "SELECT", "TEXTAREA"].includes(event.target.tagName) || event.target.isContentEditable) return;
      const key = event.key.toLowerCase();
      if (key === "escape") { event.preventDefault(); setOpened(false); setAnchor(null); setContextMenu(null); return; }
      if ((key === "delete" || key === "backspace") && selectedIds.length) { event.preventDefault(); deleteSelected(); return; }
      if (!(event.ctrlKey || event.metaKey)) return;
      if (key === "z") { event.preventDefault(); event.shiftKey ? redo() : undo(); }
      if (key === "y") { event.preventDefault(); redo(); }
    }
    function onToolKey(event) {
      if (!opened || event.ctrlKey || event.metaKey || event.altKey || ["INPUT", "SELECT", "TEXTAREA"].includes(event.target.tagName) || event.target.isContentEditable) return;
      const key = event.key.toLowerCase();
      const tools = { w: "conductor", r: "electrode", b: "structure", v: "select" };
      if (tools[key]) { event.preventDefault(); activateTool(tools[key]); }
    }
    window.addEventListener("keydown", onKeyDown);
    window.addEventListener("keydown", onToolKey);
    return () => { window.removeEventListener("keydown", onKeyDown); window.removeEventListener("keydown", onToolKey); };
  }, [opened, history, plan, selectedId, selectedIds, tool, anchor, calibrationMode]);
  function beginGesture(event, item, mode = "move", corner = null) {
    event.preventDefault(); event.stopPropagation();
    const ids = selectedIds.includes(item.id) && selectedIds.length > 1 ? selectedIds : [item.id];
    const gestureMode = mode === "move" && ids.length > 1 ? "move-selection" : mode;
    setTool("select"); setSelectedIds(ids); setSelectedId(ids.length === 1 ? item.id : null); setPropertiesOpen(ids.length === 1); setMessage("");
    const point = toWorld(event);
    const originals = plan.items.filter((candidate) => ids.includes(candidate.id));
    gestureRef.current = { pointerId: event.pointerId, itemId: item.id, itemIds: ids, mode: gestureMode, corner, start: point, before: plan, original: item, originals, moved: false };
    canvasRef.current?.setPointerCapture(event.pointerId);
  }
  function beginAreaSelection(event) {
    if (calibrationMode) return;
    if (tool !== "select" || event.button !== 0 || event.target.closest?.("[data-item-id]")) return;
    const point = toUnboundedWorld(event);
    if (point.x < 0 || point.x > plan.length || point.y < 0 || point.y > plan.width) return;
    event.preventDefault();
    selectionRef.current = { pointerId: event.pointerId, start: point, current: point };
    setSelectionRect({ x: point.x, y: point.y, width: 0, height: 0 });
    setSelectedId(null); setSelectedIds([]); setPropertiesOpen(false); setContextMenu(null);
    canvasRef.current?.setPointerCapture(event.pointerId);
  }
  function moveGesture(event) {
    if (selectionRef.current?.pointerId === event.pointerId) {
      const point = toWorld(event);
      selectionRef.current.current = point;
      setSelectionRect({ x: selectionRef.current.start.x, y: selectionRef.current.start.y, width: point.x - selectionRef.current.start.x, height: point.y - selectionRef.current.start.y });
      return;
    }
    const gesture = gestureRef.current;
    if (!gesture || gesture.pointerId !== event.pointerId) return;
    const point = toWorld(event);
    if (!gesture.moved && Math.hypot(point.x - gesture.start.x, point.y - gesture.start.y) < 0.02) return;
    gesture.moved = true;
    const { original, itemId } = gesture;
    let movedItem;
    if (gesture.mode === "move-selection") {
      const allPoints = gesture.originals.flatMap((item) => item.type === "conductor" ? [item.from, item.to] : item.type === "structure" ? [{ x: item.x-item.width/2, y: item.y-item.height/2 }, { x: item.x+item.width/2, y: item.y+item.height/2 }] : [{ x: item.x, y: item.y }]);
      const minX = Math.min(...allPoints.map((p) => p.x)), maxX = Math.max(...allPoints.map((p) => p.x)), minY = Math.min(...allPoints.map((p) => p.y)), maxY = Math.max(...allPoints.map((p) => p.y));
      // Conductor endpoints stay on the construction step.
      const moveStep = gesture.originals.some((item) => item.type === "conductor") ? step : plan.spacing;
      const dx = discreteDelta(point.x - gesture.start.x, moveStep, -minX, plan.length - maxX), dy = discreteDelta(point.y - gesture.start.y, moveStep, -minY, plan.width - maxY);
      const moved = gesture.originals.map((item) => item.type === "conductor" ? { ...item, from: { x: item.from.x+dx, y: item.from.y+dy }, to: { x: item.to.x+dx, y: item.to.y+dy } } : item.type === "electrode" ? { ...item, x: cellCenter(keyX, item.x+dx), y: cellCenter(keyY, item.y+dy) } : { ...item, x: item.x+dx, y: item.y+dy });
      const movedElectrodes = moved.filter((item) => item.type === "electrode");
      const occupied = plan.items.filter((item) => item.type === "electrode" && !gesture.itemIds.includes(item.id));
      const cells = new Set();
      for (const electrode of movedElectrodes) { const cell = cellFor(electrode); const cellKey = `${cell.col}:${cell.row}`; if (cells.has(cellKey) || occupied.some((other) => { const c=cellFor(other); return c.col===cell.col&&c.row===cell.row; })) { setMessage("El movimiento crearía dos electrodos en la misma celda."); return; } cells.add(cellKey); }
      const replacements = new Map(moved.map((item) => [item.id,item]));
      persist({ ...plan, items: plan.items.map((item) => replacements.get(item.id) || item) });
      return;
    }
    if (gesture.mode === "resize") {
      const fixed = { x: gesture.corner.includes("w") ? original.x + original.width / 2 : original.x - original.width / 2, y: gesture.corner.includes("n") ? original.y + original.height / 2 : original.y - original.height / 2 };
      const x = snapSize(Math.abs(point.x - fixed.x), plan.spacing), y = snapSize(Math.abs(point.y - fixed.y), plan.spacing);
      const left = point.x <= fixed.x ? fixed.x - x : fixed.x, top = point.y <= fixed.y ? fixed.y - y : fixed.y;
      movedItem = { ...original, x: left + x / 2, y: top + y / 2, width: x, height: y };
    } else if (original.type === "electrode") {
      movedItem = { ...original, x: cellCenter(keyX, point.x), y: cellCenter(keyY, point.y) };
      const cell = cellFor(movedItem);
      const occupied = plan.items.some((other) => other.id !== itemId && other.type === "electrode" && cellFor(other).col === cell.col && cellFor(other).row === cell.row);
      if (occupied) { setMessage("Ya hay un electrodo en esa celda."); return; }
    } else if (original.type === "conductor" && gesture.mode === "endpoint") {
      movedItem = { ...original, [gesture.corner]: { x: snapCoordinate(point.x, plan.length, step), y: snapCoordinate(point.y, plan.width, step) } };
    } else if (original.type === "conductor") {
      const dx = point.x - gesture.start.x, dy = point.y - gesture.start.y;
      const minX = Math.min(original.from.x, original.to.x), maxX = Math.max(original.from.x, original.to.x), minY = Math.min(original.from.y, original.to.y), maxY = Math.max(original.from.y, original.to.y);
      const offsetX = discreteDelta(dx, step, -minX, plan.length - maxX), offsetY = discreteDelta(dy, step, -minY, plan.width - maxY);
      movedItem = { ...original, from: { x: original.from.x + offsetX, y: original.from.y + offsetY }, to: { x: original.to.x + offsetX, y: original.to.y + offsetY } };
    } else {
      movedItem = { ...original, x: nearest(keyX, point.x), y: nearest(keyY, point.y) };
    }
    const next = { ...plan, items: plan.items.map((item) => item.id === itemId ? movedItem : item) };
    persist(next);
  }
  function endGesture(event) {
    if (selectionRef.current?.pointerId === event.pointerId) {
      const end = selectionRef.current.current || selectionRef.current.start;
      const rect = { x: selectionRef.current.start.x, y: selectionRef.current.start.y, width: end.x - selectionRef.current.start.x, height: end.y - selectionRef.current.start.y };
      const bounds = { left: Math.min(rect.x,rect.x+rect.width), right: Math.max(rect.x,rect.x+rect.width), top: Math.min(rect.y,rect.y+rect.height), bottom: Math.max(rect.y,rect.y+rect.height) };
      const ids = plan.items.filter((item) => intersectsSelection(item,bounds)).map((item)=>item.id);
      selectionRef.current=null; setSelectionRect(null); setSelectedIds(ids); setSelectedId(ids.length===1?ids[0]:null); setPropertiesOpen(ids.length===1); return;
    }
    const gesture = gestureRef.current;
    if (!gesture || gesture.pointerId !== event.pointerId) return;
    if (gesture.moved) setHistory((old) => ({ past: [...old.past, gesture.before], future: [] }));
    gestureRef.current = null;
  }
  function updateSelected(key, value) {
    if (!selectedItem) return;
    if (key === "label") {
      savePlan({ ...plan, items: plan.items.map((item) => item.id === selectedId ? { ...item, label: value } : item) });
      return;
    }
    const n = Number(value);
    if (!Number.isFinite(n)) return;
    const nextItems = plan.items.map((item) => {
      if (item.id !== selectedId) return item;
      if (item.type === "conductor" && key.includes(".")) { const [end, axis] = key.split("."); return { ...item, [end]: { ...item[end], [axis]: snapCoordinate(n, axis === "x" ? plan.length : plan.width, step) } }; }
      if (item.type === "electrode" && (key === "x" || key === "y")) return { ...item, [key]: cellCenter(key === "x" ? keyX : keyY, n) };
      if (item.type === "structure" && (key === "width" || key === "height")) return { ...item, [key]: snapSize(n, plan.spacing) };
      return { ...item, [key]: n };
    });
    if (selectedItem.type === "electrode") {
      const candidate = nextItems.find((item) => item.id === selectedId);
      const cell = cellFor(candidate);
      if (electrodes.some((item) => item.id !== selectedId && cellFor(item).col === cell.col && cellFor(item).row === cell.row)) { setMessage("Ya hay un electrodo en esa celda."); return; }
    }
    savePlan({ ...plan, items: nextItems });
  }
  function place(event) {
    setContextMenu(null);
    if (tool === "select") return;
    const raw = toWorld(event);
    const point = tool === "electrode"
      ? { x: cellCenter(keyX, raw.x), y: cellCenter(keyY, raw.y) }
      : tool === "conductor"
        ? { x: snapCoordinate(raw.x, plan.length, step), y: snapCoordinate(raw.y, plan.width, step) }
        : { x: nearest(keyX, raw.x), y: nearest(keyY, raw.y) };
    if (tool === "electrode") {
      const cell = cellFor(point);
      if (electrodes.some((item) => { const other = cellFor(item); return other.col === cell.col && other.row === cell.row; })) { setMessage("Ya hay un electrodo en esa celda de la retícula."); return; }
      savePlan((old) => ({ ...old, items: [...old.items, { id: crypto.randomUUID(), type: "electrode", ...point }] })); setMessage(""); return;
    }
    if (tool === "structure") {
      savePlan({ ...plan, items: [...plan.items, { id: crypto.randomUUID(), type: "structure", ...point, width: snapSize(Number(obstacleWidth), plan.spacing), height: snapSize(Number(obstacleHeight), plan.spacing), label: "" }] }); setMessage(""); return;
    }
    const conductorPoint = snapConductorPoint(raw);
    if (!anchor) { setAnchor(conductorPoint); setMessage(electrodeAt(conductorPoint) ? "Punto inicial conectado al electrodo." : "Marca el otro extremo del conductor."); return; }
    if (anchor.x === conductorPoint.x && anchor.y === conductorPoint.y) { setMessage("El conductor necesita dos puntos distintos."); setAnchor(null); return; }
    savePlan({ ...plan, items: [...plan.items, { id: crypto.randomUUID(), type: "conductor", from: anchor, to: conductorPoint }] }); setAnchor(null); setMessage("");
  }
  function electrodeAt(point) {
    const threshold = 9 / unitsPerPixel;
    return electrodes.find((item) => Math.hypot(item.x - point.x, item.y - point.y) <= threshold) || null;
  }
  function snapConductorPoint(point) {
    const threshold = 9 / unitsPerPixel;
    const closest = electrodes.reduce((best, item) => {
      const distance = Math.hypot(item.x - point.x, item.y - point.y);
      return distance <= threshold && (!best || distance < best.distance) ? { item, distance } : best;
    }, null);
    return closest ? { x: closest.item.x, y: closest.item.y } : { x: snapCoordinate(point.x, plan.length, step), y: snapCoordinate(point.y, plan.width, step) };
  }
  function deleteSelected() {
    const ids = selectedIds.length ? selectedIds : selectedId ? [selectedId] : [];
    if (!ids.length) return;
    savePlan({ ...plan, items: plan.items.filter((item) => !ids.includes(item.id)) }); setSelectedId(null); setSelectedIds([]); setPropertiesOpen(false); setContextMenu(null);
  }
  function showContextMenu(event) {
    event.preventDefault();
    const targetItem = event.target.closest?.("[data-item-id]");
    if (targetItem) { setSelectedId(targetItem.dataset.itemId); setSelectedIds([targetItem.dataset.itemId]); setPropertiesOpen(true); }
    setContextAddOpen(false);
    setContextMenu({ x: Math.min(event.clientX, window.innerWidth - 205), y: Math.min(event.clientY, window.innerHeight - 230) });
  }
  function activateTool(nextTool) {
    const selectedElectrodes = plan.items.filter((item) => selectedIds.includes(item.id) && item.type === "electrode");
    if (nextTool === "electrode" && (selectedItem?.type === "electrode" || selectedElectrodes.length > 0)) {
      setMessage("Ya hay un electrodo seleccionado. Elige otro elemento o mueve el existente.");
      return;
    }
    setTool(nextTool);
    const startElectrode = selectedItem?.type === "electrode" ? selectedItem : selectedElectrodes.length === 1 ? selectedElectrodes[0] : null;
    if (nextTool === "conductor" && startElectrode) {
      setAnchor({ x: startElectrode.x, y: startElectrode.y });
      setMessage("El conductor parte del electrodo seleccionado. Marca el otro extremo.");
    } else {
      setAnchor(null);
      setMessage("");
    }
  }
  function setGeometry(key, value) {
    const n = Number(value);
    if (Number.isFinite(n) && n > 0 && (key !== "spacing" || n <= Math.max(plan.length, plan.width)) && (key !== "snap" || n <= 10)) {
      savePlan((old) => ({ ...old, [key]: n }));
      if (key === "spacing") { setObstacleWidth((old) => snapSize(Number(old), n)); setObstacleHeight((old) => snapSize(Number(old), n)); }
    }
  }
  function addArea(type) {
    const label = type === "intervenible" ? "Área intervenible" : "Zona no intervenible";
    savePlan((old) => ({ ...old, areas: [...(old.areas || []), { type, label, polygon: [
      { x: 0, y: 0 }, { x: Math.min(old.length, old.spacing * 2), y: 0 },
      { x: Math.min(old.length, old.spacing * 2), y: old.width }, { x: 0, y: old.width },
    ] }] }));
  }
  function updateArea(index, key, value) {
    if (key === "polygon_text") {
      const polygon = value.split(";").map((pair) => pair.trim().split(/[ ,]+/).map(Number));
      if (polygon.length >= 3 && polygon.every((point) => point.length === 2 && point.every(Number.isFinite))) {
        savePlan((old) => ({ ...old, areas: old.areas.map((area, i) => i === index ? { ...area, polygon: polygon.map(([x, y]) => ({ x, y })) } : area) }));
      }
      return;
    }
    savePlan((old) => ({ ...old, areas: old.areas.map((area, i) => i === index ? { ...area, [key]: value } : area) }));
  }
  function removeArea(index) { savePlan((old) => ({ ...old, areas: old.areas.filter((_, i) => i !== index) })); }
  async function generateAreaGrid(index) {
    const area = plan.areas[index];
    const position = plan.areas.slice(0, index).filter((item) => item.type === "intervenible").length;
    const response = await fetch(`/api/v1/projects/${projectId}/artefactos-diseno-tierras/geometria/malla-en-areas`, { method: "POST", headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" }, body: JSON.stringify({ geometry: geometryFromPlan(plan), areas: [position], spacing_x_m: plan.spacing, spacing_y_m: plan.spacing }) });
    const result = await response.json().catch(() => ({}));
    if (!response.ok) return setMessage(typeof result.detail === "string" ? result.detail : "No se pudo generar la malla en esa zona.");
    const lines = result.conductors.map((line) => ({ id: crypto.randomUUID(), type: "conductor", from: line.start, to: line.end }));
    // Electrodes of the replaced grid that the new one does not reach would block saving.
    const orphans = electrodes.filter((item) => !lines.some((line) => pointSegmentDistance(item, line.from, line.to) <= 1e-3)).map((item) => item.id);
    savePlan((old) => ({ ...old, items: [...old.items.filter((item) => item.type !== "conductor" && !orphans.includes(item.id)), ...lines] }));
    setLayers((current) => ({ ...current, conductors: true }));
    setMessage(`${lines.length} conductores generados en «${area.label || "la zona"}» (retícula de ${plan.spacing} m, paso ${step} m). La malla anterior se reemplazó${orphans.length ? ` y se retiraron ${orphans.length} electrodos que quedaban fuera de la nueva malla` : ""}.`);
  }
  function exportPlan() {
    const data = { project_id: projectId, project_name: projectName, unit: "m", geometry: { length_m: plan.length, width_m: plan.width, discretization_m: plan.spacing, areas: plan.areas || [] }, components: plan.items, validation: issues };
    const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: "application/json" })); const link = document.createElement("a"); link.href = url; link.download = `plano-puesta-tierra-${projectId}.json`; link.click(); URL.revokeObjectURL(url);
  }
  function renderCanvas() {
    const px = (x, y) => toCanvas(x, y);
    return <svg ref={canvasRef} className="ground-plan-svg" style={zoom !== 1 ? { width: `${zoom * 100}%`, maxHeight: "none" } : undefined} viewBox="0 0 1000 690" onPointerDown={beginAreaSelection} onClick={(event) => { if (!captureCalibration(event)) place(event); }} onContextMenu={showContextMenu} onPointerMove={moveGesture} onPointerUp={endGesture} onPointerCancel={endGesture} role="application" aria-label="Plano de puesta a tierra editable">
      <defs><pattern id={`plan-dots-${projectId}`} width="16" height="16" patternUnits="userSpaceOnUse"><circle cx="1" cy="1" r=".8" fill="#dbe3df"/></pattern><pattern id={`plan-hatch-${projectId}`} width="8" height="8" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><line x1="0" y1="0" x2="0" y2="8" className="plan-hatch-line"/></pattern></defs>
      <rect width="1000" height="690" fill={`url(#plan-dots-${projectId})`}/>{backgroundUrl && (plan.background || backgroundSize) && <image href={backgroundUrl} x={drawing.x + (plan.background?.offset_x_m || 0) * unitsPerPixel} y={drawing.y + (plan.background?.offset_y_m || 0) * unitsPerPixel} width={plan.background ? plan.background.width_px * plan.background.scale_m_per_pixel * unitsPerPixel : drawing.width} height={plan.background ? plan.background.height_px * plan.background.scale_m_per_pixel * unitsPerPixel : drawing.height} opacity=".42" preserveAspectRatio="none"/>}<rect x={drawing.x} y={drawing.y} width={drawing.width} height={drawing.height} fill="#fbfcfb" fillOpacity={backgroundUrl ? ".35" : "1"} stroke="#b7c8c0" strokeWidth="1.5"/>
      {calibrationPoints.map((point, index) => { const canvasPoint = toCanvas(point.x, point.y); return <g key={`calibration-${index}`}><circle cx={canvasPoint.x} cy={canvasPoint.y} r="7" fill="#d97706" stroke="white" strokeWidth="2"/><text x={canvasPoint.x + 10} y={canvasPoint.y - 10} fill="#9a3412" fontSize="13">{index + 1}</text></g>; })}
      <g stroke="#e4eae7" strokeWidth="1">{keyX.map((x,i)=>{const X=px(x,0).x;return <line key={`gx${i}`} x1={X} x2={X} y1={drawing.y} y2={drawing.y+drawing.height}/>;})}{keyY.map((y,i)=>{const Y=px(0,y).y;return <line key={`gy${i}`} x1={drawing.x} x2={drawing.x+drawing.width} y1={Y} y2={Y}/>;})}</g>
      <rect x={drawing.x} y={drawing.y} width={drawing.width} height={drawing.height} className="plan-site"/>
      {(plan.areas||[]).map((area,index)=>{if(!layers[area.type==="intervenible"?"intervenible":"blocked"])return null;const points=areaPoints(area).map((p)=>px(p.x,p.y)),bounds=areaBounds(area),cx=(px(bounds.x_min,0).x+px(bounds.x_max,0).x)/2,cy=(px(0,bounds.y_min).y+px(0,bounds.y_max).y)/2,invalid=issues.some((issue)=>issue.id===`area-${index}`),coords=points.map((p)=>`${p.x},${p.y}`).join(" ");return <g key={`area-${index}`} className="plan-area-layer"><polygon points={coords} className={`${area.type==="intervenible"?"plan-area":"plan-blocked-area"}${invalid?" invalid":""}`}/>{area.type!=="intervenible"&&<polygon points={coords} fill={`url(#plan-hatch-${projectId})`}/>}<text x={cx} y={cy} textAnchor="middle" className="plan-area-label">{area.label||(area.type==="intervenible"?"Área":"Zona")}</text></g>;})}
      {layers.blocked&&blockers.map((item)=>{const c=px(item.x,item.y),w=item.width*unitsPerPixel,h=item.height*unitsPerPixel,left=c.x-w/2,top=c.y-h/2;return <g key={item.id} data-item-id={item.id} className={selectedIds.includes(item.id)?"plan-selected":""} onPointerDown={(event)=>beginGesture(event,item,"move")}><rect x={left} y={top} width={w} height={h} rx="3" className={issues.some((issue)=>issue.id===item.id)?"plan-obstacle invalid":"plan-obstacle"}/><rect x={left} y={top} width={w} height={h} rx="3" fill={`url(#plan-hatch-${projectId})`} pointerEvents="none"/><text x={c.x} y={c.y-2} textAnchor="middle" className="plan-obstacle-label">{item.label || "Elemento constructivo"}</text><text x={c.x} y={c.y+13} textAnchor="middle" className="plan-area-kind">No intervenible</text>{selectedIds.includes(item.id)&&selectedIds.length===1&&<><rect x={left-5} y={top-5} width="10" height="10" className="plan-resize-handle" aria-label="Redimensionar desde esquina superior izquierda" onPointerDown={(event)=>beginGesture(event,item,"resize","nw")}/><rect x={left+w-5} y={top+h-5} width="10" height="10" className="plan-resize-handle" aria-label="Redimensionar desde esquina inferior derecha" onPointerDown={(event)=>beginGesture(event,item,"resize","se")}/></>}</g>;})}
      {layers.conductors&&drawnConductors.map((item)=>{const a=px(item.from.x,item.from.y),b=px(item.to.x,item.to.y);return <g key={item.id} data-item-id={item.id} className={selectedIds.includes(item.id)?"plan-selected":""} onPointerDown={(event)=>beginGesture(event,item,"move")}><line x1={a.x} y1={a.y} x2={b.x} y2={b.y} className="plan-hit-target"/><line x1={a.x} y1={a.y} x2={b.x} y2={b.y} className={issues.some((issue)=>issue.id===item.id)?"plan-conductor invalid":"plan-conductor"}/><circle cx={a.x} cy={a.y} r="7" data-item-id={item.id} className="plan-endpoint plan-endpoint-hit" onPointerDown={(event)=>beginGesture(event,item,"endpoint","from")}/><circle cx={b.x} cy={b.y} r="7" data-item-id={item.id} className="plan-endpoint plan-endpoint-hit" onPointerDown={(event)=>beginGesture(event,item,"endpoint","to")}/></g>;})}
      {layers.electrodes&&electrodes.map((item)=>{const c=px(item.x,item.y);return <g key={item.id} data-item-id={item.id} className={selectedIds.includes(item.id)?"plan-selected":""} onPointerDown={(event)=>{if(tool!=="conductor")beginGesture(event,item,"move");}}><circle cx={c.x} cy={c.y} r="12" className="plan-electrode-hit"/><circle cx={c.x} cy={c.y} r="8" className={issues.some((issue)=>issue.id===item.id)?"plan-electrode invalid":"plan-electrode"}/><circle cx={c.x} cy={c.y} r="2" fill="white"/></g>;})}
      {selectionRect&&(()=>{const left=Math.min(selectionRect.x,selectionRect.x+selectionRect.width),top=Math.min(selectionRect.y,selectionRect.y+selectionRect.height),width=Math.abs(selectionRect.width),height=Math.abs(selectionRect.height);return <rect className="ground-plan-selection-box" x={drawing.x+left*unitsPerPixel} y={drawing.y+top*unitsPerPixel} width={width*unitsPerPixel} height={height*unitsPerPixel}/>;})()}
      {anchor&&(()=>{const c=px(anchor.x,anchor.y);return <circle cx={c.x} cy={c.y} r="7" className="plan-anchor"/>;})()}
      <text x={drawing.x+drawing.width/2} y={drawing.y+drawing.height+25} textAnchor="middle" className="plan-dimension">Terreno · {plan.length} m</text><text x={drawing.x-24} y={drawing.y+drawing.height/2} textAnchor="middle" transform={`rotate(-90 ${drawing.x-24} ${drawing.y+drawing.height/2})`} className="plan-dimension">{plan.width} m</text>
    </svg>;
  }
  function renderPreview() {
    const size = { width: 360, height: 190, padding: 17 };
    const scale = Math.min((size.width - size.padding * 2) / plan.length, (size.height - size.padding * 2) / plan.width);
    const field = { width: plan.length * scale, height: plan.width * scale };
    const origin = { x: (size.width - field.width) / 2, y: (size.height - field.height) / 2 };
    const point = (x, y) => ({ x: origin.x + x * scale, y: origin.y + y * scale });
    return <svg className="ground-plan-preview-svg" viewBox={`0 0 ${size.width} ${size.height}`} role="img" aria-label="Previsualización de la malla de puesta a tierra">
      <defs><pattern id={`plan-preview-hatch-${projectId}`} width="5" height="5" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><line x1="0" y1="0" x2="0" y2="5" className="plan-hatch-line"/></pattern></defs>
      <rect x={origin.x} y={origin.y} width={field.width} height={field.height} className="ground-plan-preview-field"/>
      {(plan.areas||[]).map((area,index)=>{if(!layers[area.type==="intervenible"?"intervenible":"blocked"])return null;const coords=areaPoints(area).map((p)=>{const q=point(p.x,p.y);return `${q.x},${q.y}`}).join(" ");return <g key={`preview-area-${index}`}><polygon points={coords} className={area.type==="intervenible"?"plan-area":"plan-blocked-area"}/>{area.type!=="intervenible"&&<polygon points={coords} fill={`url(#plan-preview-hatch-${projectId})`}/>}</g>;})}
      <g className="ground-plan-preview-grid">{keyX.map((x,index)=>{const p=point(x,0);return <line key={`px${index}`} x1={p.x} x2={p.x} y1={origin.y} y2={origin.y+field.height}/>;})}{keyY.map((y,index)=>{const p=point(0,y);return <line key={`py${index}`} x1={origin.x} x2={origin.x+field.width} y1={p.y} y2={p.y}/>;})}</g>
      {layers.blocked&&blockers.map((item)=>{const c=point(item.x,item.y),x=c.x-item.width*scale/2,y=c.y-item.height*scale/2;return <g key={item.id}><rect className="ground-plan-preview-obstacle" x={x} y={y} width={item.width*scale} height={item.height*scale} rx="2"/><rect x={x} y={y} width={item.width*scale} height={item.height*scale} rx="2" fill={`url(#plan-preview-hatch-${projectId})`}/></g>;})}
      {layers.conductors&&drawnConductors.map((item)=>{const a=point(item.from.x,item.from.y),b=point(item.to.x,item.to.y);return <line key={item.id} className={issues.some((issue)=>issue.id===item.id)?"ground-plan-preview-conductor invalid":"ground-plan-preview-conductor"} x1={a.x} y1={a.y} x2={b.x} y2={b.y}/>;})}
      {layers.electrodes&&electrodes.map((item)=>{const c=point(item.x,item.y);return <circle key={item.id} className="ground-plan-preview-electrode" cx={c.x} cy={c.y} r="3.4"/>;})}
      {!plan.items.length&&<text x={size.width/2} y={size.height/2} textAnchor="middle" className="ground-plan-preview-empty">La malla aparecerá aquí al dibujarla</text>}
    </svg>;
  }
  const legend = <div className="ground-plan-preview-legend" role="group" aria-label="Capas del plano">{LAYERS.map((layer)=><button key={layer.id} type="button" aria-pressed={layers[layer.id]} className={layers[layer.id]?"":"off"} onClick={()=>toggleLayer(layer.id)} title={layers[layer.id]?"Ocultar capa":"Mostrar capa"}><i className={layer.swatch}/>{layer.label}</button>)}<span><i className="conflict"/>Conflicto</span></div>;
  const palette = <div className="ground-plan-tools"><button className={tool === "select" ? "active" : ""} onClick={() => activateTool("select")}><Maximize2 size={16}/><span>Seleccionar</span><kbd>V</kbd></button><button className={tool === "conductor" ? "active" : ""} onClick={() => activateTool("conductor")}><Cable size={16}/><span>Conductor</span><kbd>W</kbd></button><button className={tool === "electrode" ? "active" : ""} disabled={selectedItem?.type === "electrode" || selectedIds.some((id)=>plan.items.some((item)=>item.id===id&&item.type==="electrode"))} title={selectedItem?.type === "electrode" || selectedIds.some((id)=>plan.items.some((item)=>item.id===id&&item.type==="electrode")) ? "Ya hay un electrodo seleccionado" : undefined} onClick={() => activateTool("electrode")}><CircleDot size={16}/><span>Electrodo</span><kbd>R</kbd></button><button className={tool === "structure" ? "active" : ""} onClick={() => activateTool("structure")}><Square size={16}/><span>Elemento constructivo</span><kbd>B</kbd></button></div>;
  const field = (label, key, value, min = 0, step = "any") => <label key={key}>{label}<input type="number" min={min} step={step} value={value} onChange={(event) => updateSelected(key, event.target.value)}/></label>;
  const selectedLabel = selectedItem?.type === "electrode" ? "Electrodo" : selectedItem?.type === "conductor" ? "Conductor" : selectedItem ? "Elemento constructivo" : "";
  return <>
    <section className="panel ground-plan-launch"><div className="panel-heading"><div><Cable size={17}/><h2>Plano de puesta a tierra</h2></div><span className="muted-label">{plan.items.length} elementos</span></div><p>Dibuja la malla del proyecto, coloca electrodos y representa los elementos constructivos que no se pueden atravesar.</p><div className="ground-plan-launch-preview ground-plan-preview">{renderPreview()}{legend}</div><button className="button primary" onClick={() => setOpened(true)}><Maximize2 size={15}/>Abrir editor de plano</button></section>
    {opened&&<div className="ground-plan-backdrop" onMouseDown={(e)=>{if(e.target===e.currentTarget){setOpened(false);setAnchor(null);}}}><section className="ground-plan-drawer" onClick={()=>contextMenu&&setContextMenu(null)} role="dialog" aria-modal="true" aria-label={`Dibujo de puesta a tierra: ${projectName}`}>
      <header className="ground-plan-header"><div><div className="eyebrow">{projectName}</div><h2>Plano de puesta a tierra</h2></div><div className="ground-plan-header-actions"><button className="button" onClick={undo} disabled={!history.past.length} title="Deshacer (Ctrl/Cmd+Z)"><Undo2 size={15}/>Deshacer</button><button className="button" onClick={redo} disabled={!history.future.length} title="Rehacer (Ctrl/Cmd+Y)"><Redo2 size={15}/>Rehacer</button><button className="button" onClick={exportPlan}><Download size={15}/>Exportar plano</button><button className="icon-button" aria-label="Cerrar editor de plano" onClick={()=>{setOpened(false);setAnchor(null);}}><X size={18}/></button></div></header>
      <div className="ground-plan-body"><aside className="ground-plan-sidebar"><h3>Paleta</h3>{palette}{tool==="structure"&&<div className="ground-plan-fields"><label>Largo (m)<input type="number" min={plan.spacing} step={plan.spacing} value={obstacleWidth} onChange={(e)=>setObstacleWidth(e.target.value)}/></label><label>Ancho (m)<input type="number" min={plan.spacing} step={plan.spacing} value={obstacleHeight} onChange={(e)=>setObstacleHeight(e.target.value)}/></label></div>}
        {selectedIds.length>1&&<div className="ground-plan-multi-selection"><strong>{selectedIds.length} elementos seleccionados</strong><small>Arrastra uno para moverlos en pasos discretos.</small><button className="button ground-plan-delete" onClick={deleteSelected}>Eliminar seleccionados</button></div>}
        <details className="ground-plan-properties" open={propertiesOpen} onToggle={(event)=>setPropertiesOpen(event.currentTarget.open)}><summary>{selectedItem ? `Propiedades · ${selectedLabel}` : "Propiedades del elemento"}</summary>{selectedItem ? <div className="ground-plan-fields">{selectedItem.type === "conductor" ? <><strong>Punto inicial</strong>{field("X (m)","from.x",selectedItem.from.x,0,1)}{field("Y (m)","from.y",selectedItem.from.y,0,1)}<strong>Punto final</strong>{field("X (m)","to.x",selectedItem.to.x,0,1)}{field("Y (m)","to.y",selectedItem.to.y,0,1)}</> : <>{field("X (m)","x",selectedItem.x)}{field("Y (m)","y",selectedItem.y)}{selectedItem.type === "structure" && <><label>Etiqueta<input type="text" value={selectedItem.label || ""} placeholder="Elemento constructivo" onChange={(event)=>updateSelected("label",event.target.value)}/></label>{field("Largo (m)","width",selectedItem.width,plan.spacing,plan.spacing)}{field("Ancho (m)","height",selectedItem.height,plan.spacing,plan.spacing)}<small>Las dimensiones avanzan en pasos de {plan.spacing} m.</small></>}</>}<button className="button ground-plan-delete" onClick={deleteSelected}>Eliminar elemento</button></div> : <p>Selecciona un elemento en el plano o en la lista.</p>}</details>
        <h3 className="ground-plan-section-title">Elementos ({plan.items.length})</h3><ul className="ground-plan-object-list">{plan.items.map((item,index)=><li key={item.id}><button className={selectedIds.includes(item.id)?"selected":""} onClick={()=>{setSelectedId(item.id);setSelectedIds([item.id]);setPropertiesOpen(true);setTool("select");}}><span>{item.type==="conductor"?"Conductor":item.type==="electrode"?"Electrodo":item.label||"Elemento constructivo"} {index+1}</span><small>{item.type==="electrode"?`${item.x.toFixed(2)}, ${item.y.toFixed(2)} m`:item.type==="conductor"?`${item.from.x}, ${item.from.y} → ${item.to.x}, ${item.to.y} m`:`${item.width.toFixed(1)} × ${item.height.toFixed(1)} m`}</small></button></li>)}</ul>
        <h3 className="ground-plan-section-title">Terreno</h3><div className="ground-plan-fields"><label>Largo del terreno (m)<input type="number" min="1" step="any" value={plan.length} onChange={(e)=>setGeometry("length",e.target.value)}/></label><label>Ancho del terreno (m)<input type="number" min="1" step="any" value={plan.width} onChange={(e)=>setGeometry("width",e.target.value)}/></label><label>Discretización (m)<input type="number" min="0.1" step="any" value={plan.spacing} onChange={(e)=>setGeometry("spacing",e.target.value)}/></label><label>Paso de dibujo (m)<input type="number" min="0.05" max="10" step="any" value={step} onChange={(e)=>setGeometry("snap",e.target.value)}/></label></div>
        <h3 className="ground-plan-section-title">Zonas del terreno ({(plan.areas||[]).length})</h3><div className="ground-plan-zones">{(plan.areas||[]).map((area,index)=><fieldset key={index} className={`ground-plan-zone ${area.type}`}><div className="ground-plan-zone-head"><input aria-label="Nombre de la zona" value={area.label||""} onChange={(e)=>updateArea(index,"label",e.target.value)}/><button className="icon-button" title="Eliminar zona" onClick={()=>removeArea(index)}><X size={13}/></button></div><select aria-label="Tipo de zona" value={area.type} onChange={(e)=>updateArea(index,"type",e.target.value)}><option value="intervenible">Intervenible</option><option value="non_intervenible">No intervenible</option></select><label>Vértices (x,y en m; separados por punto y coma)<textarea defaultValue={areaPoints(area).map((p)=>`${p.x},${p.y}`).join("; ")} onBlur={(e)=>updateArea(index,"polygon_text",e.target.value)}/></label>{area.type==="intervenible"&&<button className="button primary" onClick={()=>generateAreaGrid(index)}>Generar malla aquí</button>}</fieldset>)}<div className="ground-plan-zone-actions"><button className="button" onClick={()=>addArea("intervenible")}><Plus size={13}/>Área intervenible</button><button className="button" onClick={()=>addArea("non_intervenible")}><Plus size={13}/>No intervenible</button></div><small>Las áreas intervenibles son espacio disponible: genera la malla en la que vayas a usar. Los edificios existentes se dibujan como elemento constructivo (B); la malla no puede atravesarlos.</small></div>
        <h3 className="ground-plan-section-title">Plano de fondo y CAD</h3><div className="ground-plan-fields"><label>Fondo<select value={backgroundFile} onChange={(e)=>setBackgroundFile(e.target.value)}><option value="">Selecciona imagen o PDF</option>{sourceFiles.filter((file)=>file.status === "available" && ["application/pdf","image/png","image/jpeg"].includes(file.mime_type)).map((file)=><option key={file.upload_id} value={file.upload_id}>{file.filename}</option>)}</select></label>{sourceFiles.find((file)=>file.upload_id === backgroundFile)?.mime_type === "application/pdf"&&<label>Página PDF<input type="number" min="1" step="1" value={backgroundPage} onChange={(e)=>setBackgroundPage(e.target.value)}/></label>}<button className="button" onClick={prepareBackground}><Image size={14}/>Calibrar con dos puntos</button><button className="button" onClick={proposePlanVision} disabled={visionBusy}>{visionBusy ? "Analizando plano…" : "Proponer obstáculos con IA"}</button>{calibrationMode&&<><label>Distancia real (m)<input type="number" min="0.001" step="any" value={calibrationDistance} onChange={(e)=>setCalibrationDistance(e.target.value)}/></label><small>{calibrationPoints.length}/2 puntos marcados. Haz clic sobre los extremos de una cota conocida.</small><button className="button primary" disabled={calibrationPoints.length !== 2} onClick={attachBackground}>Guardar escala</button></>}{plan.background&&<small>Escala guardada: {plan.background.scale_m_per_pixel} m/píxel{plan.background.source_page ? ` · página ${plan.background.source_page}` : ""}</small>}<label>DXF<select value={dxfFile} onChange={(e)=>setDxfFile(e.target.value)}><option value="">Selecciona un DXF</option>{sourceFiles.filter((file)=>file.status === "available" && file.mime_type === "application/dxf").map((file)=><option key={file.upload_id} value={file.upload_id}>{file.filename}</option>)}</select></label><button className="button" onClick={importDxf}><Upload size={14}/>Importar propuesta DXF</button>{visionProposal&&<div className="ground-plan-vision-proposal"><strong>Revisión de propuesta</strong><span>{visionProposal.structures?.length || 0} obstáculos detectados{visionProposal.source_page ? ` · página ${visionProposal.source_page}` : ""}</span>{visionProposal.warnings?.map((warning, index)=><small key={index}>{warning}</small>)}{visionProposal.structures?.length > 0&&<ul>{visionProposal.structures.map((item, index)=><li key={`${item.x}-${item.y}-${index}`}>{item.label || "Elemento constructivo"} · {item.width} × {item.height} m · ({item.x}, {item.y}) m</li>)}</ul>}<div><button className="button primary" onClick={acceptVisionProposal}>Aceptar propuesta editable</button><button className="button" onClick={()=>setVisionProposal(null)}>Descartar</button></div></div>}</div>
        <h3 className="ground-plan-section-title">Capas</h3>{LAYERS.map((layer)=><label key={layer.id} className="ground-plan-check"><input type="checkbox" checked={layers[layer.id]} onChange={()=>toggleLayer(layer.id)}/> {layer.label}</label>)}
      </aside><div className="ground-plan-board"><div className={`ground-plan-canvas${zoom>1?" zoomed":""}`}>{renderCanvas()}</div><div className="ground-plan-help"><span>{tool==="conductor"?"Marca dos puntos; los extremos cercanos a electrodos se conectan automáticamente.":tool==="electrode"?"Coloca un electrodo en una celda. Solo se permite uno por celda.":tool==="structure"?"Coloca un elemento constructivo no atravesable.":"Elige una herramienta para editar el plano."}{message&&<strong className="ground-plan-message">{message}</strong>}</span><div className="ground-plan-zoom" role="group" aria-label="Controles de zoom"><button aria-label="Alejar" title="Alejar" onClick={()=>setZoom((value)=>Math.max(0.5,value-0.2))} disabled={zoom<=0.5}><Minus size={15}/></button><span>{Math.round(zoom*100)}%</span><button aria-label="Acercar" title="Acercar" onClick={()=>setZoom((value)=>Math.min(3,value+0.2))} disabled={zoom>=3}><Plus size={15}/></button><button onClick={()=>setZoom(1)} disabled={zoom===1}>Restablecer</button></div></div></div>
      <aside className="ground-plan-inspector"><h3>Previsualización de la malla</h3><div className="ground-plan-preview">{renderPreview()}{legend}</div><h3 className="ground-plan-inspector-rules">Reglas del plano</h3>{issues.length?<ul className="ground-plan-issues">{issues.map((issue,i)=><li key={`${issue.id}-${i}`}><AlertTriangle size={14}/>{issue.text}</li>)}</ul>:<p className="ground-plan-ok">Sin conflictos geométricos detectados.</p>}{warnings.length>0&&<ul className="ground-plan-warnings">{warnings.map((warning,i)=><li key={`warning-${i}`}><AlertTriangle size={14}/>{warning}</li>)}</ul>}
        <details ref={optimizerPanelRef} className="optimizer-context-panel"><summary><SlidersHorizontal size={14}/> Matherra · optimización matemática</summary>
          <TopologyOptimizerPanel projectId={projectId} token={token} artifact={artifact} canRun={Boolean(artifactRef.current)&&saveState==="saved"&&!dirtyRef.current} onShowResults={onShowResults}/>
        </details>
        <p className="ground-plan-shortcuts">Ctrl/Cmd+Z deshacer · Ctrl/Cmd+Y rehacer</p></aside></div>
      {contextMenu&&<div className="ground-plan-context-menu" style={{left:contextMenu.x,top:contextMenu.y}} onClick={(event)=>event.stopPropagation()}><button disabled={!history.past.length} onClick={undo}><Undo2 size={14}/>Deshacer</button><button disabled={!history.future.length} onClick={redo}><Redo2 size={14}/>Rehacer</button><button onClick={()=>{activateTool("select");setContextMenu(null);}}><Maximize2 size={14}/>Seleccionar</button><details open={contextAddOpen} onMouseEnter={()=>setContextAddOpen(true)} onMouseLeave={()=>setContextAddOpen(false)}><summary onClick={(event)=>{event.preventDefault();setContextAddOpen(true);}}><Square size={14}/>Añadir</summary><div><button onClick={()=>{activateTool("conductor");setContextMenu(null);setContextAddOpen(false);}}><Cable size={14}/>Conductor</button><button disabled={selectedItem?.type === "electrode"} title={selectedItem?.type === "electrode" ? "Ya hay un electrodo seleccionado" : undefined} onClick={()=>{activateTool("electrode");setContextMenu(null);setContextAddOpen(false);}}><CircleDot size={14}/>Electrodo</button><button onClick={()=>{activateTool("structure");setContextMenu(null);setContextAddOpen(false);}}><Square size={14}/>Elemento constructivo</button></div></details></div>}
      <footer className="ground-plan-footer">La discretización define las celdas y los puntos de conexión. {saveState === "pending" ? "Guardando versión…" : saveState === "error" ? "Error de guardado" : artifact ? `Versión ${artifact.version} guardada` : "Plano pendiente de guardar"}<span>{issues.length?`${issues.length} conflictos`:"Sin conflictos"}</span></footer>
    </section></div>}
  </>;
}

function axisPositions(span, spacing) { const count=Math.max(2,Math.ceil(span/spacing)+1); return Array.from({length:count},(_,i)=>(i*span)/(count-1)); }
function perimeterRods(count, length, width) { const perimeter=2*(length+width); return Array.from({length:count},(_,index)=>{ const d=perimeter*index/Math.max(count,1); if(d<length)return[d,0]; if(d<length+width)return[length,d-length]; if(d<2*length+width)return[length-(d-length-width),width]; return[0,width-(d-2*length-width)]; }); }
function makeGrid(size, spacing) { const values=Array.from({length:Math.floor(size/spacing)+1},(_,i)=>Number((i*spacing).toFixed(6))); if(values.at(-1)<size-1e-6)values.push(size); return values; }
// Coordinates on multiples of the construction step (geometry.snap_m), inside the site.
function snapCoordinate(value, size, step) { const top = Math.floor(size / step + 1e-8) * step; return Number(Math.max(0, Math.min(top, Math.floor(value / step + 0.5) * step)).toFixed(6)); }
function snapSize(value, step) { return Math.max(step, Number((Math.round(value / step) * step).toFixed(6))); }
function discreteDelta(value, step, min, max) {
  const low = Math.ceil(min / step - 1e-8), high = Math.floor(max / step + 1e-8);
  if (low > high) return 0;
  return Number((Math.max(low, Math.min(high, Math.round(value / step))) * step).toFixed(6));
}
function intersectsSelection(item, bounds) {
  if (item.type === "electrode") return item.x >= bounds.left && item.x <= bounds.right && item.y >= bounds.top && item.y <= bounds.bottom;
  if (item.type === "structure") return rectsOverlap(worldRect(item), bounds);
  return segmentIntersectsRect(item.from, item.to, bounds);
}
function cellIndex(grid,value) { for(let i=0;i<grid.length-1;i++)if(value>=grid[i]&&value<grid[i+1])return i;return Math.max(0,grid.length-2); }
function cellCenter(grid,value) { const i=cellIndex(grid,value); return (grid[i]+grid[i+1])/2; }
function worldRect(item) { return {left:item.x-item.width/2,right:item.x+item.width/2,top:item.y-item.height/2,bottom:item.y+item.height/2}; }
function rectsOverlap(a,b) { return a.left<b.right&&a.right>b.left&&a.top<b.bottom&&a.bottom>b.top; }
function pointSegmentDistance(p, a, b) { const dx=b.x-a.x, dy=b.y-a.y, l2=dx*dx+dy*dy; const t=l2?Math.max(0,Math.min(1,((p.x-a.x)*dx+(p.y-a.y)*dy)/l2)):0; return Math.hypot(p.x-a.x-t*dx, p.y-a.y-t*dy); }
function pointInRect(point,rect) { return point.x>=rect.left&&point.x<=rect.right&&point.y>=rect.top&&point.y<=rect.bottom; }

export { GroundingPlanDrawer };
