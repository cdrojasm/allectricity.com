import React, { useEffect, useMemo, useRef, useState } from "react";
import { AlertTriangle, Cable, CircleDot, Download, Maximize2, Minus, Plus, Square, Undo2, Redo2, X } from "lucide-react";

const VIEW = { x: 70, y: 55, width: 860, height: 530 };
const emptyPlan = { length: 40, width: 30, spacing: 5, items: [] };
function segmentIntersectsRect(a, b, rect) {
  const dx = b.x - a.x, dy = b.y - a.y;
  let low = 0, high = 1;
  for (const [p, q] of [[-dx, a.x - rect.left], [dx, rect.right - a.x], [-dy, a.y - rect.top], [dy, rect.bottom - a.y]]) {
    if (p === 0) { if (q < 0) return false; continue; }
    const t = q / p;
    if (p < 0) low = Math.max(low, t); else high = Math.min(high, t);
    if (low > high) return false;
  }
  return true;
}

function GroundingPlanDrawer({ projectId, projectName, conversation, token }) {
  const storageKey = `grounding-plan:${projectId}`;
  const [plan, setPlan] = useState(() => {
    try { const stored = JSON.parse(localStorage.getItem(storageKey) || "{}"); return { ...emptyPlan, ...stored, items: Array.isArray(stored.items) ? stored.items.map(({ subtype, ...item }) => item.type === "conductor" ? { ...item, from: { x: Math.round(item.from.x), y: Math.round(item.from.y) }, to: { x: Math.round(item.to.x), y: Math.round(item.to.y) } } : item) : [] }; }
    catch { return emptyPlan; }
  });
  useEffect(() => {
    if (!conversation || localStorage.getItem(storageKey)) return;
    let live = true;
    (async () => {
      try {
        const headers = { Authorization: `Bearer ${token}` };
        const [stateResponse, artifactsResponse] = await Promise.all([
          fetch(`/api/v1/conversations/${conversation.id}/agent-state`, { headers }),
          fetch(`/api/v1/projects/${projectId}/artefactos-diseno-tierras`, { headers }),
        ]);
        if (!stateResponse.ok || !artifactsResponse.ok) return;
        const [state, artifacts] = await Promise.all([stateResponse.json(), artifactsResponse.json()]);
        const artifact = artifacts.find((row) => row.artifact_id === state.artifact_id) || (artifacts.length === 1 ? artifacts[0] : null);
        const geometry = artifact?.snapshot?.geometry;
        if (!live || !geometry || localStorage.getItem(storageKey)) return;
        const spacing = geometry.conductor_spacing_m || geometry.conductor_spacing_x_m || 5;
        const items = [
          ...(geometry.conductors || []).map((line) => ({ id: crypto.randomUUID(), type: "conductor", from: { x: Math.round(line.start.x), y: Math.round(line.start.y) }, to: { x: Math.round(line.end.x), y: Math.round(line.end.y) } })),
          ...(geometry.rods || []).map((rod) => ({ id: crypto.randomUUID(), type: "electrode", x: rod.x, y: rod.y })),
        ];
        const next = { length: geometry.length_m || emptyPlan.length, width: geometry.width_m || emptyPlan.width, spacing, items };
        setPlan(next);
        localStorage.setItem(storageKey, JSON.stringify(next));
        window.dispatchEvent(new CustomEvent("grounding-plan-updated", { detail: { projectId, plan: next } }));
      } catch { /* Keep the editable default if the artifact is unavailable. */ }
    })();
    return () => { live = false; };
  }, [conversation?.id, projectId, storageKey, token]);
  const [opened, setOpened] = useState(false);
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
  const [conductors, setConductors] = useState(true);
  const [structures, setStructures] = useState(true);
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
  const issues = [];
  for (const item of blockers) {
    if (item.x - item.width / 2 < 0 || item.x + item.width / 2 > plan.length || item.y - item.height / 2 < 0 || item.y + item.height / 2 > plan.width) issues.push({ id: item.id, text: "El elemento constructivo excede el perímetro del plano." });
  }
  for (let i = 0; i < blockers.length; i++) for (let j = i + 1; j < blockers.length; j++) if (rectsOverlap(worldRect(blockers[i]), worldRect(blockers[j]))) issues.push({ id: blockers[j].id, text: "El elemento constructivo se superpone con otro." });
  for (const electrode of electrodes) {
    const cell = cellFor(electrode);
    if (electrodes.some((other) => other.id !== electrode.id && cellFor(other).col === cell.col && cellFor(other).row === cell.row)) issues.push({ id: electrode.id, text: "Ya existe un electrodo en esta celda de la retícula." });
    if (blockers.some((obstacle) => pointInRect(electrode, worldRect(obstacle)))) issues.push({ id: electrode.id, text: "El electrodo está dentro de un elemento constructivo." });
  }
  for (const conductor of drawnConductors) {
    if ([conductor.from, conductor.to].some((point) => point.x < 0 || point.x > plan.length || point.y < 0 || point.y > plan.width)) issues.push({ id: conductor.id, text: "El conductor sale del perímetro del plano." });
    if (blockers.some((obstacle) => segmentIntersectsRect(conductor.from, conductor.to, worldRect(obstacle)))) issues.push({ id: conductor.id, text: "El conductor cruza un elemento constructivo no atravesable." });
  }

  function persist(next) { setPlan(next); try { localStorage.setItem(storageKey, JSON.stringify(next)); } catch { /* Keep edits available in the current session if storage is unavailable. */ } window.dispatchEvent(new CustomEvent("grounding-plan-updated", { detail: { projectId, plan: next } })); }
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
  }, [opened, history, plan, selectedId, selectedIds, tool, anchor]);
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
      // Keep conductor endpoints integral even when the configured grid step is fractional.
      const moveStep = gesture.originals.some((item) => item.type === "conductor") && !Number.isInteger(plan.spacing) ? 1 : plan.spacing;
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
      movedItem = { ...original, [gesture.corner]: { x: integerCoordinate(point.x, plan.length), y: integerCoordinate(point.y, plan.width) } };
    } else if (original.type === "conductor") {
      const dx = point.x - gesture.start.x, dy = point.y - gesture.start.y;
      const minX = Math.min(original.from.x, original.to.x), maxX = Math.max(original.from.x, original.to.x), minY = Math.min(original.from.y, original.to.y), maxY = Math.max(original.from.y, original.to.y);
      const offsetX = Math.max(-minX, Math.min(Math.floor(plan.length) - maxX, Math.round(dx))), offsetY = Math.max(-minY, Math.min(Math.floor(plan.width) - maxY, Math.round(dy)));
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
      if (item.type === "conductor" && key.includes(".")) { const [end, axis] = key.split("."); return { ...item, [end]: { ...item[end], [axis]: integerCoordinate(n, axis === "x" ? plan.length : plan.width) } }; }
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
        ? { x: integerCoordinate(raw.x, plan.length), y: integerCoordinate(raw.y, plan.width) }
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
    return closest ? { x: closest.item.x, y: closest.item.y } : { x: integerCoordinate(point.x, plan.length), y: integerCoordinate(point.y, plan.width) };
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
    if (Number.isFinite(n) && n > 0 && (key !== "spacing" || n <= Math.max(plan.length, plan.width))) {
      savePlan((old) => ({ ...old, [key]: n }));
      if (key === "spacing") { setObstacleWidth((old) => snapSize(Number(old), n)); setObstacleHeight((old) => snapSize(Number(old), n)); }
    }
  }
  function exportPlan() {
    const data = { project_id: projectId, project_name: projectName, unit: "m", geometry: { length_m: plan.length, width_m: plan.width, discretization_m: plan.spacing }, components: plan.items, validation: issues };
    const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: "application/json" })); const link = document.createElement("a"); link.href = url; link.download = `plano-puesta-tierra-${projectId}.json`; link.click(); URL.revokeObjectURL(url);
  }
  function renderCanvas() {
    const px = (x, y) => toCanvas(x, y);
    return <svg ref={canvasRef} className="ground-plan-svg" style={zoom !== 1 ? { width: `${zoom * 100}%`, maxHeight: "none" } : undefined} viewBox="0 0 1000 690" onPointerDown={beginAreaSelection} onClick={place} onContextMenu={showContextMenu} onPointerMove={moveGesture} onPointerUp={endGesture} onPointerCancel={endGesture} role="application" aria-label="Plano de puesta a tierra editable">
      <defs><pattern id={`plan-dots-${projectId}`} width="16" height="16" patternUnits="userSpaceOnUse"><circle cx="1" cy="1" r=".8" fill="#dbe3df"/></pattern></defs>
      <rect width="1000" height="690" fill={`url(#plan-dots-${projectId})`}/><rect x={drawing.x} y={drawing.y} width={drawing.width} height={drawing.height} fill="#fbfcfb" stroke="#b7c8c0" strokeWidth="1.5"/>
      <g stroke="#e4eae7" strokeWidth="1">{keyX.map((x,i)=>{const X=px(x,0).x;return <line key={`gx${i}`} x1={X} x2={X} y1={drawing.y} y2={drawing.y+drawing.height}/>;})}{keyY.map((y,i)=>{const Y=px(0,y).y;return <line key={`gy${i}`} x1={drawing.x} x2={drawing.x+drawing.width} y1={Y} y2={Y}/>;})}</g>
      {conductors&&drawnConductors.map((item)=>{const a=px(item.from.x,item.from.y),b=px(item.to.x,item.to.y);return <g key={item.id} data-item-id={item.id} className={selectedIds.includes(item.id)?"plan-selected":""} onPointerDown={(event)=>beginGesture(event,item,"move")}><line x1={a.x} y1={a.y} x2={b.x} y2={b.y} className="plan-hit-target"/><line x1={a.x} y1={a.y} x2={b.x} y2={b.y} className={issues.some((issue)=>issue.id===item.id)?"plan-conductor invalid":"plan-conductor"}/><circle cx={a.x} cy={a.y} r="7" data-item-id={item.id} className="plan-endpoint plan-endpoint-hit" onPointerDown={(event)=>beginGesture(event,item,"endpoint","from")}/><circle cx={b.x} cy={b.y} r="7" data-item-id={item.id} className="plan-endpoint plan-endpoint-hit" onPointerDown={(event)=>beginGesture(event,item,"endpoint","to")}/></g>;})}
      {structures&&blockers.map((item)=>{const c=px(item.x,item.y),w=item.width*unitsPerPixel,h=item.height*unitsPerPixel,left=c.x-w/2,top=c.y-h/2;return <g key={item.id} data-item-id={item.id} className={selectedIds.includes(item.id)?"plan-selected":""} onPointerDown={(event)=>beginGesture(event,item,"move")}><rect x={left} y={top} width={w} height={h} rx="3" className={issues.some((issue)=>issue.id===item.id)?"plan-obstacle invalid":"plan-obstacle"}/><text x={c.x} y={c.y+4} textAnchor="middle" className="plan-obstacle-label">{item.label || "Elemento constructivo"}</text>{selectedIds.includes(item.id)&&selectedIds.length===1&&<><rect x={left-5} y={top-5} width="10" height="10" className="plan-resize-handle" aria-label="Redimensionar desde esquina superior izquierda" onPointerDown={(event)=>beginGesture(event,item,"resize","nw")}/><rect x={left+w-5} y={top+h-5} width="10" height="10" className="plan-resize-handle" aria-label="Redimensionar desde esquina inferior derecha" onPointerDown={(event)=>beginGesture(event,item,"resize","se")}/></>}</g>;})}
      {electrodes.map((item)=>{const c=px(item.x,item.y);return <g key={item.id} data-item-id={item.id} className={selectedIds.includes(item.id)?"plan-selected":""} onPointerDown={(event)=>{if(tool!=="conductor")beginGesture(event,item,"move");}}><circle cx={c.x} cy={c.y} r="12" className="plan-electrode-hit"/><circle cx={c.x} cy={c.y} r="8" className={issues.some((issue)=>issue.id===item.id)?"plan-electrode invalid":"plan-electrode"}/><circle cx={c.x} cy={c.y} r="2" fill="white"/></g>;})}
      {selectionRect&&(()=>{const left=Math.min(selectionRect.x,selectionRect.x+selectionRect.width),top=Math.min(selectionRect.y,selectionRect.y+selectionRect.height),width=Math.abs(selectionRect.width),height=Math.abs(selectionRect.height);return <rect className="ground-plan-selection-box" x={drawing.x+left*unitsPerPixel} y={drawing.y+top*unitsPerPixel} width={width*unitsPerPixel} height={height*unitsPerPixel}/>;})()}
      {anchor&&(()=>{const c=px(anchor.x,anchor.y);return <circle cx={c.x} cy={c.y} r="7" className="plan-anchor"/>;})()}
      <text x={drawing.x+drawing.width/2} y={drawing.y+drawing.height+25} textAnchor="middle" className="plan-dimension">{plan.length} m</text><text x={drawing.x-24} y={drawing.y+drawing.height/2} textAnchor="middle" transform={`rotate(-90 ${drawing.x-24} ${drawing.y+drawing.height/2})`} className="plan-dimension">{plan.width} m</text>
    </svg>;
  }
  function renderPreview() {
    const size = { width: 360, height: 190, padding: 17 };
    const scale = Math.min((size.width - size.padding * 2) / plan.length, (size.height - size.padding * 2) / plan.width);
    const field = { width: plan.length * scale, height: plan.width * scale };
    const origin = { x: (size.width - field.width) / 2, y: (size.height - field.height) / 2 };
    const point = (x, y) => ({ x: origin.x + x * scale, y: origin.y + y * scale });
    return <svg className="ground-plan-preview-svg" viewBox={`0 0 ${size.width} ${size.height}`} role="img" aria-label="Previsualización de la malla de puesta a tierra">
      <rect x={origin.x} y={origin.y} width={field.width} height={field.height} className="ground-plan-preview-field"/>
      <g className="ground-plan-preview-grid">{keyX.map((x,index)=>{const p=point(x,0);return <line key={`px${index}`} x1={p.x} x2={p.x} y1={origin.y} y2={origin.y+field.height}/>;})}{keyY.map((y,index)=>{const p=point(0,y);return <line key={`py${index}`} x1={origin.x} x2={origin.x+field.width} y1={p.y} y2={p.y}/>;})}</g>
      {blockers.map((item)=>{const c=point(item.x,item.y);return <rect key={item.id} className="ground-plan-preview-obstacle" x={c.x-item.width*scale/2} y={c.y-item.height*scale/2} width={item.width*scale} height={item.height*scale} rx="2"/>;})}
      {drawnConductors.map((item)=>{const a=point(item.from.x,item.from.y),b=point(item.to.x,item.to.y);return <line key={item.id} className="ground-plan-preview-conductor" x1={a.x} y1={a.y} x2={b.x} y2={b.y}/>;})}
      {electrodes.map((item)=>{const c=point(item.x,item.y);return <circle key={item.id} className="ground-plan-preview-electrode" cx={c.x} cy={c.y} r="3.4"/>;})}
      {!plan.items.length&&<text x={size.width/2} y={size.height/2} textAnchor="middle" className="ground-plan-preview-empty">La malla aparecerá aquí al dibujarla</text>}
    </svg>;
  }
  const palette = <div className="ground-plan-tools"><button className={tool === "select" ? "active" : ""} onClick={() => activateTool("select")}><Maximize2 size={16}/><span>Seleccionar</span><kbd>V</kbd></button><button className={tool === "conductor" ? "active" : ""} onClick={() => activateTool("conductor")}><Cable size={16}/><span>Conductor</span><kbd>W</kbd></button><button className={tool === "electrode" ? "active" : ""} disabled={selectedItem?.type === "electrode" || selectedIds.some((id)=>plan.items.some((item)=>item.id===id&&item.type==="electrode"))} title={selectedItem?.type === "electrode" || selectedIds.some((id)=>plan.items.some((item)=>item.id===id&&item.type==="electrode")) ? "Ya hay un electrodo seleccionado" : undefined} onClick={() => activateTool("electrode")}><CircleDot size={16}/><span>Electrodo</span><kbd>R</kbd></button><button className={tool === "structure" ? "active" : ""} onClick={() => activateTool("structure")}><Square size={16}/><span>Elemento constructivo</span><kbd>B</kbd></button></div>;
  const field = (label, key, value, min = 0, step = "any") => <label key={key}>{label}<input type="number" min={min} step={step} value={value} onChange={(event) => updateSelected(key, event.target.value)}/></label>;
  const selectedLabel = selectedItem?.type === "electrode" ? "Electrodo" : selectedItem?.type === "conductor" ? "Conductor" : selectedItem ? "Elemento constructivo" : "";
  return <>
    <section className="panel ground-plan-launch"><div className="panel-heading"><div><Cable size={17}/><h2>Plano de puesta a tierra</h2></div><span className="muted-label">{plan.items.length} elementos</span></div><p>Dibuja la malla del proyecto, coloca electrodos y representa los elementos constructivos que no se pueden atravesar.</p><div className="ground-plan-launch-preview ground-plan-preview">{renderPreview()}<div className="ground-plan-preview-legend"><span><i className="conductor"/>Conductores</span><span><i className="electrode"/>Electrodos</span><span><i className="obstacle"/>Construcción</span></div></div><button className="button primary" onClick={() => setOpened(true)}><Maximize2 size={15}/>Abrir drawer de dibujo</button></section>
    {opened&&<div className="ground-plan-backdrop" onMouseDown={(e)=>{if(e.target===e.currentTarget){setOpened(false);setAnchor(null);}}}><section className="ground-plan-drawer" onClick={()=>contextMenu&&setContextMenu(null)} role="dialog" aria-modal="true" aria-label={`Dibujo de puesta a tierra: ${projectName}`}>
      <header className="ground-plan-header"><div><div className="eyebrow">{projectName}</div><h2>Plano de puesta a tierra</h2></div><div className="ground-plan-header-actions"><button className="button" onClick={undo} disabled={!history.past.length} title="Deshacer (Ctrl/Cmd+Z)"><Undo2 size={15}/>Deshacer</button><button className="button" onClick={redo} disabled={!history.future.length} title="Rehacer (Ctrl/Cmd+Y)"><Redo2 size={15}/>Rehacer</button><button className="button" onClick={exportPlan}><Download size={15}/>Exportar plano</button><button className="icon-button" aria-label="Cerrar drawer" onClick={()=>{setOpened(false);setAnchor(null);}}><X size={18}/></button></div></header>
      <div className="ground-plan-body"><aside className="ground-plan-sidebar"><h3>Paleta</h3>{palette}{tool==="structure"&&<div className="ground-plan-fields"><label>Largo (m)<input type="number" min={plan.spacing} step={plan.spacing} value={obstacleWidth} onChange={(e)=>setObstacleWidth(e.target.value)}/></label><label>Ancho (m)<input type="number" min={plan.spacing} step={plan.spacing} value={obstacleHeight} onChange={(e)=>setObstacleHeight(e.target.value)}/></label></div>}
        {selectedIds.length>1&&<div className="ground-plan-multi-selection"><strong>{selectedIds.length} elementos seleccionados</strong><small>Arrastra uno para moverlos en pasos discretos.</small><button className="button ground-plan-delete" onClick={deleteSelected}>Eliminar seleccionados</button></div>}
        <details className="ground-plan-properties" open={propertiesOpen} onToggle={(event)=>setPropertiesOpen(event.currentTarget.open)}><summary>{selectedItem ? `Propiedades · ${selectedLabel}` : "Propiedades del elemento"}</summary>{selectedItem ? <div className="ground-plan-fields">{selectedItem.type === "conductor" ? <><strong>Punto inicial</strong>{field("X (m)","from.x",selectedItem.from.x,0,1)}{field("Y (m)","from.y",selectedItem.from.y,0,1)}<strong>Punto final</strong>{field("X (m)","to.x",selectedItem.to.x,0,1)}{field("Y (m)","to.y",selectedItem.to.y,0,1)}</> : <>{field("X (m)","x",selectedItem.x)}{field("Y (m)","y",selectedItem.y)}{selectedItem.type === "structure" && <><label>Etiqueta<input type="text" value={selectedItem.label || ""} placeholder="Elemento constructivo" onChange={(event)=>updateSelected("label",event.target.value)}/></label>{field("Largo (m)","width",selectedItem.width,plan.spacing,plan.spacing)}{field("Ancho (m)","height",selectedItem.height,plan.spacing,plan.spacing)}<small>Las dimensiones avanzan en pasos de {plan.spacing} m.</small></>}</>}<button className="button ground-plan-delete" onClick={deleteSelected}>Eliminar elemento</button></div> : <p>Selecciona un elemento en el plano o en la lista.</p>}</details>
        <h3 className="ground-plan-section-title">Elementos ({plan.items.length})</h3><ul className="ground-plan-object-list">{plan.items.map((item,index)=><li key={item.id}><button className={selectedIds.includes(item.id)?"selected":""} onClick={()=>{setSelectedId(item.id);setSelectedIds([item.id]);setPropertiesOpen(true);setTool("select");}}><span>{item.type==="conductor"?"Conductor":item.type==="electrode"?"Electrodo":item.label||"Elemento constructivo"} {index+1}</span><small>{item.type==="electrode"?`${item.x.toFixed(2)}, ${item.y.toFixed(2)} m`:item.type==="conductor"?`${item.from.x}, ${item.from.y} → ${item.to.x}, ${item.to.y} m`:`${item.width.toFixed(1)} × ${item.height.toFixed(1)} m`}</small></button></li>)}</ul>
        <h3 className="ground-plan-section-title">Geometría del plano</h3><div className="ground-plan-fields"><label>Largo (m)<input type="number" min="1" step="any" value={plan.length} onChange={(e)=>setGeometry("length",e.target.value)}/></label><label>Ancho (m)<input type="number" min="1" step="any" value={plan.width} onChange={(e)=>setGeometry("width",e.target.value)}/></label><label>Discretización (m)<input type="number" min="0.1" step="any" value={plan.spacing} onChange={(e)=>setGeometry("spacing",e.target.value)}/></label></div>
        <h3 className="ground-plan-section-title">Visibilidad</h3><label className="ground-plan-check"><input type="checkbox" checked={conductors} onChange={(e)=>setConductors(e.target.checked)}/> Conductores</label><label className="ground-plan-check"><input type="checkbox" checked={structures} onChange={(e)=>setStructures(e.target.checked)}/> Elementos constructivos</label>
      </aside><div className="ground-plan-board"><div className={`ground-plan-canvas${zoom>1?" zoomed":""}`}>{renderCanvas()}</div><div className="ground-plan-help"><span>{tool==="conductor"?"Marca dos puntos; los extremos cercanos a electrodos se conectan automáticamente.":tool==="electrode"?"Coloca un electrodo en una celda. Solo se permite uno por celda.":tool==="structure"?"Coloca un elemento constructivo no atravesable.":"Elige una herramienta para editar el plano."}{message&&<strong className="ground-plan-message">{message}</strong>}</span><div className="ground-plan-zoom" role="group" aria-label="Controles de zoom"><button aria-label="Alejar" title="Alejar" onClick={()=>setZoom((value)=>Math.max(0.5,value-0.2))} disabled={zoom<=0.5}><Minus size={15}/></button><span>{Math.round(zoom*100)}%</span><button aria-label="Acercar" title="Acercar" onClick={()=>setZoom((value)=>Math.min(3,value+0.2))} disabled={zoom>=3}><Plus size={15}/></button><button onClick={()=>setZoom(1)} disabled={zoom===1}>Restablecer</button></div></div></div>
      <aside className="ground-plan-inspector"><h3>Previsualización de la malla</h3><div className="ground-plan-preview">{renderPreview()}<div className="ground-plan-preview-legend"><span><i className="conductor"/>Conductores</span><span><i className="electrode"/>Electrodos</span><span><i className="obstacle"/>Construcción</span></div></div><h3 className="ground-plan-inspector-rules">Reglas del plano</h3>{issues.length?<ul className="ground-plan-issues">{issues.map((issue,i)=><li key={`${issue.id}-${i}`}><AlertTriangle size={14}/>{issue.text}</li>)}</ul>:<p className="ground-plan-ok">Sin conflictos geométricos detectados.</p>}<p className="ground-plan-shortcuts">Ctrl/Cmd+Z deshacer · Ctrl/Cmd+Y rehacer</p></aside></div>
      {contextMenu&&<div className="ground-plan-context-menu" style={{left:contextMenu.x,top:contextMenu.y}} onClick={(event)=>event.stopPropagation()}><button disabled={!history.past.length} onClick={undo}><Undo2 size={14}/>Deshacer</button><button disabled={!history.future.length} onClick={redo}><Redo2 size={14}/>Rehacer</button><button onClick={()=>{activateTool("select");setContextMenu(null);}}><Maximize2 size={14}/>Seleccionar</button><details open={contextAddOpen} onMouseEnter={()=>setContextAddOpen(true)} onMouseLeave={()=>setContextAddOpen(false)}><summary onClick={(event)=>{event.preventDefault();setContextAddOpen(true);}}><Square size={14}/>Añadir</summary><div><button onClick={()=>{activateTool("conductor");setContextMenu(null);setContextAddOpen(false);}}><Cable size={14}/>Conductor</button><button disabled={selectedItem?.type === "electrode"} title={selectedItem?.type === "electrode" ? "Ya hay un electrodo seleccionado" : undefined} onClick={()=>{activateTool("electrode");setContextMenu(null);setContextAddOpen(false);}}><CircleDot size={14}/>Electrodo</button><button onClick={()=>{activateTool("structure");setContextMenu(null);setContextAddOpen(false);}}><Square size={14}/>Elemento constructivo</button></div></details></div>}
      <footer className="ground-plan-footer">La discretización define las celdas y los puntos de conexión. El plano se guarda localmente en este navegador.<span>{issues.length?`${issues.length} conflictos`:"Sin conflictos"}</span></footer>
    </section></div>}
  </>;
}

function makeGrid(size, spacing) { const values=Array.from({length:Math.floor(size/spacing)+1},(_,i)=>Number((i*spacing).toFixed(6))); if(values.at(-1)<size-1e-6)values.push(size); return values; }
function integerCoordinate(value, size) { return Math.max(0, Math.min(Math.floor(size), Math.round(value))); }
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
function pointInRect(point,rect) { return point.x>=rect.left&&point.x<=rect.right&&point.y>=rect.top&&point.y<=rect.bottom; }

export { GroundingPlanDrawer };
