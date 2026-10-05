import React, { useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  Activity,
  ArrowDownToLine,
  ArrowDown,
  ArrowLeft,
  ArrowRight,
  ArrowUp,
  Box,
  Check,
  ChevronDown,
  ChevronRight,
  CircleHelp,
  File,
  FileImage,
  FileSpreadsheet,
  FolderOpen,
  GitBranch,
  History,
  Layers,
  LayoutGrid,
  MapPin,
  MessageCircle,
  Minus,
  Maximize2,
  Mic,
  Network,
  Paperclip,
  Plus,
  Pencil,
  RotateCcw,
  Search,
  Settings2,
  ShieldCheck,
  Sparkles,
  Square,
  X,
  Trash2,
  Zap,
} from "lucide-react";
import "./styles.css";

const mimeByExtension = {
  pdf: "application/pdf",
  png: "image/png",
  jpg: "image/jpeg",
  jpeg: "image/jpeg",
  csv: "text/csv",
  xlsx: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
};
const uploadableMimeTypes = new Set(Object.values(mimeByExtension));
const uploadStatusLabels = {
  uploading: "Uploading to quarantine…",
  pending: "Queued for processing",
  scanning: "Scanning and extracting…",
  available: "Processed and ready",
  rejected: "Rejected · file validation failed",
  failed: "Processing failed · retry with Add files",
};
const defaults = {
  length: 40,
  width: 30,
  spacing: 5,
  rods: 12,
  depth: 0.6,
  resistivity: 120,
  soilDepth: 2.5,
  current: 12500,
  time: 0.5,
  copperPrice: 12.8,
};
const initialMessages = [
  {
    role: "user",
    text: "Create a grounding mesh for the north substation using the site layout and soil measurements.",
  },
  {
    role: "assistant",
    text: "Here is a starting point for your grounding design. The reference layout combines a rectangular copper mesh with perimeter ground rods.",
    card: true,
  },
];
const IconButton = ({ title, children, ...props }) => (
  <button className="icon-button" title={title} aria-label={title} {...props}>
    {children}
  </button>
);
function download(name, text, type = "application/json") {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function Mesh({ parameters: p, selected, onSelect }) {
  const nx = Math.min(20, Math.ceil(p.length / p.spacing));
  const ny = Math.min(20, Math.ceil(p.width / p.spacing));
  const rods = Array.from({ length: p.rods }, (_, i) => {
    const t = (i / p.rods) * 4;
    return t < 1
      ? [70 + t * 350, 65]
      : t < 2
        ? [420, 65 + (t - 1) * 220]
        : t < 3
          ? [420 - (t - 2) * 350, 285]
          : [70, 285 - (t - 3) * 220];
  });
  return (
    <svg
      viewBox="0 0 490 350"
      className="mesh-svg"
      aria-label="Interactive grounding mesh plan"
    >
      <defs>
        <pattern id="dots" width="15" height="15" patternUnits="userSpaceOnUse">
          <circle cx="1" cy="1" r=".7" fill="#ccd6de" />
        </pattern>
      </defs>
      <rect width="490" height="350" fill="url(#dots)" />
      <rect
        x="53"
        y="48"
        width="384"
        height="254"
        rx="4"
        fill="#f0f7f5"
        stroke="#ccd9d4"
        strokeDasharray="5 5"
      />
      <g stroke="#46978c" strokeWidth="1.5">
        {Array.from({ length: nx + 1 }, (_, i) => (
          <line
            key={"x" + i}
            x1={70 + (i * 350) / nx}
            x2={70 + (i * 350) / nx}
            y1="65"
            y2="285"
          />
        ))}
        {Array.from({ length: ny + 1 }, (_, i) => (
          <line
            key={"y" + i}
            x1="70"
            x2="420"
            y1={65 + (i * 220) / ny}
            y2={65 + (i * 220) / ny}
          />
        ))}
      </g>
      <rect
        x="70"
        y="65"
        width="350"
        height="220"
        fill="none"
        stroke="#217f72"
        strokeWidth="3"
      />
      <rect
        x="188"
        y="133"
        width="114"
        height="75"
        rx="3"
        fill="#eef1f3"
        stroke="#bdc8d0"
      />
      <path
        d="M198 144h94v53h-94z"
        fill="none"
        stroke="#c8d1d8"
        strokeDasharray="4 3"
      />
      <text x="245" y="167" textAnchor="middle" fill="#778791" fontSize="10">
        TRANSFORMER
      </text>
      <text x="245" y="185" textAnchor="middle" fill="#778791" fontSize="10">
        T-01
      </text>
      {rods.map(([x, y], i) => (
        <g
          key={i}
          role="button"
          tabIndex="0"
          aria-label={`Select ground rod ${i + 1}`}
          onClick={() => onSelect(i)}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === " ") {
              e.preventDefault();
              onSelect(i);
            }
          }}
          className="rod"
        >
          <circle cx={x} cy={y} r="11" fill="transparent" />
          <circle
            cx={x}
            cy={y}
            r={selected === i ? 7 : 4.5}
            fill={selected === i ? "#edb44d" : "#fff"}
            stroke="#217f72"
            strokeWidth="2"
          />
        </g>
      ))}
      <g stroke="#98a7b0" strokeWidth=".8">
        <path d="M70 316h350M70 311v10M420 311v10M35 65v220M30 65h10M30 285h10" />
      </g>
      <g fontSize="10" fill="#7d8b95">
        <text x="245" y="331" textAnchor="middle">
          {p.length}.0 m
        </text>
        <text transform="translate(23 175) rotate(-90)" textAnchor="middle">
          {p.width}.0 m
        </text>
      </g>
      <text x="456" y="37" fill="#6a7b87" fontSize="11">
        N
      </text>
      <path d="m460 44-4 13h8z" fill="#6a7b87" />
    </svg>
  );
}
function PotentialChart() {
  return (
    <svg
      viewBox="0 0 460 158"
      className="potential-chart"
      aria-label="Illustrative surface potential chart, not calculated"
    >
      <defs>
        <linearGradient id="chartFill" x1="0" y1="0" x2="0" y2="1">
          <stop stopColor="#48a092" stopOpacity=".25" />
          <stop offset="1" stopColor="#48a092" stopOpacity="0" />
        </linearGradient>
      </defs>
      {[25, 60, 95, 130].map((y, i) => (
        <g key={y}>
          <line x1="40" x2="445" y1={y} y2={y} stroke="#e9edf1" />
          <text x="28" y={y + 4} textAnchor="end" fill="#94a0ac" fontSize="9">
            {600 - i * 200}
          </text>
        </g>
      ))}
      <path
        d="M40 130C75 125 90 120 120 98S175 32 235 30S320 85 355 105S420 128 445 130V130H40Z"
        fill="url(#chartFill)"
      />
      <path
        d="M40 130C75 125 90 120 120 98S175 32 235 30S320 85 355 105S420 128 445 130"
        fill="none"
        stroke="#398f83"
        strokeWidth="2.5"
      />
      <path d="M40 60H445" stroke="#dcac5c" strokeDasharray="5 4" />
      <text x="440" y="53" textAnchor="end" fill="#b28a48" fontSize="9">
        Illustrative threshold
      </text>
      {[0, 10, 20, 30, 40].map((n, i) => (
        <text key={n} x={40 + i * 100} y="150" fill="#94a0ac" fontSize="9">
          {n} m
        </text>
      ))}
    </svg>
  );
}
function Section({ icon: Icon, title, label, children, defaultOpen = true }) {
  return (
    <details className="refinement-section" open={defaultOpen || undefined}>
      <summary>
        <span className="section-title">
          <Icon size={16} />
          {title}
        </span>
        <span className="section-end">
          {label}
          <ChevronDown size={15} />
        </span>
      </summary>
      <div className="section-content">{children}</div>
    </details>
  );
}

function Login({ onLogin }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  async function submit(event) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const response = await fetch("/api/v1/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password }),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.detail || "Unable to sign in.");
      onLogin(result.access_token);
    } catch (err) {
      setError(err.message || "Unable to reach the authentication service.");
    } finally {
      setBusy(false);
    }
  }
  return (
    <main className="login-page">
      <form className="login-card" onSubmit={submit}>
        <div className="login-brand"><Zap size={22} fill="currentColor" /></div>
        <div className="eyebrow">TERRA WORKSPACE</div>
        <h1>Welcome back</h1>
        <p>Sign in with your local account to continue.</p>
        <label>Email address<input autoComplete="username" type="email" required value={email} onChange={(e) => setEmail(e.target.value)} /></label>
        <label>Password<input autoComplete="current-password" type="password" required value={password} onChange={(e) => setPassword(e.target.value)} /></label>
        {error && <div className="login-error" role="alert">{error}</div>}
        <button className="button primary login-submit" type="submit" disabled={busy}>{busy ? "Signing in…" : "Sign in"}</button>
      </form>
    </main>
  );
}

function MapPicker({ latitude, longitude, onPick }) {
  const mapRef = useRef(null);
  const drag = useRef(null);
  const selected = latitude !== null && latitude !== "" && longitude !== null && longitude !== "" && Number.isFinite(Number(latitude)) && Number.isFinite(Number(longitude));
  const [view, setView] = useState(() => ({ lat: selected ? Number(latitude) : 4.711, lon: selected ? Number(longitude) : -74.072, zoom: 13 }));
  useEffect(() => {
    if (selected) setView((old) => ({ ...old, lat: Number(latitude), lon: Number(longitude) }));
  }, [latitude, longitude]);
  const lat = Math.max(-85.0511, Math.min(85.0511, view.lat));
  const lon = view.lon;
  const zoom = view.zoom;
  const tileCount = 2 ** zoom;
  const scale = 256 * tileCount;
  const centerX = ((lon + 180) / 360) * scale;
  const centerY = (1 - Math.asinh(Math.tan(lat * Math.PI / 180)) / Math.PI) / 2 * scale;
  const baseX = Math.floor(centerX / 256);
  const baseY = Math.floor(centerY / 256);
  function fromWorld(x, y) {
    const nextLat = Math.atan(Math.sinh(Math.PI * (1 - 2 * y / scale))) * 180 / Math.PI;
    let nextLon = x / scale * 360 - 180;
    nextLon = ((nextLon + 180) % 360 + 360) % 360 - 180;
    return { lat: nextLat, lon: nextLon };
  }
  function choose(event) {
    if (drag.current?.moved) { drag.current = null; return; }
    const rect = mapRef.current.getBoundingClientRect();
    const x = centerX + event.clientX - rect.left - rect.width / 2;
    const y = Math.max(0, Math.min(scale, centerY + event.clientY - rect.top - rect.height / 2));
    const point = fromWorld(x, y);
    setView((old) => ({ ...old, ...point }));
    onPick(point.lat, point.lon);
  }
  function pan(dx, dy) {
    const rect = mapRef.current.getBoundingClientRect();
    setView((old) => {
      const oldScale = 256 * (2 ** old.zoom);
      const x = ((old.lon + 180) / 360) * oldScale + dx * rect.width;
      const y = (1 - Math.asinh(Math.tan(Math.max(-85.0511, Math.min(85.0511, old.lat)) * Math.PI / 180)) / Math.PI) / 2 * oldScale + dy * rect.height;
      return { ...old, ...fromWorld(x, Math.max(0, Math.min(oldScale, y))) };
    });
  }
  function beginDrag(event) {
    if (event.target.closest(".map-controls")) return;
    event.currentTarget.setPointerCapture(event.pointerId);
    drag.current = { x: event.clientX, y: event.clientY, moved: false, startX: centerX, startY: centerY };
  }
  function moveDrag(event) {
    if (!drag.current) return;
    const dx = event.clientX - drag.current.x;
    const dy = event.clientY - drag.current.y;
    if (Math.abs(dx) + Math.abs(dy) > 4) drag.current.moved = true;
    if (!drag.current.moved) return;
    const point = fromWorld(drag.current.startX - dx, drag.current.startY - dy);
    setView((old) => ({ ...old, ...point }));
  }
  function endDrag(event) {
    if (!drag.current) return;
    if (event?.type === "pointercancel") { drag.current = null; return; }
    if (!drag.current.moved) drag.current = null;
  }
  const markerLat = Number(latitude);
  const markerLon = Number(longitude);
  const markerX = selected ? ((markerLon + 180) / 360) * scale - centerX : 0;
  const markerY = selected ? (1 - Math.asinh(Math.tan(Math.max(-85.0511, Math.min(85.0511, markerLat)) * Math.PI / 180)) / Math.PI) / 2 * scale - centerY : 0;
  return <div ref={mapRef} className="project-map" role="application" aria-label="Mapa interactivo. Arrastra para moverte y haz clic para elegir las coordenadas" onClick={choose} onPointerDown={beginDrag} onPointerMove={moveDrag} onPointerUp={endDrag} onPointerCancel={endDrag}>
    <div className="map-tiles" aria-hidden="true">{Array.from({ length: 25 }, (_, i) => {
      const rawX = baseX + (i % 5) - 2;
      const x = (rawX + tileCount) % tileCount;
      const y = Math.max(0, Math.min(tileCount - 1, baseY + Math.floor(i / 5) - 2));
      const offsetX = rawX * 256 - centerX;
      const offsetY = y * 256 - centerY;
      return <img key={`${rawX}-${y}`} draggable="false" alt="" src={`https://tile.openstreetmap.org/${zoom}/${x}/${y}.png`} style={{ left: `calc(50% + ${offsetX}px)`, top: `calc(50% + ${offsetY}px)` }} />;
    })}</div>
    {selected && <div className="map-marker" style={{ left: `calc(50% + ${markerX}px)`, top: `calc(50% + ${markerY}px)` }}><MapPin size={22} fill="white" /></div>}
    <div className="map-controls" onClick={(event) => event.stopPropagation()} onPointerDown={(event) => event.stopPropagation()}>
      <div className="map-pan-controls"><button type="button" aria-label="Mover mapa hacia arriba" onClick={() => pan(0, -0.35)}><ArrowUp size={14}/></button><button type="button" aria-label="Mover mapa a la izquierda" onClick={() => pan(-0.35, 0)}><ArrowLeft size={14}/></button><button type="button" aria-label="Mover mapa a la derecha" onClick={() => pan(0.35, 0)}><ArrowRight size={14}/></button><button type="button" aria-label="Mover mapa hacia abajo" onClick={() => pan(0, 0.35)}><ArrowDown size={14}/></button></div>
      <div className="map-zoom-controls"><button type="button" aria-label="Acercar mapa" disabled={zoom >= 17} onClick={() => setView((old) => ({ ...old, zoom: Math.min(17, old.zoom + 1) }))}><Plus size={15}/></button><button type="button" aria-label="Alejar mapa" disabled={zoom <= 4} onClick={() => setView((old) => ({ ...old, zoom: Math.max(4, old.zoom - 1) }))}><Minus size={15}/></button></div>
    </div>
    <span className="map-instruction">Haz clic para ubicar el proyecto</span>
    <span className="map-attribution">© OpenStreetMap contributors</span>
  </div>;
}

function ProjectsPage({ token, onNotice, onOpen }) {
  const empty = { name: "", description: "", project_type: "land", country: "", city: "", latitude: null, longitude: null, attachments: [] };
  const [projects, setProjects] = useState([]);
  const [form, setForm] = useState(empty);
  const [editing, setEditing] = useState(null);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [searching, setSearching] = useState(false);
  const [locationResults, setLocationResults] = useState([]);
  const [error, setError] = useState("");
  const fileInput = useRef(null);
  const auth = { Authorization: `Bearer ${token}` };
  async function request(url, options = {}) {
    const response = await fetch(url, { ...options, headers: { ...auth, ...(options.body ? { "Content-Type": "application/json" } : {}), ...options.headers } });
    if (response.status === 204) return null;
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "No se pudo completar la operación.");
    return data;
  }
  async function refresh() {
    try { setProjects(await request("/api/v1/projects")); }
    catch (e) { setError(e.message); }
  }
  useEffect(() => { refresh(); }, [token]);
  function start(project = null) {
    setEditing(project?.id || null);
    setForm(project ? { ...empty, ...project, country: project.country || "", city: project.city || "", attachments: project.attachments || [] } : { ...empty });
    setLocationResults([]);
    setError("");
    setOpen(true);
  }
  async function searchCity() {
    if (!form.country.trim() && !form.city.trim()) { setError("Escribe un país o una ciudad para buscar."); return; }
    setSearching(true); setError(""); setLocationResults([]);
    try {
      const params = new URLSearchParams({ country: form.country, city: form.city });
      const data = await request(`/api/v1/locations/search?${params}`);
      setLocationResults(data.results || []);
      if (!data.results?.length) setError("No encontramos esa ubicación. Prueba con otro nombre.");
      else chooseLocation(data.results[0]);
    } catch (e) { setError(e.message.toLowerCase().includes("too many attempts") ? "Espera un momento antes de volver a buscar." : e.message); }
    finally { setSearching(false); }
  }
  function chooseLocation(location) {
    setForm((f) => ({ ...f, country: location.country || f.country, city: location.city || f.city, latitude: Number(Number(location.latitude).toFixed(6)), longitude: Number(Number(location.longitude).toFixed(6)) }));
  }
  async function save(event) {
    event.preventDefault(); setBusy(true); setError("");
    try {
      await request(editing ? `/api/v1/projects/${editing}` : "/api/v1/projects", { method: editing ? "PATCH" : "POST", body: JSON.stringify(form) });
      setOpen(false); await refresh(); onNotice(editing ? "Proyecto actualizado." : "Proyecto creado.");
    } catch (e) { setError(e.message); }
    finally { setBusy(false); }
  }
  async function remove(project) {
    if (!window.confirm(`¿Seguro que quieres borrar “${project.name}”? Esta acción no se puede deshacer.`)) return;
    try { await request(`/api/v1/projects/${project.id}`, { method: "DELETE" }); await refresh(); onNotice("Proyecto eliminado."); }
    catch (e) { setError(e.message); }
  }
  async function attachFiles(files) {
    for (const file of Array.from(files)) {
      const extension = file.name.split(".").pop().toLowerCase();
      const mime = ({ pdf: "application/pdf", png: "image/png", jpg: "image/jpeg", jpeg: "image/jpeg", csv: "text/csv", xlsx: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" })[extension];
      if (!mime || file.size > 20 * 1024 * 1024) { setError(`${file.name}: usa PDF, PNG, JPG, CSV o XLSX de hasta 20 MB.`); continue; }
      const placeholder = { name: file.name, mime_type: mime, status: "uploading" };
      setForm((f) => ({ ...f, attachments: [...f.attachments, placeholder] }));
      try {
        if (!editing) throw new Error("Crea primero el proyecto y carga sus archivos desde su espacio de trabajo.");
        const presign = await request("/api/v1/files/presign", { method: "POST", body: JSON.stringify({ filename: file.name, mime_type: mime, category: "documents", project_id: editing }) });
        const put = await fetch(presign.upload_url, { method: "PUT", headers: { "Content-Type": mime }, body: file });
        if (!put.ok) throw new Error("No se pudo subir el archivo.");
        const complete = await request(`/api/v1/files/${presign.upload_id}/complete`, { method: "POST" });
        setForm((f) => ({ ...f, attachments: f.attachments.map((a) => a === placeholder ? { ...a, upload_id: presign.upload_id, status: complete.status || "pending" } : a) }));
      } catch (e) { setError(`${file.name}: ${e.message}`); }
    }
  }
  return <section className="projects-page">
    <div className="projects-topline"><div><div className="eyebrow">TERRA WORKSPACE / PORTAFOLIO</div><h1>Proyectos</h1><p>Organiza tus proyectos de tierras y sus documentos de referencia.</p></div><button className="button primary" onClick={() => start()}><Plus size={15}/> Nuevo proyecto</button></div>
    <div className="project-summary"><span><Layers size={17}/><strong>{projects.length}</strong> proyectos</span><span>Tipo disponible: <strong>Tierras</strong></span></div>
    {error && <div className="project-error" role="alert">{error}<button onClick={() => setError("")}><X size={14}/></button></div>}
    <div className="projects-table-wrap"><table className="projects-table"><thead><tr><th>PROYECTO</th><th>TIPO</th><th>UBICACIÓN</th><th>ARCHIVOS</th><th>ACTUALIZADO</th><th></th></tr></thead><tbody>
      {projects.length ? projects.map((p) => <tr key={p.id}><td><button className="project-open-link" onClick={() => onOpen(p)}><strong>{p.name}</strong><small>{p.description || "Sin descripción"}</small></button></td><td><span className="land-tag">Tierras</span></td><td>{[p.city, p.country].filter(Boolean).join(", ") || (p.latitude != null && p.longitude != null ? `${Number(p.latitude).toFixed(4)}, ${Number(p.longitude).toFixed(4)}` : "Sin ubicación")}</td><td>{p.attachments?.length || 0} archivos</td><td>{new Date(p.updated_at * 1000).toLocaleDateString("es-CO")}</td><td className="row-actions"><button title="Abrir espacio del proyecto" onClick={() => onOpen(p)}><MessageCircle size={15}/></button><button title="Editar proyecto" onClick={() => start(p)}><Pencil size={15}/></button><button title="Borrar proyecto" onClick={() => remove(p)}><Trash2 size={15}/></button></td></tr>) : <tr><td colSpan="6" className="projects-empty"><FolderOpen size={28}/><strong>Aún no hay proyectos</strong><span>Crea tu primer proyecto para empezar a organizar la información del sitio.</span><button className="button" onClick={() => start()}><Plus size={14}/> Crear proyecto</button></td></tr>}
    </tbody></table></div>
    {open && <div className="modal-backdrop project-modal-backdrop" onMouseDown={(e) => { if (e.target === e.currentTarget) setOpen(false); }}><form className="project-modal" onSubmit={save}>
      <div className="project-modal-head"><div><div className="eyebrow">DETALLES DEL PROYECTO</div><h2>{editing ? "Editar proyecto" : "Crear proyecto"}</h2></div><button type="button" className="icon-button" aria-label="Cerrar" onClick={() => setOpen(false)}><X size={19}/></button></div>
      <div className="project-form-body">
        <label>Nombre del proyecto<input autoFocus required maxLength="160" placeholder="Ej. Subestación norte" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })}/></label>
        <label>Descripción <span className="optional">Opcional</span><textarea rows="3" maxLength="5000" placeholder="Describe el propósito o alcance del proyecto" value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })}/></label>
        <label>Tipo de proyecto<select value={form.project_type} onChange={(e) => setForm({ ...form, project_type: e.target.value })}><option value="land">Tierras</option></select></label>
        <div className="form-label">Ubicación del proyecto <span className="optional">Todos los datos de ubicación son opcionales</span></div>
        <div className="location-search-grid"><label>País <span className="optional">Opcional</span><input maxLength="120" placeholder="Ej. Colombia" value={form.country} onChange={(e) => setForm({ ...form, country: e.target.value })}/></label><label>Ciudad <span className="optional">Opcional</span><input maxLength="120" placeholder="Ej. Bogotá" value={form.city} onChange={(e) => setForm({ ...form, city: e.target.value })}/></label><button type="button" className="button location-search-button" disabled={searching || (!form.country.trim() && !form.city.trim())} onClick={searchCity}><Search size={14}/>{searching ? "Buscando…" : "Buscar"}</button></div>
        {!!locationResults.length && <div className="location-search-results" role="status">{locationResults.length > 1 && <small>Resultados encontrados; puedes elegir otro:</small>}{locationResults.map((location, index) => <button key={`${location.latitude}-${location.longitude}`} type="button" className={Number(form.latitude) === Number(location.latitude) ? "selected" : ""} onClick={() => chooseLocation(location)}>{location.label}<MapPin size={13}/></button>)}</div>}
        <div className="map-optional-hint">Arrastra el mapa para explorar, usa los controles o haz clic para elegir las coordenadas.</div>
        <MapPicker latitude={form.latitude} longitude={form.longitude} onPick={(latitude, longitude) => setForm((f) => ({ ...f, latitude: Number(latitude.toFixed(6)), longitude: Number(longitude.toFixed(6)) }))}/>
        <div className="coordinate-fields"><label>Latitud<input type="number" step="any" min="-90" max="90" value={form.latitude ?? ""} onChange={(e) => setForm({ ...form, latitude: e.target.value === "" ? null : Number(e.target.value) })}/></label><label>Longitud<input type="number" step="any" min="-180" max="180" value={form.longitude ?? ""} onChange={(e) => setForm({ ...form, longitude: e.target.value === "" ? null : Number(e.target.value) })}/></label><span><MapPin size={13}/> Coordenadas WGS84</span></div>
        <div className="form-label">Archivos del proyecto <span className="optional">PDF, imágenes, CSV o XLSX</span></div><button type="button" className="project-file-drop" disabled={!editing} onClick={() => fileInput.current?.click()}><Paperclip size={17}/><span><strong>Adjuntar archivos</strong><small>{editing ? "Máximo 20 MB por archivo" : "Crea el proyecto para agregar archivos"}</small></span><Plus size={16}/></button><input ref={fileInput} hidden type="file" multiple accept=".pdf,.png,.jpg,.jpeg,.csv,.xlsx" onChange={(e) => { attachFiles(e.target.files); e.target.value = ""; }}/>
        {!!form.attachments.length && <div className="project-attachments">{form.attachments.map((a, i) => <span key={`${a.name}-${i}`}><File size={14}/>{a.name}<small>{a.status === "uploading" ? "Subiendo…" : a.status || "Adjunto"}</small><button type="button" aria-label={`Quitar ${a.name}`} onClick={() => setForm({ ...form, attachments: form.attachments.filter((_, index) => index !== i) })}><X size={13}/></button></span>)}</div>}
      </div>
      {error && <div className="project-modal-error" role="alert">{error}</div>}<div className="project-modal-actions"><button className="button" type="button" onClick={() => setOpen(false)}>Cancelar</button><button className="button primary" disabled={busy || form.attachments.some((a) => a.status === "uploading")}><Check size={14}/>{busy ? "Guardando…" : editing ? "Guardar cambios" : "Crear proyecto"}</button></div>
    </form></div>}
  </section>;
}

function ArtifactPanel({ fit = null, calculation = null, design = null }) {
  const p = design || { length_m: 40, width_m: 30, conductor_spacing_m: 5, rods_count: 12, burial_depth_m: 0.6 };
  const result = calculation?.result;
  return <aside className="panel artifact-side-panel"><div className="panel-heading"><div><Box size={17}/><h2>Artefacto de puesta a tierra</h2></div><span className="muted-label">{result ? "Calculado" : "Borrador"}</span></div>
    <div className="artifact-preview"><svg viewBox="0 0 260 190" role="img" aria-label={`Esquema preliminar de malla de ${p.length_m} por ${p.width_m} metros`}><rect x="20" y="20" width="220" height="150" rx="5" fill="#f1f8f5" stroke="#d9e8e1" strokeDasharray="5 4"/><g stroke="#438f80" strokeWidth="2">{[0,1,2,3,4].map(i=><line key={`v${i}`} x1={42+i*49} y1="36" x2={42+i*49} y2="154"/>)}{[0,1,2,3].map(i=><line key={`h${i}`} x1="42" y1={36+i*39} x2="238" y2={36+i*39}/>)}</g><g fill="#d28d43" stroke="white" strokeWidth="2">{Array.from({length:Math.min(Number(p.rods_count)||0,12)},(_,i)=>{const corners=[[42,36],[238,36],[238,154],[42,154]],c=corners[Math.floor(i/3)%4],n=i%3;return <circle key={i} cx={c[0]+(c[0]===42?1:-1)*(n*9)} cy={c[1]+(c[1]===36?1:-1)*(n*7)} r="4"/>})}</g><text x="130" y="184" textAnchor="middle" fill="#71877e" fontSize="10">Vista esquemática · no está a escala</text></svg></div>
    <div className="artifact-facts"><div><span>Geometría</span><strong>{p.length_m} × {p.width_m} m</strong></div><div><span>Separación</span><strong>{p.conductor_spacing_m} m</strong></div><div><span>Varillas</span><strong>{p.rods_count}</strong></div><div><span>Enterramiento</span><strong>{p.burial_depth_m} m</strong></div></div>
    <div className="artifact-status"><strong>Modelo de suelo</strong>{fit ? <span>{Number(fit.model.upper_resistivity_ohm_m).toFixed(1)} / {Number(fit.model.lower_resistivity_ohm_m).toFixed(1)} Ω·m · capa superior {Number(fit.model.upper_thickness_m).toFixed(2)} m</span> : <span className="no-information">Sin información: ajusta las mediciones para obtener las capas del suelo.</span>}</div>
    <div className="artifact-status"><strong>Verificación</strong>{result ? <span>{result.safety?.[0]?.status || "Resultado disponible"} · {Number(result.max_touch_v).toFixed(1)} V contacto · {Number(result.max_step_v).toFixed(1)} V paso</span> : <span className="no-information">Sin información: ejecuta el cálculo de seguridad para ver resultados.</span>}</div>
  </aside>;
}

function GroundingCalculations({ project, token, section }) {
  const [readings, setReadings] = useState([{ spacing_m: 1, apparent_resistivity_ohm_m: 100 }, { spacing_m: 2, apparent_resistivity_ohm_m: 110 }, { spacing_m: 4, apparent_resistivity_ohm_m: 160 }, { spacing_m: 8, apparent_resistivity_ohm_m: 230 }]);
  const [fit, setFit] = useState(null); const [calculation, setCalculation] = useState(null); const [busy, setBusy] = useState(false); const [error, setError] = useState("");
  const soilMaterials = [{name:"Grava",rho:3000,range:"1.000–10.000"},{name:"Arena",rho:500,range:"100–2.500"},{name:"Arcilla",rho:50,range:"1–100"},{name:"Limo",rho:150,range:"20–500"},{name:"Tierra vegetal",rho:100,range:"10–1.000"},{name:"Roca",rho:5000,range:"1.000–100.000"},{name:"Personalizado",rho:null,range:"definido por el usuario"}];
  function updateSoilLayer(index, key, value) {
    setFit((current) => {
      if (!current) return current;
      const soil_layers = current.soil_layers.map((layer, i) => i === index ? { ...layer, [key]: key === "resistivity_ohm_m" ? Number(value) : value } : layer);
      const model = { ...current.model, ...(index === 0 ? { upper_resistivity_ohm_m: soil_layers[0].resistivity_ohm_m } : { lower_resistivity_ohm_m: soil_layers[1].resistivity_ohm_m }) };
      return { ...current, soil_layers, model };
    });
  }
  const [design, setDesign] = useState({ name: `Diseño de tierras · ${project.name}`, length_m: 40, width_m: 30, burial_depth_m: 0.6, conductor_spacing_m: 5, rods_count: 12, rod_length_m: 2.4, current_a: 12500, clearing_time_s: 0.5, surface_resistivity_ohm_m: 3000, surface_thickness_m: 0.1, body_weight_kg: 50, split_factor: 1, x_over_r: "" });
  const auth = { Authorization: `Bearer ${token}` };
  const request = async (url, options = {}) => { const response = await fetch(url, { ...options, headers: { ...auth, ...(options.body ? { "Content-Type": "application/json" } : {}) } }); const data = response.status === 204 ? null : await response.json(); if (!response.ok) throw new Error(data?.detail || "No se pudo completar la operación."); return data; };
  const root = `/api/v1/projects/${project.id}/artefactos-diseno-tierras`;
  function setReading(i, key, value) { setReadings((rows) => rows.map((row, index) => index === i ? { ...row, [key]: value } : row)); }
  async function fitSoil() { setBusy(true); setError(""); try { setFit(await request(`${root}/mediciones-suelo/ajustar`, { method: "POST", body: JSON.stringify({ array: "wenner", measurements: readings.map((r) => ({ spacing_m: Number(r.spacing_m), apparent_resistivity_ohm_m: Number(r.apparent_resistivity_ohm_m) })) }) })); } catch (e) { setError(e.message); } finally { setBusy(false); } }
  async function calculate() {
    setBusy(true); setError(""); setCalculation(null);
    try {
      const artifact = await request(root, { method: "POST", body: JSON.stringify({ name: design.name, geometry: { length_m: Number(design.length_m), width_m: Number(design.width_m), burial_depth_m: Number(design.burial_depth_m), conductor_spacing_m: Number(design.conductor_spacing_m), rods_count: Number(design.rods_count), rod_length_m: Number(design.rod_length_m) }, soil_layers: fit.soil_layers, soil_measurements: { array: "wenner", measurements: readings.map((r) => ({ spacing_m: Number(r.spacing_m), apparent_resistivity_ohm_m: Number(r.apparent_resistivity_ohm_m) })) }, fault: { current_a: Number(design.current_a), clearing_time_s: Number(design.clearing_time_s), surface_resistivity_ohm_m: Number(design.surface_resistivity_ohm_m), surface_thickness_m: Number(design.surface_thickness_m), body_weight_kg: Number(design.body_weight_kg) } }) });
      const calculationParameters = { surface_spacing_m: 0.5, safety_standards: ["IEEE 80-2013"], fault_split: { split_factor: Number(design.split_factor), split_factor_origin: "Factor S_f ingresado por el usuario" } };
      if (design.x_over_r !== "") calculationParameters.x_over_r = Number(design.x_over_r);
      const queued = await request(`${root}/${artifact.artifact_id}/versions/${artifact.version}/calculos-potencial`, { method: "POST", body: JSON.stringify(calculationParameters) }); setCalculation(queued);
    } catch (e) { setError(e.message); setBusy(false); }
  }
  useEffect(() => { if (!calculation || !["pending", "running"].includes(calculation.status)) return undefined; const timer = setInterval(async () => { try { const latest = await request(`${root}/${calculation.artifact_id || ""}/calculos-potencial/${calculation.id}`); setCalculation(latest); if (!["pending", "running"].includes(latest.status)) setBusy(false); } catch (e) { setError(e.message); setBusy(false); } }, 1500); return () => clearInterval(timer); }, [calculation?.id, calculation?.status]);
  // Calculation records are scoped by artifact id; retain it from the newly created artifact.
  const num = (value, digits = 1) => Number(value).toLocaleString("es-CO", { maximumFractionDigits: digits });
  return <div className="grounding-calc-center">
    {section === "measurements" && <>
    <section className="panel calc-panel"><div className="panel-heading"><div><FileSpreadsheet size={17}/><h2>Mediciones de resistividad · Wenner</h2><details className="wenner-help"><summary aria-label="Ver esquema del método Wenner" title="¿Cómo se disponen los electrodos?"><CircleHelp size={15}/></summary><div className="wenner-tooltip"><strong>Arreglo Wenner</strong><svg viewBox="0 0 300 132" role="img" aria-label="Cuatro electrodos alineados y equidistantes: C1, P1, P2 y C2"><path d="M22 66H278" stroke="#b9cbc4" strokeWidth="2"/><path d="M52 27v51M118 40v38M184 40v38M250 27v51" stroke="#328a7c" strokeWidth="4" strokeLinecap="round"/><g fill="#40574e" fontSize="12" fontFamily="sans-serif" textAnchor="middle"><text x="52" y="18">C1</text><text x="118" y="31">P1</text><text x="184" y="31">P2</text><text x="250" y="18">C2</text></g><g stroke="#8b9f97" strokeWidth="1" fill="none"><path d="M52 94v8M118 94v8M52 99h66M118 94v8M184 94v8M118 99h66M184 94v8M250 94v8M184 99h66"/><path d="m55 97-3 2 3 2M115 97l3 2-3 2M121 97l-3 2 3 2M181 97l3 2-3 2M187 97l-3 2 3 2M247 97l3 2-3 2"/></g><text x="151" y="122" fill="#60766d" fontSize="11" fontFamily="sans-serif" textAnchor="middle">Misma separación a entre electrodos</text></svg><p>Se inyecta corriente por los electrodos exteriores (C1, C2) y se mide la diferencia de potencial entre los interiores (P1, P2).</p></div></details></div><span className="count">{readings.length} puntos</span></div><p className="calc-help"><strong>Valores de ejemplo:</strong> reemplázalos por las mediciones de campo. Ingresa el espaciamiento y la resistividad aparente para ajustar el modelo de suelo.</p>
      <div className="measurement-table"><div className="measurement-head"><span>Espaciamiento a (m)</span><span>Resistividad aparente (Ω·m)</span><span></span></div>{readings.map((r, i) => <div className="measurement-row" key={i}><input type="number" min="0.01" step="any" value={r.spacing_m} onChange={(e) => setReading(i, "spacing_m", e.target.value)} aria-label={`Espaciamiento lectura ${i + 1}`}/><input type="number" min="0.01" step="any" value={r.apparent_resistivity_ohm_m} onChange={(e) => setReading(i, "apparent_resistivity_ohm_m", e.target.value)} aria-label={`Resistividad lectura ${i + 1}`}/><button disabled={readings.length <= 4} title="Quitar lectura" onClick={() => setReadings((rows) => rows.filter((_, index) => index !== i))}><X size={15}/></button></div>)}</div>
      <div className="calc-actions"><button className="button" onClick={() => setReadings((rows) => [...rows, { spacing_m: 10, apparent_resistivity_ohm_m: 250 }])}><Plus size={14}/> Agregar medición</button><button className="button primary" disabled={busy} onClick={fitSoil}>{busy ? "Procesando…" : "Ajustar modelo de suelo"}</button></div>

    </section></>}
    {section === "soil" && <section className="panel calc-panel"><div className="panel-heading"><div><Layers size={17}/><h2>Modelo de suelos</h2></div>{fit && <span className="muted-label">2 capas</span>}</div><p className="calc-help">Revisa los valores ajustados y asigna un material conocido a cada capa. Los rangos son orientativos; usa mediciones del sitio para definir el modelo final.</p>{fit ? <div className="soil-fit-result"><div className="fit-title"><Check size={16}/> Modelo ajustado <span>RMS {num(fit.rms_error_percent)}%</span></div><div className="soil-material-list">{fit.soil_layers.map((layer, i) => <div className="soil-material-row" key={i}><label>Capa {i + 1}<select aria-label={`Material de la capa ${i + 1}`} value={layer.material || "Personalizado"} onChange={(e) => { const material = soilMaterials.find((item) => item.name === e.target.value); updateSoilLayer(i, "material", material.name); if (material.rho) updateSoilLayer(i, "resistivity_ohm_m", material.rho); }}><option value="Personalizado">Personalizado</option>{soilMaterials.filter((item) => item.rho).map((item) => <option key={item.name} value={item.name}>{item.name} · {item.range} Ω·m</option>)}</select></label><label>Resistividad (Ω·m)<input type="number" min="0.01" step="any" value={layer.resistivity_ohm_m} onChange={(e) => updateSoilLayer(i, "resistivity_ohm_m", e.target.value)}/></label><small>Rango típico: {soilMaterials.find((item) => item.name === layer.material)?.range || "variable"} Ω·m</small></div>)}</div>{fit.warnings?.map((warning) => <small key={warning}>{warning}</small>)}</div> : <div className="soil-fit-result"><strong>Sin modelo de suelo</strong><p>Ajusta las mediciones Wenner para crear un modelo y configurar sus capas.</p></div>}</section>}
    {section === "safety" && <section className="panel calc-panel"><div className="panel-heading"><div><ShieldCheck size={17}/><h2>Verificación de seguridad</h2></div><span className="muted-label">IEEE 80-2013</span></div><p className="calc-help">Define la geometría y el escenario de falla para verificar tensiones de contacto y paso.</p><div className="calc-form-grid">{[["Largo de malla (m)","length_m"],["Ancho de malla (m)","width_m"],["Profundidad (m)","burial_depth_m"],["Separación (m)","conductor_spacing_m"],["Varillas","rods_count"],["Longitud varilla (m)","rod_length_m"],["Corriente de falla (A)","current_a"],["Despeje (s)","clearing_time_s"],["Resistividad superficial (Ω·m)","surface_resistivity_ohm_m"],["Espesor superficial (m)","surface_thickness_m"],["Factor de reparto S_f (0–1)","split_factor"],["Relación X/R (opcional)","x_over_r"]].map(([label,key]) => <label key={key}>{label}<input type="number" min={key === "split_factor" ? "0.001" : "0"} max={key === "split_factor" ? "1" : undefined} step="any" value={design[key]} onChange={(e) => setDesign({ ...design, [key]: e.target.value })}/></label>)}</div><button className="button primary calc-run" disabled={!fit || busy} onClick={calculate}><Activity size={15}/>{busy ? "Calculando…" : "Calcular tensiones y seguridad"}</button>{calculation?.result && <div className="soil-fit-result"><strong>{calculation.result.safety?.[0]?.status || "Resultado disponible"}</strong><p>Contacto {num(calculation.result.max_touch_v)} V · Paso {num(calculation.result.max_step_v)} V · GPR {num(calculation.result.gpr_v)} V</p></div>}</section>}
    {error && <div className="project-error calc-error" role="alert">{error}<button onClick={() => setError("")}><X size={14}/></button></div>}
  </div>;
}

function ProjectChatWorkspace({ project, token, onBack, onNotice }) {
  const [leftSection, setLeftSection] = useState("files");
  const [rightSection, setRightSection] = useState("artifact");
  const [files, setFiles] = useState([]);
  const [conversation, setConversation] = useState(null);
  const [messages, setMessages] = useState([]);
  const [cancelled, setCancelled] = useState(() => new Set());
  const [attachments, setAttachments] = useState([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const fileInput = useRef(null);
  const messageBox = useRef(null);
  const auth = { Authorization: `Bearer ${token}` };
  const request = async (url, options = {}) => {
    const response = await fetch(url, { ...options, headers: { ...auth, ...(options.body ? { "Content-Type": "application/json" } : {}), ...options.headers } });
    const data = response.status === 204 ? null : await response.json();
    if (!response.ok) throw new Error(data?.detail || "No se pudo completar la operación.");
    return data;
  };
  async function reloadFiles() { setFiles(await request(`/api/v1/projects/${project.id}/files`)); }
  async function reloadMessages(id = conversation?.id) {
    if (!id) return;
    setMessages(await request(`/api/v1/conversations/${id}/messages/first?limit=50`));
  }
  useEffect(() => {
    let live = true;
    (async () => {
      try {
        const [existingFiles, convs] = await Promise.all([
          request(`/api/v1/projects/${project.id}/files`),
          request(`/api/v1/projects/${project.id}/conversations`),
        ]);
        if (!live) return;
        setFiles(existingFiles);
        const current = convs[0] || await request(`/api/v1/projects/${project.id}/conversations`, { method: "POST", body: JSON.stringify({ title: `Refinamiento · ${project.name}` }) });
        if (!live) return;
        setConversation(current);
        setMessages(await request(`/api/v1/conversations/${current.id}/messages/first?limit=50`));
      } catch (e) { if (live) setError(e.message); }
    })();
    return () => { live = false; };
  }, [project.id]);
  useEffect(() => {
    messageBox.current?.scrollTo({ top: messageBox.current.scrollHeight, behavior: "smooth" });
    if (!conversation) return undefined;
    const pending = messages.some((m) => ["pending", "processing"].includes(m.status) && !cancelled.has(m.id));
    if (!pending) return undefined;
    const timer = setInterval(() => reloadMessages(), 1500);
    return () => clearInterval(timer);
  }, [messages, conversation, cancelled]);
  async function uploadFile(file) {
    const extension = file.name.split(".").pop().toLowerCase();
    const mime = mimeByExtension[extension] || file.type;
    if (!uploadableMimeTypes.has(mime) || file.size > 20 * 1024 * 1024) throw new Error(`${file.name}: usa PDF, PNG, JPG, CSV o XLSX de hasta 20 MB.`);
    const placeholder = { id: crypto.randomUUID(), filename: file.name, status: "uploading" };
    setAttachments((current) => [...current, placeholder]);
    const update = (changes) => setAttachments((current) => current.map((a) => a.id === placeholder.id ? { ...a, ...changes } : a));
    try {
      const presign = await request("/api/v1/files/presign", { method: "POST", body: JSON.stringify({ filename: file.name, mime_type: mime, category: "documents", project_id: project.id }) });
      const put = await fetch(presign.upload_url, { method: "PUT", headers: { "Content-Type": mime }, body: file });
      if (!put.ok) throw new Error("No se pudo cargar el archivo al almacenamiento.");
      await request(`/api/v1/files/${presign.upload_id}/complete`, { method: "POST" });
      update({ uploadId: presign.upload_id, status: "scanning", mime_type: mime });
      for (let attempt = 0; attempt < 180; attempt += 1) {
        const state = await request(`/api/v1/files/${presign.upload_id}`);
        update({ status: state.status });
        if (state.status === "available") { await reloadFiles(); return; }
        if (["rejected", "failed"].includes(state.status)) throw new Error("El archivo no superó el procesamiento de seguridad.");
        await new Promise((resolve) => setTimeout(resolve, 1500));
      }
      throw new Error("El análisis del archivo sigue en curso. Vuelve a intentarlo en un momento.");
    } catch (e) { update({ status: "failed", error: e.message }); throw e; }
  }
  async function addFiles(fileList) {
    for (const file of Array.from(fileList)) {
      try { await uploadFile(file); }
      catch (e) { setError(e.message); onNotice(e.message); }
    }
  }
  async function sendMessage() {
    const text = draft.trim();
    const ready = attachments.filter((a) => a.uploadId && a.status === "available");
    if ((!text && !ready.length) || busy) return;
    setBusy(true); setError("");
    try {
      let active = conversation;
      if (!active) {
        active = await request(`/api/v1/projects/${project.id}/conversations`, { method: "POST", body: JSON.stringify({ title: `Refinamiento · ${project.name}` }) });
        setConversation(active);
      }
      await request(`/api/v1/conversations/${active.id}/messages`, {
        method: "POST",
        body: JSON.stringify({ text, type: ready.length ? (ready.every((a) => a.mime_type.startsWith("image/")) ? "image" : "file") : "text", contents: ready.map((a) => ({ upload_id: a.uploadId })) }),
      });
      setDraft(""); setAttachments([]);
      await reloadMessages(active.id);
    } catch (e) { setError(e.message); }
    finally { setBusy(false); }
  }
  async function cancel(message) {
    try { await request(`/api/v1/messages/${message.id}/cancel`, { method: "POST" }); setCancelled((current) => new Set(current).add(message.id)); await reloadMessages(); }
    catch (e) { setError(e.message); }
  }
  async function loadOlder() {
    if (!messages.length || !conversation) return;
    try {
      const node = messageBox.current;
      const previousHeight = node?.scrollHeight || 0;
      const older = await request(`/api/v1/conversations/${conversation.id}/messages/cursor?before=${messages[0].id}&limit=30`);
      setMessages((current) => [...older, ...current]);
      requestAnimationFrame(() => { if (node) node.scrollTop = node.scrollHeight - previousHeight; });
    } catch (e) { if (!e.message.includes("404")) setError(e.message); }
  }
  return <main className="project-chat-workspace">
    <header className="project-chat-topbar"><div className="breadcrumbs"><span className="wordmark">terra<span> / </span></span><button className="project-parent" onClick={onBack}>Proyectos <ChevronRight size={14}/></button><span className="project-name"><span className="project-dot"/>{project.name}</span><span className="project-badge">SPAT</span></div><button className="button" onClick={onBack}><Layers size={14}/> Todos los proyectos</button></header>
    <div className="project-chat-heading"><div><div className="eyebrow">ESPACIO DEL PROYECTO</div><h1>{project.name}</h1><p>{project.description || "Archivos de entrada y conversación para refinar los artefactos del proyecto."}</p></div><span className="project-chat-live"><i/> Proyecto activo</span></div>
    {error && <div className="project-error" role="alert">{error}<button onClick={() => setError("")}><X size={14}/></button></div>}
    <div className="project-three-col-grid">
    <aside className="project-left-column"><div className="project-view-tabs" role="tablist" aria-label="Secciones del proyecto"><button role="tab" aria-selected={leftSection === "files"} className={leftSection === "files" ? "active" : ""} onClick={() => setLeftSection("files")}><Layers size={15}/> Archivos</button><button role="tab" aria-selected={leftSection === "measurements"} className={leftSection === "measurements" ? "active" : ""} onClick={() => setLeftSection("measurements")}><FileSpreadsheet size={15}/> Mediciones</button><button role="tab" aria-selected={leftSection === "soil"} className={leftSection === "soil" ? "active" : ""} onClick={() => setLeftSection("soil")}><Network size={15}/> Modelo suelo</button><button role="tab" aria-selected={leftSection === "safety"} className={leftSection === "safety" ? "active" : ""} onClick={() => setLeftSection("safety")}><ShieldCheck size={15}/> Seguridad</button></div>{leftSection === "files" ? <aside className="panel project-files-panel"><div className="panel-heading"><div><Layers size={17}/><h2>Archivos del proyecto</h2><span className="count">{files.length}</span></div><button className="icon-button" title="Cargar archivos" onClick={() => fileInput.current?.click()}><Plus size={17}/></button></div><div className="project-files-list">{files.length ? files.map((f) => <div className="project-file-row" key={f.upload_id}><span className={`asset-icon ${f.mime_type.startsWith("image/") ? "image" : "document"}`}>{f.mime_type.startsWith("image/") ? <FileImage size={18}/> : <File size={18}/>}</span><span><strong>{f.filename}</strong><small>{f.ocr_needs_review ? `Revisión OCR recomendada · ${Number(f.ocr_confidence ?? 0).toFixed(0)}% de confianza` : uploadStatusLabels[f.status] || f.status}</small></span><i className={`asset-dot ${f.status === "failed" || f.status === "rejected" || f.ocr_needs_review ? "error" : f.status !== "available" ? "pending" : ""}`}/></div>) : <div className="empty-assets">Los archivos cargados para este proyecto aparecerán aquí.</div>}</div><button className="upload-area" onClick={() => fileInput.current?.click()}><span><Plus size={16}/></span><strong>Agregar archivos</strong><small>PDF, PNG, JPG, CSV o XLSX · máximo 20 MB</small></button><input ref={fileInput} hidden type="file" multiple accept=".pdf,.png,.jpg,.jpeg,.csv,.xlsx" onChange={(e) => { addFiles(e.target.files); e.target.value = ""; }}/><div className="project-chat-files-note"><ShieldCheck size={16}/> Todo archivo pasa por cuarentena y análisis antes de adjuntarse al chat.</div></aside> : <GroundingCalculations project={project} token={token} section={leftSection}/>}</aside>
    <div className="project-center-column">
      <section className="panel project-conversation-panel"><div className="panel-heading"><div><Sparkles size={17}/><h2>Refinamiento del artefacto</h2></div><span className="project-chat-live"><i/> Chat listo</span></div><div className="project-chat-messages" ref={messageBox}><button className="load-older" onClick={loadOlder}>Cargar mensajes anteriores</button>{messages.length ? messages.map((m) => <article className={`message ${m.source === "user" ? "user" : "assistant"}`} key={m.id}><div className={`message-avatar ${m.source === "user" ? "user" : "assistant"}`}>{m.source === "user" ? `${project.name[0] || "U"}` : <Zap size={15}/>}</div><div className="message-content"><div className="message-author">{m.source === "user" ? "Tú" : m.source === "notification" ? "Notificación" : "Terra"}<span>{new Date(m.created_at * 1000).toLocaleTimeString("es-CO", { hour: "2-digit", minute: "2-digit" })}</span></div>{m.text && <p>{m.text}</p>}{m.contents?.map((c) => <div className="chat-file" key={c.id}>{c.format === "image" ? <FileImage size={13}/> : <Paperclip size={13}/>} {c.filename}</div>)}{["pending", "processing"].includes(m.status) && <div className="chat-processing">{m.status === "pending" ? "En cola…" : "Procesando solicitud…"}<button onClick={() => cancel(m)}>Cancelar</button></div>}</div></article>) : <div className="project-chat-empty"><span><Sparkles size={20}/></span><strong>Inicia el refinamiento</strong><p>Describe qué artefacto quieres ajustar o adjunta archivos de referencia del proyecto.</p></div>}</div><div className="project-chat-composer"><div className="attachment-chips">{attachments.map((a) => <span key={a.id}><Paperclip size={12}/>{a.filename}<small>{a.status === "available" ? "Listo" : a.status === "failed" ? "Error" : "Analizando…"}</small><button aria-label={`Quitar ${a.filename}`} onClick={() => setAttachments((xs) => xs.filter((x) => x.id !== a.id))}><X size={12}/></button></span>)}</div><textarea aria-label="Mensaje para el chat del proyecto" placeholder="Describe el refinamiento que necesitas…" value={draft} onChange={(e) => setDraft(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendMessage(); } }}/><div className="project-composer-tools"><button className="icon-button" title="Adjuntar imágenes o archivos" onClick={() => fileInput.current?.click()}><Paperclip size={17}/></button><span>Los archivos se cargan y analizan antes de enviar</span><button className="send-button" disabled={busy || (!draft.trim() && !attachments.some((a) => a.status === "available"))} onClick={sendMessage}>{busy ? <Activity size={17}/> : <ArrowUp size={18}/>}</button></div></div></section>
    </div>
    <div className="artifact-column"><div className="artifact-view-tabs" role="tablist" aria-label="Vista del artefacto"><button role="tab" aria-selected={rightSection === "artifact"} className={rightSection === "artifact" ? "active" : ""} onClick={() => setRightSection("artifact")}><Box size={14}/> Artefacto</button><button role="tab" aria-selected={rightSection === "results"} className={rightSection === "results" ? "active" : ""} onClick={() => setRightSection("results")}><Activity size={14}/> Resultados</button></div>{rightSection === "artifact" ? <ArtifactPanel/> : <div className="artifact-chat-results panel"><div className="panel-heading"><div><Activity size={16}/><h2>Resultados</h2></div></div><p className="no-information">Sin información: ejecuta una verificación de seguridad para ver los resultados del artefacto.</p></div>}</div>
    </div>
  </main>;
}

function App() {
  const [token, setToken] = useState(() => localStorage.getItem("spat_access_token"));
  const [user, setUser] = useState(null);
  const [authChecking, setAuthChecking] = useState(true);
  const [parameters, setParameters] = useState(defaults);
  const [assets, setAssets] = useState([]);
  const [messages, setMessages] = useState(initialMessages);
  const [draft, setDraft] = useState("");
  const [attachments, setAttachments] = useState([]);
  const [selected, setSelected] = useState(null);
  const [assetView, setAssetView] = useState("list");
  const [activeAsset, setActiveAsset] = useState(null);
  const [notice, setNotice] = useState("");
  const [recording, setRecording] = useState(false);
  const [versions, setVersions] = useState([
    { name: "Initial design", parameters: defaults },
  ]);
  const [history, setHistory] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const [tab, setTab] = useState("workspace");
  const [activeProject, setActiveProject] = useState(null);
  const fileRef = useRef();
  const recognitionRef = useRef();
  const chatEnd = useRef();
  useEffect(() => {
    let cancelled = false;
    if (!token) {
      localStorage.removeItem("spat_access_token");
      if (window.location.pathname !== "/login") window.history.replaceState({}, "", "/login");
      setAuthChecking(false);
      return () => { cancelled = true; };
    }
    fetch("/api/v1/auth/me", { headers: { Authorization: `Bearer ${token}` } })
      .then(async (response) => {
        if (!response.ok) throw new Error("Session expired");
        return response.json();
      })
      .then((profile) => {
        if (cancelled) return;
        setUser(profile);
        if (window.location.pathname === "/login") window.history.replaceState({}, "", "/");
      })
      .catch(() => {
        if (cancelled) return;
        localStorage.removeItem("spat_access_token");
        setToken(null);
        setUser(null);
        if (window.location.pathname !== "/login") window.history.replaceState({}, "", "/login");
      })
      .finally(() => { if (!cancelled) setAuthChecking(false); });
    return () => { cancelled = true; };
  }, [token]);
  useEffect(() => {
    if (!token || !user) return undefined;
    let live = true;
    async function syncRoute() {
      const match = window.location.pathname.match(/^\/project\/([^/]+)\/?$/);
      if (match) {
        try {
          const response = await fetch(`/api/v1/projects/${encodeURIComponent(match[1])}`, { headers: { Authorization: `Bearer ${token}` } });
          const project = await response.json();
          if (!response.ok) throw new Error(project.detail || "Proyecto no encontrado.");
          if (live) { setActiveProject(project); setTab("workspace"); }
        } catch (error) {
          if (live) { setActiveProject(null); setTab("projects"); setNotice(error.message); }
        }
      } else if (window.location.pathname === "/projects") {
        setActiveProject(null); setTab("projects");
      } else {
        setActiveProject(null); setTab("workspace");
      }
    }
    syncRoute();
    window.addEventListener("popstate", syncRoute);
    return () => { live = false; window.removeEventListener("popstate", syncRoute); };
  }, [token, user]);
  function openProject(project) {
    window.history.pushState({}, "", `/project/${encodeURIComponent(project.id)}`);
    setActiveProject(project);
    setTab("workspace");
  }
  function showProjects() {
    window.history.pushState({}, "", "/projects");
    setActiveProject(null);
    setTab("projects");
  }
  function acceptToken(accessToken) {
    localStorage.setItem("spat_access_token", accessToken);
    setAuthChecking(true);
    setToken(accessToken);
  }
  function logout() {
    localStorage.removeItem("spat_access_token");
    setToken(null);
    setUser(null);
  }
  useEffect(() => {
    chatEnd.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [messages]);
  useEffect(() => {
    if (notice) {
      const id = setTimeout(() => setNotice(""), 5000);
      return () => clearTimeout(id);
    }
  }, [notice]);
  useEffect(() => () => recognitionRef.current?.abort(), []);
  const cableLength =
    (Math.ceil(parameters.width / parameters.spacing) + 1) * parameters.length +
    (Math.ceil(parameters.length / parameters.spacing) + 1) * parameters.width;
  function update(key, value) {
    const n = Number(value);
    if (Number.isFinite(n) && n > 0 && n <= 1000000) {
      const bounded = key === "rods" ? Math.min(100, Math.floor(n)) : n;
      setParameters((p) => ({ ...p, [key]: bounded }));
      if (key === "rods") setSelected(null);
    }
  }
  function setUploadState(id, patch) {
    setAssets((current) => current.map((asset) => asset.id === id ? { ...asset, ...patch } : asset));
    setAttachments((current) => current.map((asset) => asset.id === id ? { ...asset, ...patch } : asset));
  }
  async function uploadFile(file, asset) {
    const authHeaders = { Authorization: `Bearer ${token}` };
    try {
      const presignResponse = await fetch("/api/v1/files/presign", {
        method: "POST",
        headers: { ...authHeaders, "Content-Type": "application/json" },
        body: JSON.stringify({ filename: file.name, mime_type: asset.mimeType, category: "documents" }),
      });
      const presign = await presignResponse.json();
      if (!presignResponse.ok) throw new Error(presign.detail || "Could not prepare the upload.");

      const putResponse = await fetch(presign.upload_url, {
        method: "PUT",
        headers: { "Content-Type": asset.mimeType },
        body: file,
      });
      if (!putResponse.ok) throw new Error("MinIO could not accept the file. Check the upload URL and CORS configuration.");

      const completeResponse = await fetch(`/api/v1/files/${presign.upload_id}/complete`, {
        method: "POST",
        headers: authHeaders,
      });
      const completion = await completeResponse.json();
      if (!completeResponse.ok) throw new Error(completion.detail || "The processing task could not be queued.");
      setUploadState(asset.id, { uploadId: presign.upload_id, status: completion.status || "pending" });

      for (let attempt = 0; attempt < 180; attempt += 1) {
        const statusResponse = await fetch(`/api/v1/files/${presign.upload_id}`, { headers: authHeaders });
        const result = await statusResponse.json();
        if (!statusResponse.ok) throw new Error(result.detail || "Could not read the processing status.");
        setUploadState(asset.id, { status: result.status });
        if (["available", "rejected", "failed"].includes(result.status)) return;
        await new Promise((resolve) => setTimeout(resolve, 2000));
      }
      setUploadState(asset.id, { status: "failed" });
    } catch (error) {
      setUploadState(asset.id, { status: "failed", error: error.message });
      setNotice(`${file.name}: ${error.message}`);
    }
  }
  function addFiles(files) {
    Array.from(files).forEach((file) => {
      if (file.size > 20 * 1024 * 1024) {
        setNotice(`${file.name}: the maximum upload size is 20 MB.`);
        return;
      }
      const extension = file.name.includes(".") ? file.name.split(".").pop().toLowerCase() : "";
      const mimeType = mimeByExtension[extension] || file.type;
      if (!uploadableMimeTypes.has(mimeType)) {
        setNotice(`${file.name}: use PDF, PNG, JPG, CSV or XLSX files.`);
        return;
      }
      const id = crypto.randomUUID();
      const asset = {
        id,
        name: file.name,
        detail: `${(file.size / 1024).toFixed(0)} KB · ${uploadStatusLabels.uploading}`,
        type: mimeType.startsWith("image/") ? "image" : mimeType.includes("spreadsheet") ? "soil" : "document",
        mimeType,
        status: "uploading",
      };
      setAssets((current) => [asset, ...current]);
      setAttachments((current) => [...current, asset]);
      setActiveAsset(id);
      uploadFile(file, asset);
    });
  }
  function send(text = draft) {
    if (!text.trim() && !attachments.length) return;
    setMessages((m) => [
      ...m,
      {
        role: "user",
        text: text.trim(),
        context:
          selected === null
            ? null
            : `Ground rod R-${String(selected + 1).padStart(2, "0")}`,
        files: attachments.map((a) => a.name),
      },
      {
        role: "assistant",
        text: "Your request has been added to this design conversation. This prototype does not yet run AI or engineering calculations. You can edit the design parameters in the refinement panel and save a new version.",
        suggestion: true,
      },
    ]);
    setAttachments([]);
    setDraft("");
  }
  function voice() {
    if (recording) {
      recognitionRef.current?.stop();
      return;
    }
    const Speech = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!Speech) {
      setNotice(
        "Voice transcription is not supported in this browser. Try Chrome over localhost or HTTPS.",
      );
      return;
    }
    const r = new Speech();
    r.lang = "en-US";
    r.interimResults = false;
    r.onresult = (e) =>
      setDraft((d) => `${d} ${e.results[0][0].transcript}`.trim());
    r.onerror = () => {
      setRecording(false);
      setNotice(
        "Microphone unavailable or permission denied. You can still type your message.",
      );
    };
    r.onend = () => setRecording(false);
    recognitionRef.current = r;
    try {
      r.start();
      setRecording(true);
    } catch {
      setNotice("Could not start the microphone.");
    }
  }
  function save() {
    setVersions((v) => [
      ...v,
      {
        name: `Design revision ${v.length + 1}`,
        parameters: { ...parameters },
      },
    ]);
    setNotice("Design version saved for this session.");
  }
  const field = (label, key, unit, step = 1) => (
    <label className="parameter-field">
      <span>{label}</span>
      <div>
        <input
          aria-label={label}
          type="number"
          min={step}
          step={step}
          value={parameters[key]}
          onChange={(e) => update(key, e.target.value)}
        />
        <span>{unit}</span>
      </div>
    </label>
  );
  if (authChecking) return <main className="login-page"><div className="login-loading">Loading your workspace…</div></main>;
  if (!token || !user) return <Login onLogin={acceptToken} />;
  return (
    <div className="app-shell">
      <nav className="rail" aria-label="Main navigation">
        <a className="brand" href="#" aria-label="Terra home">
          <Zap size={23} fill="currentColor" />
        </a>
        <div className="rail-top">
          <IconButton
            title="Design workspace"
            className={`rail-button ${tab === "workspace" ? "active" : ""}`}
            onClick={() => setTab("workspace")}
          >
            <LayoutGrid size={21} />
          </IconButton>
          <IconButton
            title="Project assets"
            className={`rail-button ${tab === "assets" ? "active" : ""}`}
            onClick={() => {
              setTab("assets");
              setAssetView("list");
            }}
          >
            <FolderOpen size={21} />
          </IconButton>
          <IconButton
            title="Project management"
            aria-label="Proyectos"
            className={`rail-button ${tab === "projects" ? "active" : ""}`}
            onClick={showProjects}
          >
            <Layers size={21} />
          </IconButton>
          <IconButton
            title="Version history"
            className="rail-button"
            onClick={() => setHistory(true)}
          >
            <History size={21} />
          </IconButton>
        </div>
        <div className="rail-bottom">
          <IconButton
            title="Workspace help"
            onClick={() =>
              setNotice(
                "Attach files in chat, select mesh rods, edit parameters, then save a version. All changes are session-only.",
              )
            }
          >
            <CircleHelp size={20} />
          </IconButton>
          <button className="avatar" title={`${user.email} · ${user.roles.join(", ")}. Sign out`} onClick={logout}>{`${user.first_name?.[0] || "U"}${user.last_name?.[0] || ""}`.toUpperCase()}</button>
        </div>
      </nav>
      {tab === "projects" ? <ProjectsPage token={token} onNotice={setNotice} onOpen={openProject} /> : activeProject ? <ProjectChatWorkspace project={activeProject} token={token} onBack={showProjects} onNotice={setNotice} /> : <div className="workspace">
        <header className="project-bar">
          <div className="breadcrumbs">
            <span className="wordmark">
              terra<span> / </span>
            </span>
            <span className="project-parent">
              Projects <ChevronRight size={14} />
            </span>
            <button
              className="project-name"
              onClick={() =>
                setNotice(
                  "You are working in the North substation demo project.",
                )
              }
            >
              <span className="project-dot" />
              North substation
              <ChevronDown size={14} />
            </button>
            <span className="project-badge">SPAT</span>
          </div>
          <div className="header-actions">
            <span className="session-status">
              <span />
              Local session
            </span>
            <button className="button" onClick={() => setHistory(true)}>
              <History size={14} />
              History
            </button>
            <button
              className="button primary"
              onClick={() =>
                download(
                  "north-substation.json",
                  JSON.stringify(
                    {
                      schemaVersion: 1,
                      parameters,
                      assets,
                      versions,
                      status: "unvalidated_demo",
                    },
                    null,
                    2,
                  ),
                )
              }
            >
              <ArrowDownToLine size={14} />
              Export design
            </button>
          </div>
        </header>
        <div className="workspace-heading">
          <div>
            <div className="eyebrow">DESIGN WORKSPACE</div>
            <h1>A solid foundation, refined together.</h1>
            <p>Bring your inputs. Shape your design. Explore every detail.</p>
          </div>
          <div className="workspace-label">
            <span className="green-dot" />
            Draft design
            <span className="divider" />
            IEEE 80 workflow
          </div>
        </div>
        <main className="columns">
          <aside
            className={`assets-panel panel ${tab === "assets" ? "highlight-panel" : ""}`}
          >
            <div className="panel-heading">
              <div>
                <Layers size={17} />
                <h2>Project assets</h2>
                <span className="count">{assets.length}</span>
              </div>
              <IconButton
                title="Upload assets"
                onClick={() => fileRef.current.click()}
              >
                <Plus size={17} />
              </IconButton>
            </div>
            <div className="segmented">
              <button
                className={assetView === "list" ? "selected" : ""}
                onClick={() => setAssetView("list")}
              >
                <FolderOpen size={13} />
                Files
              </button>
              <button
                className={assetView === "graph" ? "selected" : ""}
                onClick={() => setAssetView("graph")}
              >
                <Network size={13} />
                Graph
              </button>
            </div>
            <div className="assets-body">
              <div className="small-label">
                DESIGN INPUTS <span>{assets.length}</span>
              </div>
              {assetView === "list" ? (
                <div className="asset-list">
                  {assets.length === 0 && (
                    <div className="empty-assets">No files yet. Upload a project document to start processing.</div>
                  )}
                  {assets.map((a) => {
                    const I =
                      a.type === "soil"
                        ? FileSpreadsheet
                        : a.type === "image"
                          ? FileImage
                          : a.type === "cad"
                            ? Box
                            : File;
                    return (
                      <button
                        key={a.id}
                        className={`asset ${activeAsset === a.id ? "selected" : ""}`}
                        onClick={() => {
                          setActiveAsset(a.id);
                          setNotice(
                            `${a.name}: ${a.error || uploadStatusLabels[a.status] || a.detail}`,
                          );
                        }}
                      >
                        <span className={`asset-icon ${a.type}`}>
                          <I size={19} />
                        </span>
                        <span>
                          <strong>{a.name}</strong>
                          <small>{a.error || uploadStatusLabels[a.status] || a.detail}</small>
                        </span>
                        <span className={`asset-dot ${a.status === "failed" || a.status === "rejected" ? "error" : a.status !== "available" ? "pending" : ""}`} />
                      </button>
                    );
                  })}
                </div>
              ) : (
                <div className="asset-graph">
                  {assets.length ? (
                    <>
                      <div className="graph-flow">
                        <span>Uploaded documents</span><ChevronRight size={13} />
                        <span>Celery extraction</span><ChevronRight size={13} />
                        <span>Neo4j graph</span>
                      </div>
                      <small>{assets.filter((asset) => asset.status === "available").length} of {assets.length} files processed</small>
                    </>
                  ) : (
                    <small>Upload a file to start the processing workflow.</small>
                  )}
                </div>
              )}
              <button
                className="upload-area"
                onClick={() => fileRef.current.click()}
                onDragOver={(e) => e.preventDefault()}
                onDrop={(e) => {
                  e.preventDefault();
                  addFiles(e.dataTransfer.files);
                }}
              >
                <span>
                  <Plus size={16} />
                </span>
                <strong>Add files to process</strong>
                <small>PDF, PNG, JPG, CSV or XLSX · up to 20 MB</small>
              </button>
              <div className="small-label output-label">
                GENERATED ARTIFACTS
              </div>
              <button
                className="artifact-file"
                onClick={() => setExpanded(true)}
              >
                <span className="artifact-icon">
                  <LayoutGrid size={17} />
                </span>
                <div>
                  <strong>Grounding design</strong>
                  <small>
                    Live artifact <span>· v{versions.length}</span>
                  </small>
                </div>
                <ChevronRight size={14} />
              </button>
            </div>
            <div className="asset-footer">
              <ShieldCheck size={17} />
              <p>
                Your inputs, connected.
                <br />
                <span>Keep the context behind every decision.</span>
              </p>
            </div>
          </aside>
          <section className="chat-panel panel">
            <div className="panel-heading">
              <div>
                <Sparkles size={17} />
                <h2>Design assistant</h2>
              </div>
              <span className="demo-badge">Demo mode</span>
            </div>
            <div className="chat-messages">
              <div className="conversation-date">
                TODAY <span /> NORTH SUBSTATION
              </div>
              {messages.map((m, i) => (
                <article key={i} className={`message ${m.role}`}>
                  <div className={`message-avatar ${m.role}`}>
                    {m.role === "assistant" ? <Zap size={16} /> : "JD"}
                  </div>
                  <div className="message-content">
                    <div className="message-author">
                      {m.role === "assistant" ? "Terra" : "You"}
                      <span>{i < 2 ? "10:24" : "Just now"}</span>
                    </div>
                    <p>{m.text}</p>
                    {m.context && (
                      <div className="chat-file">
                        <Box size={12} />
                        {m.context}
                      </div>
                    )}
                    {m.files?.map((f, j) => (
                      <div className="chat-file" key={j}>
                        <Paperclip size={12} />
                        {f}
                      </div>
                    ))}
                    {m.card && (
                      <>
                        <div className="design-card">
                          <div>
                            <span className="artifact-icon">
                              <LayoutGrid size={18} />
                            </span>
                            <span>
                              <strong>North substation mesh</strong>
                              <small>
                                Initial design · illustrative preview
                              </small>
                            </span>
                            <span className="version-chip">v1</span>
                          </div>
                          <dl>
                            <div>
                              <dt>Grid dimensions</dt>
                              <dd>40 × 30 m</dd>
                            </div>
                            <div>
                              <dt>Mesh spacing</dt>
                              <dd>5 × 5 m</dd>
                            </div>
                            <div>
                              <dt>Ground rods</dt>
                              <dd>12 perimeter rods</dd>
                            </div>
                          </dl>
                          <button onClick={() => setExpanded(true)}>
                            Explore design <ChevronRight size={14} />
                          </button>
                        </div>
                        <p className="assistant-followup">
                          Where would you like to start? You can explore the
                          mesh or adjust the soil and design parameters.
                        </p>
                        <div className="suggestions">
                          <button
                            onClick={() =>
                              send("Explore ways to refine the grounding mesh")
                            }
                          >
                            Refine the mesh <ArrowUp size={12} />
                          </button>
                          <button
                            onClick={() => send("Explain the soil parameters")}
                          >
                            Review soil inputs <ArrowUp size={12} />
                          </button>
                        </div>
                      </>
                    )}
                  </div>
                </article>
              ))}
              <div ref={chatEnd} />
            </div>
            <div className="composer-wrap">
              {selected !== null && (
                <div className="selection-context">
                  <Box size={13} />
                  Ground rod R-{String(selected + 1).padStart(2, "0")} selected
                  <IconButton
                    title="Clear selection"
                    onClick={() => setSelected(null)}
                  >
                    <X size={13} />
                  </IconButton>
                </div>
              )}
              <div className="composer">
                {attachments.length > 0 && (
                  <div className="attachment-chips">
                    {attachments.map((a) => (
                      <span key={a.id}>
                        <File size={12} />
                        {a.name}
                        <button
                          aria-label={`Remove ${a.name}`}
                          onClick={() =>
                            setAttachments((v) =>
                              v.filter((x) => x.id !== a.id),
                            )
                          }
                        >
                          <X size={12} />
                        </button>
                      </span>
                    ))}
                  </div>
                )}
                <textarea
                  aria-label="Message the design assistant"
                  placeholder="Ask Terra to refine your design…"
                  value={draft}
                  onChange={(e) => setDraft(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && !e.shiftKey) {
                      e.preventDefault();
                      send();
                    }
                  }}
                />
                <div className="composer-toolbar">
                  <div>
                    <IconButton
                      title="Attach images or files"
                      onClick={() => fileRef.current.click()}
                    >
                      <Paperclip size={17} />
                    </IconButton>
                    <IconButton
                      title={recording ? "Stop recording" : "Voice input"}
                      onClick={voice}
                    >
                      <Mic
                        size={17}
                        color={recording ? "#e15d55" : undefined}
                      />
                    </IconButton>
                    <span>
                      {recording
                        ? "Listening…"
                        : "Text, voice, images or files"}
                    </span>
                  </div>
                  <button
                    className="send-button"
                    aria-label="Send message"
                    disabled={!draft.trim() && !attachments.length}
                    onClick={() => send()}
                  >
                    <ArrowUp size={18} />
                  </button>
                </div>
              </div>
              <div className="composer-caption">
                <Sparkles size={11} />
                Design assistance, with you in control.<span>↵ to send</span>
              </div>
            </div>
          </section>
          <section
            className={`refinement-panel panel ${expanded ? "expanded" : ""}`}
          >
            <div className="panel-heading">
              <div>
                <Settings2 size={17} />
                <h2>Design refinement</h2>
                <span className="version-chip">v{versions.length}</span>
              </div>
              <IconButton
                title={
                  expanded ? "Close expanded view" : "Expand refinement view"
                }
                onClick={() => setExpanded(!expanded)}
              >
                {expanded ? <X size={16} /> : <Maximize2 size={16} />}
              </IconButton>
            </div>
            <div className="refinement-scroll">
              <Section
                icon={LayoutGrid}
                title="Grounding mesh"
                label={
                  <span className="live-label">
                    <span />
                    Live preview
                  </span>
                }
              >
                <div className="mesh-toolbar">
                  <span className="view-toggle">
                    <Square size={12} />
                    2D plan
                  </span>
                  <span>Units: meters</span>
                  <IconButton
                    title="Clear mesh selection"
                    onClick={() => setSelected(null)}
                  >
                    <RotateCcw size={13} />
                  </IconButton>
                </div>
                <Mesh
                  parameters={parameters}
                  selected={selected}
                  onSelect={setSelected}
                />
                <div className="mesh-legend">
                  <span>
                    <i className="line-swatch" />
                    Copper conductor
                  </span>
                  <span>
                    <i className="rod-swatch" />
                    Ground rod
                  </span>
                  <span>
                    {parameters.length} × {parameters.width} m
                  </span>
                </div>
                <div className="mesh-metrics">
                  <div>
                    <small>Mesh spacing</small>
                    <strong>{parameters.spacing} m</strong>
                  </div>
                  <div>
                    <small>Ground rods</small>
                    <strong>
                      {parameters.rods}
                      <em>rods</em>
                    </strong>
                  </div>
                  <div>
                    <small>Burial depth</small>
                    <strong>
                      {parameters.depth}
                      <em>m</em>
                    </strong>
                  </div>
                </div>
              </Section>
              <Section
                icon={Activity}
                title="Surface potential"
                label={<span className="muted-label">Illustrative</span>}
              >
                <div className="chart-heading">
                  <span>Potential distribution</span>
                  <small>V</small>
                </div>
                <PotentialChart />
                <div className="chart-caption">
                  <span className="green-dot" />
                  Surface potential profile<span>Sample data</span>
                </div>
              </Section>
              <Section
                icon={Layers}
                title="Soil parameters"
                label={<span className="muted-label">Layer 01</span>}
              >
                <div className="parameter-grid">
                  {field("Soil resistivity", "resistivity", "Ω·m")}
                  {field("Layer depth", "soilDepth", "m", 0.1)}
                </div>
                <div className="input-note">
                  <FileSpreadsheet size={12} />
                  Demo values · field measurements pending
                </div>
              </Section>
              <Section
                icon={Settings2}
                title="Design parameters"
                label={<span className="muted-label">Edit geometry</span>}
              >
                <div className="parameter-grid">
                  {field("Grid length", "length", "m")}
                  {field("Grid width", "width", "m")}
                  {field("Mesh spacing", "spacing", "m", 0.5)}
                  {field("Ground rods", "rods", "qty")}
                  {field("Burial depth", "depth", "m", 0.1)}
                  {field("Fault current", "current", "A")}
                  {field("Clearing time", "time", "s", 0.1)}
                </div>
              </Section>
              <Section
                icon={GitBranch}
                title="Materials & pricing"
                label={<span className="muted-label">Estimate</span>}
              >
                <div className="parameter-grid">
                  {field("Copper unit price", "copperPrice", "$/m", 0.1)}
                  <div className="price-total">
                    <span>Estimated copper</span>
                    <strong>
                      $
                      {(cableLength * parameters.copperPrice).toLocaleString(
                        "en-US",
                        { maximumFractionDigits: 0 },
                      )}
                    </strong>
                  </div>
                </div>
                <div className="input-note">
                  {cableLength.toFixed(0)} m of conductor · USD · excludes rods,
                  labor and tax
                </div>
              </Section>
              <div className="review-note">
                <ShieldCheck size={16} />
                <span>
                  Draft workspace. Engineering validation is not connected.
                </span>
              </div>
            </div>
            <div className="refinement-footer">
              <span>
                <span className="green-dot" />
                Session changes
              </span>
              <button className="button primary" onClick={save}>
                <Check size={14} />
                Save version
              </button>
            </div>
          </section>
        </main>
        <footer className="workspace-footer">
          <span>
            terra <span> / </span> Grounding design, thoughtfully connected.
          </span>
          <span>
            Prototype workspace <span>·</span> No calculations executed
          </span>
        </footer>
      </div>}
      <input
        type="file"
        multiple
        accept=".pdf,.png,.jpg,.jpeg,.csv,.xlsx,application/pdf,image/png,image/jpeg,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ref={fileRef}
        hidden
        onChange={(e) => {
          addFiles(e.target.files);
          e.target.value = "";
        }}
      />
      {notice && (
        <div className="toast" role="status">
          <CircleHelp size={18} />
          {notice}
          <IconButton
            title="Dismiss notification"
            onClick={() => setNotice("")}
          >
            <X size={15} />
          </IconButton>
        </div>
      )}
      {history && (
        <div className="modal-backdrop" onClick={() => setHistory(false)}>
          <section
            className="history-modal"
            role="dialog"
            aria-modal="true"
            aria-label="Design version history"
            onClick={(e) => e.stopPropagation()}
            onKeyDown={(e) => {
              if (e.key === "Escape") setHistory(false);
            }}
          >
            <div className="panel-heading">
              <div>
                <History size={18} />
                <h2>Design history</h2>
              </div>
              <IconButton
                title="Close history"
                onClick={() => setHistory(false)}
              >
                <X size={18} />
              </IconButton>
            </div>
            <p>
              Restore a saved set of parameters. Versions are held in this
              browser session.
            </p>
            {versions.map((v, i) => (
              <button
                className="history-version"
                key={i}
                onClick={() => {
                  setParameters({ ...v.parameters });
                  setSelected(null);
                  setHistory(false);
                  setNotice(`Restored version ${i + 1}.`);
                }}
              >
                <span className="version-chip">v{i + 1}</span>
                <span>
                  <strong>{v.name}</strong>
                  <small>
                    {v.parameters.length} × {v.parameters.width} m ·{" "}
                    {v.parameters.rods} rods
                  </small>
                </span>
                <RotateCcw size={15} />
              </button>
            ))}
          </section>
        </div>
      )}
    </div>
  );
}

createRoot(document.getElementById("root")).render(<App />);
