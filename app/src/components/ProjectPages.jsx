import React, { useEffect, useRef, useState } from "react";
import { Activity, ArrowDownToLine, ArrowDown, ArrowLeft, ArrowRight, ArrowUp, Box, Check, ChevronDown, ChevronRight, CircleHelp, File, FileImage, FileSpreadsheet, FolderOpen, GitBranch, History, Layers, LayoutGrid, MapPin, MessageCircle, Minus, Maximize2, Mic, Network, Paperclip, Plus, Pencil, RotateCcw, Search, Settings2, ShieldCheck, Sparkles, Square, X, Trash2, Zap } from "lucide-react";
import { mimeByExtension, uploadableMimeTypes, uploadStatusLabels } from "../shared.jsx";
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
      onLogin(result);
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
  const [deleteProject, setDeleteProject] = useState(null);
  const [deleting, setDeleting] = useState(false);
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
  async function removeProject() {
    if (!deleteProject || deleting) return;
    setDeleting(true);
    try {
      await request(`/api/v1/projects/${deleteProject.id}`, { method: "DELETE" });
      setDeleteProject(null);
      await refresh();
      onNotice("Proyecto eliminado.");
    } catch (e) { setError(e.message); }
    finally { setDeleting(false); }
  }
  function askToDelete(project) {
    setError("");
    setDeleteProject(project);
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
      {projects.length ? projects.map((p) => <tr key={p.id}><td><button className="project-open-link" onClick={() => onOpen(p)}><strong>{p.name}</strong><small>{p.description || "Sin descripción"}</small></button></td><td><span className="land-tag">Tierras</span></td><td>{[p.city, p.country].filter(Boolean).join(", ") || (p.latitude != null && p.longitude != null ? `${Number(p.latitude).toFixed(4)}, ${Number(p.longitude).toFixed(4)}` : "Sin ubicación")}</td><td>{p.attachments?.length || 0} archivos</td><td>{new Date(p.updated_at * 1000).toLocaleDateString("es-CO")}</td><td className="row-actions"><button title="Abrir espacio del proyecto" onClick={() => onOpen(p)}><MessageCircle size={15}/></button><button title="Editar proyecto" onClick={() => start(p)}><Pencil size={15}/></button><button title="Borrar proyecto" onClick={() => askToDelete(p)}><Trash2 size={15}/></button></td></tr>) : <tr><td colSpan="6" className="projects-empty"><FolderOpen size={28}/><strong>Aún no hay proyectos</strong><span>Crea tu primer proyecto para empezar a organizar la información del sitio.</span><button className="button" onClick={() => start()}><Plus size={14}/> Crear proyecto</button></td></tr>}
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
    {deleteProject && <div className="modal-backdrop project-modal-backdrop delete-project-backdrop" onMouseDown={(e) => { if (e.target === e.currentTarget && !deleting) setDeleteProject(null); }}><section className="delete-project-modal" role="alertdialog" aria-modal="true" aria-labelledby="delete-project-title" aria-describedby="delete-project-description" onKeyDown={(e) => { if (e.key === "Escape" && !deleting) setDeleteProject(null); }}><div className="delete-project-icon"><Trash2 size={20}/></div><h2 id="delete-project-title">¿Borrar este proyecto?</h2><p id="delete-project-description">Se eliminará <strong>{deleteProject.name}</strong> y ya no podrás acceder a sus archivos ni a su espacio de trabajo. Esta acción no se puede deshacer.</p>{error && <div className="project-modal-error" role="alert">{error}</div>}<div className="delete-project-actions"><button className="button" type="button" autoFocus disabled={deleting} onClick={() => setDeleteProject(null)}>Cancelar</button><button className="button danger" type="button" disabled={deleting} onClick={removeProject}><Trash2 size={14}/>{deleting ? "Borrando…" : "Borrar proyecto"}</button></div></section></div>}
  </section>;
}


export { Login, MapPicker, ProjectsPage };
