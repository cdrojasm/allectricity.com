import React, { useEffect, useRef, useState } from "react";
import { Activity, ArrowDownToLine, ArrowDown, ArrowLeft, ArrowRight, ArrowUp, Box, Cable, Check, ChevronDown, ChevronLeft, ChevronRight, CircleHelp, File, FileImage, FileSpreadsheet, FolderOpen, GitBranch, History, Layers, LayoutGrid, MapPin, MessageCircle, Minus, Maximize2, Mic, Network, Paperclip, Plus, Pencil, RotateCcw, Search, Settings2, ShieldCheck, Sparkles, Square, X, Trash2, Zap } from "lucide-react";
import { DesignStatusBadge, RichText, mimeByExtension, recordFeatureUse, uploadableMimeTypes, uploadStatusLabels } from "../shared.jsx";
import { GroundingCalculations } from "./GroundingCalculations.jsx";
import { GroundingPlanDrawer } from "./GroundingPlanDrawer.jsx";
import { AgentArtifactPanel, AgentResultsPanel, ArtifactUpdateCard } from "./AgentArtifact.jsx";
import { KnowledgeGraphWorkspace } from "./KnowledgeGraphWorkspace.jsx";
import { StudyManager } from "./StudyPage.jsx";

function KnowledgeInterrogationCard({ message, confirmed, busy, onConfirm }) {
  const payload = message.payload || {};
  return <article className="message assistant"><div className="message-avatar assistant"><Zap size={15}/></div><div className="message-content knowledge-interrogation"><div className="message-author">Terra<span>{new Date(message.created_at * 1000).toLocaleTimeString("es-CO", { hour: "2-digit", minute: "2-digit" })}</span></div><p>{message.text}</p><div className="interrogation-summary"><span>{payload.found_count} encontrados</span><span className={payload.conflict_count ? "warn" : ""}>{payload.conflict_count} conflictos</span><span className={payload.missing_count ? "warn" : ""}>{payload.missing_count} faltantes</span></div>{payload.found?.length > 0 && <details><summary>Ver datos encontrados</summary><ul>{payload.found.map((item) => <li key={`${item.attribute}-${item.claim_id}`}><strong>{item.attribute}</strong> · {item.value} {item.unit || ""}{item.source && <small> · {item.source}</small>}</li>)}</ul></details>}{payload.confirmable_claim_ids?.length > 0 && <button className="button primary" disabled={busy || confirmed} onClick={onConfirm}>{confirmed ? "Datos confirmados" : busy ? "Confirmando…" : `Confirmar ${payload.confirmable_claim_ids.length} datos encontrados`}</button>}</div></article>;
}

function HorizontalTabStrip({ children }) {
  const viewport = useRef(null);
  const drag = useRef(null);
  const suppressClick = useRef(false);
  const [overflow, setOverflow] = useState(false);
  useEffect(() => {
    const node = viewport.current;
    if (!node || typeof ResizeObserver === "undefined") return undefined;
    const measure = () => setOverflow(node.scrollWidth > node.clientWidth + 1);
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(node);
    return () => observer.disconnect();
  }, []);
  const scroll = (direction) => viewport.current?.scrollBy({ left: direction * Math.max(140, viewport.current.clientWidth * 0.7), behavior: "smooth" });
  function startDrag(event) {
    if (event.button !== 0) return;
    drag.current = { pointerId: event.pointerId, x: event.clientX, scrollLeft: viewport.current.scrollLeft, moved: false };
  }
  function moveDrag(event) {
    if (!drag.current || drag.current.pointerId !== event.pointerId) return;
    const distance = event.clientX - drag.current.x;
    if (!drag.current.moved && Math.abs(distance) > 5) {
      drag.current.moved = true;
      viewport.current.classList.add("dragging");
      viewport.current.setPointerCapture(event.pointerId);
    }
    if (drag.current.moved) { event.preventDefault(); viewport.current.scrollLeft = drag.current.scrollLeft - distance; }
  }
  function endDrag(event) {
    if (!drag.current || drag.current.pointerId !== event.pointerId) return;
    suppressClick.current = drag.current.moved;
    if (drag.current.moved && viewport.current.hasPointerCapture(event.pointerId)) viewport.current.releasePointerCapture(event.pointerId);
    viewport.current.classList.remove("dragging");
    drag.current = null;
  }
  return <div className="project-tabs-slider">{overflow && <button className="project-tabs-arrow" aria-label="Desplazar pestañas a la izquierda" onClick={() => scroll(-1)}><ChevronLeft size={15}/></button>}<div className="project-tabs-viewport" ref={viewport} onPointerDown={startDrag} onPointerMove={moveDrag} onPointerUp={endDrag} onPointerCancel={endDrag} onClickCapture={(event) => { if (suppressClick.current) { event.preventDefault(); event.stopPropagation(); suppressClick.current = false; } }}>{children}</div>{overflow && <button className="project-tabs-arrow" aria-label="Desplazar pestañas a la derecha" onClick={() => scroll(1)}><ChevronRight size={15}/></button>}</div>;
}

// Artifact sections by level: overview, sources (level 0), inputs (level 1), result (level 2).
const artifactSections = [
  { id: "artifact", icon: Box, label: "Resumen" },
  { id: "files", icon: Layers, label: "Fuentes" },
  { group: "Entradas", id: "measurements", icon: FileSpreadsheet, label: "Mediciones" },
  { id: "soil", icon: Network, label: "Suelo" },
  { id: "safety", icon: ShieldCheck, label: "Parámetros", title: "Parámetros eléctricos" },
  { id: "plan", icon: Cable, label: "Plano" },
  { group: "", id: "results", icon: Activity, label: "Resultado" },
];

function ProjectSourcesPanel({ files, retryingUploads, onAdd, onRetry, onOpenGraph }) {
  const latestByName = [...new Map([...files].sort((a, b) => a.updated_at - b.updated_at).map((f) => [f.filename.toLocaleLowerCase(), f])).values()];
  return <section className="panel project-files-panel"><div className="panel-heading"><div><Layers size={17}/><h2>Fuentes del proyecto</h2><span className="count">{latestByName.length}</span></div><div className="project-files-actions"><button className="button" disabled={!files.some((f) => f.status === "available")} onClick={onOpenGraph}><Search size={14}/> Ver lo extraído</button><button className="icon-button" title="Cargar archivos" onClick={onAdd}><Plus size={17}/></button></div></div><div className="project-files-list">{latestByName.length ? latestByName.map((f) => <div className="project-file-row" key={f.upload_id}><span className={`asset-icon ${f.mime_type.startsWith("image/") ? "image" : "document"}`}>{f.mime_type.startsWith("image/") ? <FileImage size={18}/> : <File size={18}/>}</span><span><strong>{f.filename}</strong><small>{f.ocr_needs_review ? `Revisión OCR recomendada · ${Number(f.ocr_confidence ?? 0).toFixed(0)}% de confianza` : uploadStatusLabels[f.status] || f.status}</small>{f.last_error && <small className="upload-error-text">{f.last_error}</small>}{["failed", "expired"].includes(f.status) && <button className="upload-retry-button" disabled={retryingUploads.has(f.upload_id)} onClick={() => onRetry(f)}>{retryingUploads.has(f.upload_id) ? "Reintentando…" : "Reintentar"}</button>}</span><i className={`asset-dot ${f.status === "failed" || f.status === "rejected" || f.status === "expired" || f.ocr_needs_review ? "error" : f.status !== "available" ? "pending" : ""}`}/></div>) : <div className="empty-assets">Los archivos cargados para este proyecto aparecerán aquí. También puedes adjuntarlos o soltarlos en el chat.</div>}</div><button className="upload-area" onClick={onAdd}><span><Plus size={16}/></span><strong>Agregar archivos</strong><small>PDF, DOCX, PNG, JPG, CSV o XLSX · máximo 20 MB</small></button><div className="project-chat-files-note"><ShieldCheck size={16}/> Todo archivo pasa por cuarentena y análisis antes de adjuntarse al chat.</div></section>;
}

function ProjectChatWorkspace({ project, token, userId, onBack, onNotice, onOpenCatalog }) {
  const [view, setView] = useState("workspace");
  const [artifactSection, setArtifactSection] = useState("artifact");
  const [mobileSection, setMobileSection] = useState("chat");
  const [files, setFiles] = useState([]);
  const [retryingUploads, setRetryingUploads] = useState(() => new Set());
  const [conversation, setConversation] = useState(null);
  const [conversations, setConversations] = useState([]);
  const [projectMemory, setProjectMemory] = useState({ summary: "", items: [] });
  const [messages, setMessages] = useState([]);
  const [cancelled, setCancelled] = useState(() => new Set());
  const [attachments, setAttachments] = useState([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [voiceListening, setVoiceListening] = useState(false);
  const [agent, setAgent] = useState({ run: null, seq: null, progress: "", pollMs: null });
  const [artifactKey, setArtifactKey] = useState(0);
  const [designStatus, setDesignStatus] = useState(null);
  const [noOlder, setNoOlder] = useState(false);
  useEffect(() => {
    let live = true;
    fetch(`/api/v1/projects/${project.id}`, { headers: { Authorization: `Bearer ${token}` } })
      .then((r) => (r.ok ? r.json() : null)).then((data) => { if (live && data?.design_status) setDesignStatus(data.design_status); }).catch(() => {});
    return () => { live = false; };
  }, [project.id, token, artifactKey, conversation?.id, messages.length]);
  const lastArtifactUpdate = useRef(undefined);
  const [error, setError] = useState("");
  const [confirmingInterrogation, setConfirmingInterrogation] = useState(null);
  const [confirmedInterrogations, setConfirmedInterrogations] = useState(() => new Set());
  const fileInput = useRef(null);
  const expiredRetryId = useRef(null);
  const messageBox = useRef(null);
  const speechRecognition = useRef(null);
  const voiceText = useRef("");
  const voiceFailed = useRef(false);
  const voiceUnmounted = useRef(false);
  const auth = { Authorization: `Bearer ${token}` };
  function activateFeature(section, current, setter) {
    setter(section);
    if (current !== section) recordFeatureUse(userId, section, project.name);
  }
  useEffect(() => {
    recordFeatureUse(userId, "workspace", project.name);
    recordFeatureUse(userId, "artifact", project.name);
  }, [project.id, project.name, userId]);
  useEffect(() => () => {
    voiceUnmounted.current = true;
    speechRecognition.current?.abort();
  }, []);
  const request = async (url, options = {}) => {
    const response = await fetch(url, { ...options, headers: { ...auth, ...(options.body ? { "Content-Type": "application/json" } : {}), ...options.headers } });
    const body = response.status === 204 ? "" : await response.text();
    let data = null;
    try { data = body ? JSON.parse(body) : null; } catch { /* Some proxies return plain text for 5xx responses. */ }
    if (!response.ok) {
      const detail = typeof data?.detail === "string" ? data.detail : Array.isArray(data?.detail) ? data.detail.map((item) => item.msg || JSON.stringify(item)).join("; ") : null;
      throw new Error(detail || (response.status >= 500 ? "El servidor no pudo completar la operación. Inténtalo de nuevo." : "No se pudo completar la operación."));
    }
    return data;
  };
  async function reloadFiles() { setFiles(await request(`/api/v1/projects/${project.id}/files`)); }
  async function retryUpload(uploadId) {
    setRetryingUploads((current) => new Set(current).add(uploadId));
    setError("");
    try {
      await request(`/api/v1/files/${uploadId}/retry`, { method: "POST" });
      await reloadFiles();
    } catch (e) { setError(e.message); await reloadFiles().catch(() => {}); }
    finally { setRetryingUploads((current) => { const next = new Set(current); next.delete(uploadId); return next; }); }
  }
  async function reloadMessages(id = conversation?.id) {
    if (!id) return;
    setMessages(await request(`/api/v1/conversations/${id}/messages/first?limit=50`));
  }
  async function reloadAgent(id = conversation?.id) {
    if (!id) return;
    const query = agent.seq === null ? "" : `?after=${agent.seq}`;
    const data = await request(`/api/v1/conversations/${id}/agent-events${query}`);
    if (data.events.some((e) => ["artifact.version_created", "calculation.queued", "calculation.completed", "calculation.failed"].includes(e.type))) setArtifactKey((k) => k + 1);
    if (agent.seq !== null && data.events.some((e) => e.type === "calculation.completed")) setArtifactSection("results");
    const latest = [...data.events].reverse().find((e) => e.run_id === data.active_run?.id);
    setAgent((current) => ({ run: data.active_run, seq: data.next_after, pollMs: data.poll_after_ms,
      progress: data.active_run ? (latest?.title || (current.run?.id === data.active_run.id ? current.progress : "")) : "" }));
  }
  async function activateConversation(next) {
    setConversation(next);
    setMessages([]); setCancelled(new Set()); setAgent({ run: null, seq: null, progress: "", pollMs: null });
    setAttachments([]); setDraft(""); setError(""); lastArtifactUpdate.current = undefined;
    const [history, state] = await Promise.all([
      request(`/api/v1/conversations/${next.id}/messages/first?limit=50`),
      request(`/api/v1/conversations/${next.id}/agent-events`),
    ]);
    setMessages(history);
    setAgent({ run: state.active_run, seq: state.next_after, pollMs: state.poll_after_ms,
      progress: [...state.events].reverse().find((event) => event.run_id === state.active_run?.id)?.title || "" });
  }
  async function createConversation() {
    if (busy) return;
    try {
      const created = await request(`/api/v1/projects/${project.id}/conversations`, { method: "POST", body: JSON.stringify({ title: "Nueva conversación" }) });
      setConversations((current) => [created, ...current]);
      await activateConversation(created);
    } catch (e) { setError(e.message); }
  }
  useEffect(() => {
    let live = true;
    (async () => {
      try {
        // PR-05: each list is loaded on its own. One failing request (memory, for example) used to leave the files at
        // 0 and the conversation unopened while the rest of the page showed a project with documents.
        const [filesResult, convsResult, memoryResult] = await Promise.allSettled([
          request(`/api/v1/projects/${project.id}/files`),
          request(`/api/v1/projects/${project.id}/conversations`),
          request(`/api/v1/projects/${project.id}/memory`),
        ]);
        if (!live) return;
        if (filesResult.status === "fulfilled") setFiles(filesResult.value);
        if (memoryResult.status === "fulfilled") setProjectMemory(memoryResult.value);
        const failed = [filesResult, memoryResult].filter((result) => result.status === "rejected");
        if (failed.length) setError(failed.map((result) => result.reason?.message || "No se pudo cargar parte del proyecto.").join(" "));
        if (convsResult.status === "rejected") throw convsResult.reason;
        const convs = convsResult.value;
        setConversations(convs);
        const current = convs[0] || await request(`/api/v1/projects/${project.id}/conversations`, { method: "POST", body: JSON.stringify({ title: `Diseño · ${project.name}` }) });
        if (!live) return;
        if (!convs.length) setConversations([current]);
        await activateConversation(current);
      } catch (e) { if (live) setError(e.message); }
    })();
    return () => { live = false; };
  }, [project.id]);
  useEffect(() => {
    if (!files.some((file) => ["pending", "scanning"].includes(file.status))) return undefined;
    const timer = setInterval(() => reloadFiles().catch(() => {}), 5000);
    return () => clearInterval(timer);
  }, [files, project.id]);
  useEffect(() => {
    messageBox.current?.scrollTo({ top: messageBox.current.scrollHeight, behavior: "smooth" });
    if (!conversation) return undefined;
    const pending = messages.some((m) => ["pending", "processing"].includes(m.status) && !cancelled.has(m.id));
    if (!pending && !agent.pollMs) return undefined;
    const timer = setInterval(() => { reloadMessages().catch(() => {}); reloadAgent().catch(() => {}); request(`/api/v1/projects/${project.id}/memory`).then(setProjectMemory).catch(() => {}); }, agent.pollMs || 1500);
    return () => clearInterval(timer);
  }, [messages, conversation, cancelled, agent.pollMs, agent.seq]);
  useEffect(() => {
    // The `artifact.updated` message is the reload flag: refresh the artifact view when a new one arrives.
    const latest = [...messages].reverse().find((m) => m.payload?.kind === "artifact.updated");
    if (!latest) { if (messages.length && lastArtifactUpdate.current === undefined) lastArtifactUpdate.current = null; return; }
    if (latest.id === lastArtifactUpdate.current) return;
    const firstLoad = lastArtifactUpdate.current === undefined;
    lastArtifactUpdate.current = latest.id;
    setArtifactKey((k) => k + 1);
    if (!firstLoad) setArtifactSection("artifact");
  }, [messages]);
  async function uploadFile(file, retryUploadId = null) {
    const extension = file.name.split(".").pop().toLowerCase();
    const mime = mimeByExtension[extension] || file.type;
    if (!uploadableMimeTypes.has(mime) || file.size > 20 * 1024 * 1024) throw new Error(`${file.name}: usa PDF, DOCX, PNG, JPG, CSV, XLSX o DXF de hasta 20 MB.`);
    const placeholder = { id: crypto.randomUUID(), filename: file.name, status: "uploading", retryUploadId };
    setAttachments((current) => [...current, placeholder]);
    const update = (changes) => setAttachments((current) => current.map((a) => a.id === placeholder.id ? { ...a, ...changes } : a));
    try {
      const presign = await request("/api/v1/files/presign", { method: "POST", body: JSON.stringify({ filename: file.name, mime_type: mime, category: "documents", project_id: project.id, ...(placeholder.retryUploadId ? { retry_upload_id: placeholder.retryUploadId } : {}) }) });
      const put = await fetch(presign.upload_url, { method: "PUT", headers: { "Content-Type": mime }, body: file });
      if (!put.ok) throw new Error("No se pudo cargar el archivo al almacenamiento.");
      await request(`/api/v1/files/${presign.upload_id}/complete`, { method: "POST" });
      update({ uploadId: presign.upload_id, status: "scanning", mime_type: mime });
      for (let attempt = 0; attempt < 180; attempt += 1) {
        const state = await request(`/api/v1/files/${presign.upload_id}`);
        update({ status: state.status });
        if (state.status === "available") { await reloadFiles(); return; }
        if (["rejected", "failed", "expired"].includes(state.status)) throw new Error(state.last_error || uploadStatusLabels[state.status]);
        await new Promise((resolve) => setTimeout(resolve, 1500));
      }
      update({ status: "scanning" });
      await reloadFiles();
    } catch (e) { update({ status: "failed", error: e.message }); await reloadFiles().catch(() => {}); throw e; }
  }
  async function addFiles(fileList) {
    const seenNames = new Set(files.map((existing) => existing.filename.toLocaleLowerCase()));
    const uploads = [];
    for (const file of Array.from(fileList)) {
      const normalizedName = file.name.toLocaleLowerCase();
      if (seenNames.has(normalizedName)) {
        const message = `Ya existe un archivo llamado ${file.name} en este proyecto.`;
        setError(message); onNotice(message); continue;
      }
      seenNames.add(normalizedName);
      // Each upload waits for its scan and processing, so they run side by side.
      uploads.push(uploadFile(file).catch((e) => { setError(e.message); onNotice(e.message); }));
    }
    await Promise.all(uploads);
  }
  function retryExpiredUpload(file) {
    const uploadId = expiredRetryId.current;
    expiredRetryId.current = null;
    if (!file || !uploadId) return;
    if (file.name.toLocaleLowerCase() !== files.find((item) => item.upload_id === uploadId)?.filename.toLocaleLowerCase()) {
      const message = "Selecciona el mismo archivo para completar la carga pendiente.";
      setError(message); onNotice(message); return;
    }
    uploadFile(file, uploadId).catch((e) => { setError(e.message); onNotice(e.message); });
  }
  async function sendMessage(textOverride = draft) {
    const text = textOverride.trim();
    const ready = attachments.filter((a) => a.uploadId && a.status === "available");
    if ((!text && !ready.length) || busy) return;
    setBusy(true); setError("");
    try {
      let active = conversation;
      if (!active) {
        active = await request(`/api/v1/projects/${project.id}/conversations`, { method: "POST", body: JSON.stringify({ title: `Diseño · ${project.name}` }) });
        setConversation(active);
      }
      await request(`/api/v1/conversations/${active.id}/messages`, {
        method: "POST",
        body: JSON.stringify({ text, type: ready.length ? (ready.every((a) => a.mime_type.startsWith("image/")) ? "image" : "file") : "text", contents: ready.map((a) => ({ upload_id: a.uploadId })) }),
      });
      setDraft(""); setAttachments([]);
      setConversations((current) => current.map((item) => item.id === active.id ? { ...item, title: item.title === "Nueva conversación" && text ? text.slice(0, 60) : item.title, updated_at: Math.floor(Date.now() / 1000) } : item).sort((a, b) => b.updated_at - a.updated_at));
      await Promise.all([reloadMessages(active.id), reloadAgent(active.id)]);
    } catch (e) { setError(e.message); }
    finally { setBusy(false); }
  }
  async function confirmInterrogation(message) {
    const claimIds = message.payload?.confirmable_claim_ids || [];
    if (!claimIds.length || confirmingInterrogation) return;
    setConfirmingInterrogation(message.id); setError("");
    try {
      const result = await request(`/api/v1/projects/${project.id}/knowledge-graph/claims/decisions`, { method: "POST", body: JSON.stringify({ items: claimIds.map((claim_id) => ({ claim_id, decision: "accept", reason: "Confirmado desde la interrogación" })) }) });
      if (result.failed) setError(`${result.succeeded} datos confirmados; ${result.failed} requieren revisión individual.`);
      if (!result.failed) setConfirmedInterrogations((current) => new Set([...current, message.id]));
    } catch (e) { setError(e.message); }
    finally { setConfirmingInterrogation(null); }
  }
  function startVoiceNote() {
    if (voiceListening) {
      speechRecognition.current?.stop();
      return;
    }
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognition) {
      setError("Este navegador no ofrece reconocimiento de voz. Prueba con Chrome o Edge actualizado.");
      return;
    }
    setError("");
    setDraft("");
    voiceText.current = "";
    voiceFailed.current = false;
    voiceUnmounted.current = false;
    let recognition;
    try { recognition = new SpeechRecognition(); }
    catch { setError("No se pudo preparar el reconocimiento de voz en este navegador."); return; }
    recognition.lang = "es-CO";
    recognition.continuous = true;
    recognition.interimResults = true;
    recognition.onstart = () => setVoiceListening(true);
    recognition.onresult = (event) => {
      const finalParts = [];
      const interimParts = [];
      for (let i = 0; i < event.results.length; i += 1) {
        const result = event.results[i];
        const transcript = result[0]?.transcript?.trim();
        if (!transcript) continue;
        (result.isFinal ? finalParts : interimParts).push(transcript);
      }
      const transcript = [...finalParts, ...interimParts].join(" ").trim();
      voiceText.current = transcript;
      setDraft(transcript);
    };
    recognition.onerror = (event) => {
      voiceFailed.current = true;
      setVoiceListening(false);
      const messages = {
        "not-allowed": "Permite el acceso al micrófono para dictar una nota de voz.",
        "service-not-allowed": "El servicio de reconocimiento de voz no está disponible.",
        network: "Se perdió la conexión durante la transcripción de voz.",
        "no-speech": "No se detectó voz. Inténtalo de nuevo.",
      };
      if (event.error !== "aborted") setError(messages[event.error] || "No se pudo transcribir la nota de voz.");
    };
    recognition.onend = () => {
      speechRecognition.current = null;
      setVoiceListening(false);
      if (voiceUnmounted.current || voiceFailed.current) return;
      const transcript = voiceText.current.trim();
      if (!transcript) {
        setError("No se detectó voz. Inténtalo de nuevo.");
        return;
      }
      setDraft(transcript);
      window.requestAnimationFrame(() => window.requestAnimationFrame(() => sendMessage(transcript)));
    };
    speechRecognition.current = recognition;
    setVoiceListening(true);
    try { recognition.start(); }
    catch {
      speechRecognition.current = null;
      setVoiceListening(false);
      setError("No se pudo iniciar el micrófono. Revisa los permisos del navegador.");
    }
  }
  function openGraph() {
    setView("graph");
    recordFeatureUse(userId, "knowledge-graph", project.name);
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
      if (older.length < 30) setNoOlder(true);
      setMessages((current) => [...older, ...current]);
      requestAnimationFrame(() => { if (node) node.scrollTop = node.scrollHeight - previousHeight; });
    } catch (e) { if (!e.message.includes("404")) setError(e.message); }
  }
  return <main className="project-chat-workspace">
    <header className="project-chat-topbar"><div className="breadcrumbs"><span className="wordmark">terra<span> / </span></span><button className="project-parent" onClick={onBack}>Proyectos <ChevronRight size={14}/></button><span className="project-name"><span className="project-dot"/>{project.name}</span><span className="project-badge">Puesta a tierra</span></div><div className="project-topbar-actions">{onOpenCatalog && <button className="button" onClick={() => onOpenCatalog(project.id)}><Layers size={14}/> Catálogo de materiales</button>}<div className="artifact-view-tabs project-view-switch" role="tablist" aria-label="Vista del proyecto"><button role="tab" aria-selected={view === "workspace"} className={view === "workspace" ? "active" : ""} onClick={() => activateFeature("workspace", view, setView)}><Sparkles size={14}/> Espacio de trabajo</button><button role="tab" aria-selected={view === "study"} className={view === "study" ? "active" : ""} onClick={() => activateFeature("study", view, setView)}>Compartir estudio</button></div><button className="button" onClick={onBack}><Layers size={14}/> Todos los proyectos</button></div></header>
    <div className="project-chat-heading"><div><div className="eyebrow">ESPACIO DEL PROYECTO</div><h1>{project.name}</h1><p>{view === "graph" ? "Entidades, afirmaciones y evidencia extraídas de los documentos del proyecto, para revisar y depurar." : project.description || "Archivos de entrada y conversación con el agente para diseñar y ajustar el proyecto."}</p></div><span className="project-chat-live">{designStatus ? <DesignStatusBadge status={designStatus}/> : <><i/> Proyecto activo</>}</span></div>
    {error && <div className="project-error" role="alert">{error}<button onClick={() => setError("")}><X size={14}/></button></div>}
    {view === "graph" ? <KnowledgeGraphWorkspace project={project} token={token}/> : view === "study" ? <StudyManager project={project} token={token} onNotice={onNotice}/> : <><div className="mobile-artifact-tabs" role="tablist" aria-label="Vista móvil"><button className={mobileSection === "chat" ? "active" : ""} role="tab" aria-selected={mobileSection === "chat"} onClick={() => setMobileSection("chat")}>Chat</button><button className={mobileSection === "artifact" ? "active" : ""} role="tab" aria-selected={mobileSection === "artifact"} onClick={() => setMobileSection("artifact")}>Diseño</button></div><div className={`project-workspace-grid mobile-${mobileSection}`}>
    <div className="project-center-column">
      <section className="panel project-conversation-panel" onDragOver={(event) => event.preventDefault()} onDrop={(event) => { event.preventDefault(); addFiles(event.dataTransfer.files); }}><div className="panel-heading chat-conversation-heading"><div><Sparkles size={17}/><h2>Conversación con el agente</h2></div><div className="conversation-controls"><select aria-label="Conversaciones del proyecto" value={conversation?.id || ""} onChange={(event) => { const next = conversations.find((item) => item.id === event.target.value); if (next) activateConversation(next).catch((e) => setError(e.message)); }}>{conversations.map((item) => <option value={item.id} key={item.id}>{item.title || "Conversación"}</option>)}</select><button className="button" onClick={createConversation}><Plus size={14}/> Nueva</button></div></div><details className="project-memory"><summary><History size={14}/> Notas del proyecto · {projectMemory.items?.length || 0}</summary><div>{projectMemory.summary && <p>{projectMemory.summary}</p>}{projectMemory.items?.length ? projectMemory.items.map((item, index) => <p key={`${item.kind}-${index}`}><strong>{item.kind === "decision" ? "Decisión" : item.kind === "assumption" ? "Supuesto" : "Pendiente"}:</strong> {item.text}<small title={(item.source_message_ids || []).join(", ")}> Fuentes: {(item.source_message_ids || []).map((id) => id.slice(0, 8)).join(", ")}</small></p>) : <p>El agente guardará aquí decisiones, supuestos y preguntas con referencia a los mensajes que los originaron.</p>}</div></details><div className="project-chat-messages" ref={messageBox}>{messages.length >= 30 && !noOlder && <button className="load-older" onClick={loadOlder}>Cargar mensajes anteriores</button>}{messages.length ? messages.map((m) => m.payload?.kind === "artifact.updated" ? <ArtifactUpdateCard key={m.id} message={m} token={token} project={project} onView={() => { setArtifactSection("artifact"); setMobileSection("artifact"); }} onUndone={() => setArtifactKey((k) => k + 1)}/> : m.payload?.kind === "knowledge.interrogation" ? <KnowledgeInterrogationCard key={m.id} message={m} confirmed={confirmedInterrogations.has(m.id)} busy={confirmingInterrogation === m.id} onConfirm={() => confirmInterrogation(m)}/> : <article className={`message ${m.source === "user" ? "user" : "assistant"}`} key={m.id}><div className={`message-avatar ${m.source === "user" ? "user" : "assistant"}`}>{m.source === "user" ? `${project.name[0] || "U"}` : <Zap size={15}/>}</div><div className="message-content"><div className="message-author">{m.source === "user" ? "Tú" : m.source === "notification" ? "Notificación" : "Terra"}<span>{new Date(m.created_at * 1000).toLocaleTimeString("es-CO", { hour: "2-digit", minute: "2-digit" })}</span></div>{m.text && <RichText text={m.text}/>}{m.contents?.map((c) => <div className="chat-file" key={c.id}>{c.format === "image" ? <FileImage size={13}/> : <Paperclip size={13}/>} {c.filename}</div>)}{["pending", "processing"].includes(m.status) && <div className="chat-processing">{agent.progress ? `${agent.progress}…` : m.status === "pending" ? "En cola…" : "Procesando solicitud…"}<button onClick={() => cancel(m)}>Cancelar</button></div>}</div></article>) : <div className="project-chat-empty"><span><Sparkles size={20}/></span><strong>Empieza la conversación</strong><p>Describe la subestación que quieres diseñar o adjunta archivos de referencia del proyecto.</p></div>}</div><div className="project-chat-composer"><div className="attachment-chips">{attachments.map((a) => <span key={a.id}><Paperclip size={12}/>{a.filename}<small>{a.status === "available" ? "Listo" : a.status === "failed" ? "Error" : "Analizando…"}</small><button aria-label={`Quitar ${a.filename}`} onClick={() => setAttachments((xs) => xs.filter((x) => x.id !== a.id))}><X size={12}/></button></span>)}</div><textarea aria-label="Mensaje para el chat del proyecto" placeholder="Describe lo que necesitas…" value={draft} readOnly={voiceListening} onChange={(e) => setDraft(e.target.value)} onKeyDown={(e) => { if (!voiceListening && e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendMessage(); } }}/><div className="project-composer-tools"><button className={`icon-button voice-note-button ${voiceListening ? "recording" : ""}`} aria-label={voiceListening ? "Detener nota de voz y enviar" : "Grabar nota de voz"} title={voiceListening ? "Detener y transcribir" : "Grabar nota de voz"} disabled={busy} onClick={startVoiceNote}>{voiceListening ? <Square size={15}/> : <Mic size={17}/>}</button><button className="icon-button" title="Adjuntar imágenes o archivos" onClick={() => fileInput.current?.click()}><Paperclip size={17}/></button><span>{voiceListening ? "Escuchando… el texto se enviará al detener la grabación" : "Los archivos se cargan y analizan antes de enviar"}</span><button className="send-button" disabled={busy || voiceListening || (!draft.trim() && !attachments.some((a) => a.status === "available"))} onClick={sendMessage}>{busy ? <Activity size={17}/> : <ArrowUp size={18}/>}</button></div></div></section>
    </div>
    <section className="artifact-column" aria-label="Diseño"><HorizontalTabStrip><div className="project-view-tabs" role="tablist" aria-label="Secciones del artefacto">{artifactSections.map(({ id, icon: Icon, label, title, group }) => <React.Fragment key={id}>{group !== undefined && <span className="artifact-nav-group" aria-hidden="true">{group}</span>}<button role="tab" title={title} aria-selected={artifactSection === id} className={artifactSection === id ? "active" : ""} onClick={() => activateFeature(id, artifactSection, setArtifactSection)}><Icon size={14}/> {label}</button></React.Fragment>)}</div></HorizontalTabStrip>{artifactSection === "files" ? <ProjectSourcesPanel files={files} retryingUploads={retryingUploads} onAdd={() => fileInput.current?.click()} onRetry={(f) => { if (f.status === "expired") { expiredRetryId.current = f.upload_id; fileInput.current?.click(); } else retryUpload(f.upload_id); }} onOpenGraph={openGraph}/> : ["measurements", "soil", "safety"].includes(artifactSection) ? <GroundingCalculations project={project} token={token} section={artifactSection} files={files} onArtifactSaved={() => setArtifactKey((key) => key + 1)}/> : artifactSection === "plan" ? <GroundingPlanDrawer key={project.id} projectId={project.id} projectName={project.name} conversation={conversation} token={token}/> : artifactSection === "artifact" ? <AgentArtifactPanel project={project} conversation={conversation} token={token} refreshKey={artifactKey} onOpenGraph={openGraph}/> : <AgentResultsPanel project={project} conversation={conversation} token={token} refreshKey={artifactKey} onSuggestion={(suggestion) => { setMobileSection("chat"); return sendMessage(suggestion); }}/>}</section>
    </div></>}
    <input ref={fileInput} hidden type="file" multiple accept=".pdf,.docx,.png,.jpg,.jpeg,.csv,.xlsx,.dxf" onChange={(e) => { const filesToAdd = e.target.files; if (expiredRetryId.current) retryExpiredUpload(filesToAdd?.[0]); else addFiles(filesToAdd); e.target.value = ""; }}/>
  </main>;
}


export { ProjectChatWorkspace };
