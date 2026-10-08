import React, { useEffect, useRef, useState } from "react";
import { Activity, ArrowDownToLine, ArrowDown, ArrowLeft, ArrowRight, ArrowUp, Box, Cable, Check, ChevronDown, ChevronLeft, ChevronRight, CircleHelp, File, FileImage, FileSpreadsheet, FolderOpen, GitBranch, History, Layers, LayoutGrid, MapPin, MessageCircle, Minus, Maximize2, Mic, Network, Paperclip, Plus, Pencil, RotateCcw, Search, Settings2, ShieldCheck, Sparkles, Square, X, Trash2, Zap } from "lucide-react";
import { mimeByExtension, recordFeatureUse, uploadableMimeTypes, uploadStatusLabels } from "../shared.jsx";
import { GroundingCalculations } from "./GroundingCalculations.jsx";
import { GroundingPlanDrawer } from "./GroundingPlanDrawer.jsx";
import { AgentArtifactPanel, AgentResultsPanel, ArtifactUpdateCard } from "./AgentArtifact.jsx";
import { KnowledgeGraphWorkspace } from "./KnowledgeGraphWorkspace.jsx";

function HorizontalTabStrip({ children }) {
  const viewport = useRef(null);
  const drag = useRef(null);
  const suppressClick = useRef(false);
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
  return <div className="project-tabs-slider"><button className="project-tabs-arrow" aria-label="Desplazar pestañas a la izquierda" onClick={() => scroll(-1)}><ChevronLeft size={15}/></button><div className="project-tabs-viewport" ref={viewport} onPointerDown={startDrag} onPointerMove={moveDrag} onPointerUp={endDrag} onPointerCancel={endDrag} onClickCapture={(event) => { if (suppressClick.current) { event.preventDefault(); event.stopPropagation(); suppressClick.current = false; } }}>{children}</div><button className="project-tabs-arrow" aria-label="Desplazar pestañas a la derecha" onClick={() => scroll(1)}><ChevronRight size={15}/></button></div>;
}

function ProjectChatWorkspace({ project, token, userId, onBack, onNotice }) {
  const [view, setView] = useState("workspace");
  const [leftSection, setLeftSection] = useState("files");
  const [rightSection, setRightSection] = useState("plan");
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
  const lastArtifactUpdate = useRef(undefined);
  const [error, setError] = useState("");
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
    recordFeatureUse(userId, "files", project.name);
    recordFeatureUse(userId, "plan", project.name);
  }, [project.id, project.name, userId]);
  useEffect(() => () => {
    voiceUnmounted.current = true;
    speechRecognition.current?.abort();
  }, []);
  const request = async (url, options = {}) => {
    const response = await fetch(url, { ...options, headers: { ...auth, ...(options.body ? { "Content-Type": "application/json" } : {}), ...options.headers } });
    const data = response.status === 204 ? null : await response.json();
    if (!response.ok) throw new Error(data?.detail || "No se pudo completar la operación.");
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
    if (agent.seq !== null && data.events.some((e) => e.type === "calculation.completed")) setRightSection("results");
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
        const [existingFiles, convs, memory] = await Promise.all([
          request(`/api/v1/projects/${project.id}/files`),
          request(`/api/v1/projects/${project.id}/conversations`),
          request(`/api/v1/projects/${project.id}/memory`),
        ]);
        if (!live) return;
        setFiles(existingFiles); setConversations(convs); setProjectMemory(memory);
        const current = convs[0] || await request(`/api/v1/projects/${project.id}/conversations`, { method: "POST", body: JSON.stringify({ title: `Refinamiento · ${project.name}` }) });
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
    if (!firstLoad) setRightSection("artifact");
  }, [messages]);
  async function uploadFile(file, retryUploadId = null) {
    const extension = file.name.split(".").pop().toLowerCase();
    const mime = mimeByExtension[extension] || file.type;
    if (!uploadableMimeTypes.has(mime) || file.size > 20 * 1024 * 1024) throw new Error(`${file.name}: usa PDF, DOCX, PNG, JPG, CSV o XLSX de hasta 20 MB.`);
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
        active = await request(`/api/v1/projects/${project.id}/conversations`, { method: "POST", body: JSON.stringify({ title: `Refinamiento · ${project.name}` }) });
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
    <header className="project-chat-topbar"><div className="breadcrumbs"><span className="wordmark">terra<span> / </span></span><button className="project-parent" onClick={onBack}>Proyectos <ChevronRight size={14}/></button><span className="project-name"><span className="project-dot"/>{project.name}</span><span className="project-badge">SPAT</span></div><div className="project-topbar-actions"><div className="artifact-view-tabs project-view-switch" role="tablist" aria-label="Vista del proyecto"><button role="tab" aria-selected={view === "workspace"} className={view === "workspace" ? "active" : ""} onClick={() => activateFeature("workspace", view, setView)}><Sparkles size={14}/> Espacio de trabajo</button><button role="tab" aria-selected={view === "graph"} className={view === "graph" ? "active" : ""} onClick={() => { setView("graph"); if (view !== "graph") recordFeatureUse(userId, "knowledge-graph", project.name); }}><Network size={14}/> Grafo de conocimiento</button></div><button className="button" onClick={onBack}><Layers size={14}/> Todos los proyectos</button></div></header>
    <div className="project-chat-heading"><div><div className="eyebrow">ESPACIO DEL PROYECTO</div><h1>{project.name}</h1><p>{view === "graph" ? "Entidades, afirmaciones y evidencia extraídas de los documentos del proyecto, para revisar y depurar." : project.description || "Archivos de entrada y conversación para refinar los artefactos del proyecto."}</p></div><span className="project-chat-live"><i/> Proyecto activo</span></div>
    {error && <div className="project-error" role="alert">{error}<button onClick={() => setError("")}><X size={14}/></button></div>}
    {view === "graph" ? <KnowledgeGraphWorkspace project={project} token={token}/> : <div className="project-three-col-grid">
    <aside className="project-left-column"><HorizontalTabStrip><div className="project-view-tabs" role="tablist" aria-label="Secciones del proyecto"><button role="tab" aria-selected={leftSection === "files"} className={leftSection === "files" ? "active" : ""} onClick={() => activateFeature("files", leftSection, setLeftSection)}><Layers size={15}/> Archivos</button><button role="tab" aria-selected={leftSection === "measurements"} className={leftSection === "measurements" ? "active" : ""} onClick={() => activateFeature("measurements", leftSection, setLeftSection)}><FileSpreadsheet size={15}/> Mediciones</button><button role="tab" aria-selected={leftSection === "soil"} className={leftSection === "soil" ? "active" : ""} onClick={() => activateFeature("soil", leftSection, setLeftSection)}><Network size={15}/> Modelo suelo</button><button role="tab" aria-selected={leftSection === "safety"} className={leftSection === "safety" ? "active" : ""} onClick={() => activateFeature("safety", leftSection, setLeftSection)}><ShieldCheck size={15}/> Parámetros eléctricos</button></div></HorizontalTabStrip>{leftSection === "files" ? <aside className="panel project-files-panel"><div className="panel-heading"><div><Layers size={17}/><h2>Archivos del proyecto</h2><span className="count">{new Set(files.map((f) => f.filename.toLocaleLowerCase())).size}</span></div><button className="icon-button" title="Cargar archivos" onClick={() => fileInput.current?.click()}><Plus size={17}/></button></div><div className="project-files-list">{files.length ? [...new Map([...files].sort((a, b) => a.updated_at - b.updated_at).map((f) => [f.filename.toLocaleLowerCase(), f])).values()].map((f) => <div className="project-file-row" key={f.upload_id}><span className={`asset-icon ${f.mime_type.startsWith("image/") ? "image" : "document"}`}>{f.mime_type.startsWith("image/") ? <FileImage size={18}/> : <File size={18}/>}</span><span><strong>{f.filename}</strong><small>{f.ocr_needs_review ? `Revisión OCR recomendada · ${Number(f.ocr_confidence ?? 0).toFixed(0)}% de confianza` : uploadStatusLabels[f.status] || f.status}</small>{f.last_error && <small className="upload-error-text">{f.last_error}</small>}{["failed", "expired"].includes(f.status) && <button className="upload-retry-button" disabled={retryingUploads.has(f.upload_id)} onClick={() => { if (f.status === "expired") { expiredRetryId.current = f.upload_id; fileInput.current?.click(); } else retryUpload(f.upload_id); }}>{retryingUploads.has(f.upload_id) ? "Reintentando…" : "Reintentar"}</button>}</span><i className={`asset-dot ${f.status === "failed" || f.status === "rejected" || f.status === "expired" || f.ocr_needs_review ? "error" : f.status !== "available" ? "pending" : ""}`}/></div>) : <div className="empty-assets">Los archivos cargados para este proyecto aparecerán aquí.</div>}</div><button className="upload-area" onClick={() => fileInput.current?.click()}><span><Plus size={16}/></span><strong>Agregar archivos</strong><small>PDF, DOCX, PNG, JPG, CSV o XLSX · máximo 20 MB</small></button><input ref={fileInput} hidden type="file" multiple accept=".pdf,.docx,.png,.jpg,.jpeg,.csv,.xlsx" onChange={(e) => { const filesToAdd = e.target.files; if (expiredRetryId.current) retryExpiredUpload(filesToAdd?.[0]); else addFiles(filesToAdd); e.target.value = ""; }}/><div className="project-chat-files-note"><ShieldCheck size={16}/> Todo archivo pasa por cuarentena y análisis antes de adjuntarse al chat.</div></aside> : <GroundingCalculations project={project} token={token} section={leftSection} files={files} onArtifactSaved={() => setArtifactKey((key) => key + 1)}/>}</aside>
    <div className="project-center-column">
      <section className="panel project-conversation-panel"><div className="panel-heading chat-conversation-heading"><div><Sparkles size={17}/><h2>Refinamiento del artefacto</h2></div><div className="conversation-controls"><select aria-label="Conversaciones del proyecto" value={conversation?.id || ""} onChange={(event) => { const next = conversations.find((item) => item.id === event.target.value); if (next) activateConversation(next).catch((e) => setError(e.message)); }}>{conversations.map((item) => <option value={item.id} key={item.id}>{item.title || "Conversación"}</option>)}</select><button className="button" onClick={createConversation}><Plus size={14}/> Nueva</button></div></div><details className="project-memory"><summary><History size={14}/> Memoria del proyecto · {projectMemory.items?.length || 0}</summary><div>{projectMemory.summary && <p>{projectMemory.summary}</p>}{projectMemory.items?.length ? projectMemory.items.map((item, index) => <p key={`${item.kind}-${index}`}><strong>{item.kind === "decision" ? "Decisión" : item.kind === "assumption" ? "Supuesto" : "Pendiente"}:</strong> {item.text}<small title={(item.source_message_ids || []).join(", ")}> Fuentes: {(item.source_message_ids || []).map((id) => id.slice(0, 8)).join(", ")}</small></p>) : <p>El agente guardará aquí decisiones, supuestos y preguntas con referencia a los mensajes que los originaron.</p>}</div></details><div className="project-chat-messages" ref={messageBox}><button className="load-older" onClick={loadOlder}>Cargar mensajes anteriores</button>{messages.length ? messages.map((m) => m.payload?.kind === "artifact.updated" ? <ArtifactUpdateCard key={m.id} message={m} token={token} project={project} onView={() => setRightSection("artifact")} onUndone={() => setArtifactKey((k) => k + 1)}/> : <article className={`message ${m.source === "user" ? "user" : "assistant"}`} key={m.id}><div className={`message-avatar ${m.source === "user" ? "user" : "assistant"}`}>{m.source === "user" ? `${project.name[0] || "U"}` : <Zap size={15}/>}</div><div className="message-content"><div className="message-author">{m.source === "user" ? "Tú" : m.source === "notification" ? "Notificación" : "Terra"}<span>{new Date(m.created_at * 1000).toLocaleTimeString("es-CO", { hour: "2-digit", minute: "2-digit" })}</span></div>{m.text && <p>{m.text}</p>}{m.contents?.map((c) => <div className="chat-file" key={c.id}>{c.format === "image" ? <FileImage size={13}/> : <Paperclip size={13}/>} {c.filename}</div>)}{["pending", "processing"].includes(m.status) && <div className="chat-processing">{agent.progress ? `${agent.progress}…` : m.status === "pending" ? "En cola…" : "Procesando solicitud…"}<button onClick={() => cancel(m)}>Cancelar</button></div>}</div></article>) : <div className="project-chat-empty"><span><Sparkles size={20}/></span><strong>Inicia el refinamiento</strong><p>Describe qué artefacto quieres ajustar o adjunta archivos de referencia del proyecto.</p></div>}</div><div className="project-chat-composer"><div className="attachment-chips">{attachments.map((a) => <span key={a.id}><Paperclip size={12}/>{a.filename}<small>{a.status === "available" ? "Listo" : a.status === "failed" ? "Error" : "Analizando…"}</small><button aria-label={`Quitar ${a.filename}`} onClick={() => setAttachments((xs) => xs.filter((x) => x.id !== a.id))}><X size={12}/></button></span>)}</div><textarea aria-label="Mensaje para el chat del proyecto" placeholder="Describe el refinamiento que necesitas…" value={draft} readOnly={voiceListening} onChange={(e) => setDraft(e.target.value)} onKeyDown={(e) => { if (!voiceListening && e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendMessage(); } }}/><div className="project-composer-tools"><button className={`icon-button voice-note-button ${voiceListening ? "recording" : ""}`} aria-label={voiceListening ? "Detener nota de voz y enviar" : "Grabar nota de voz"} title={voiceListening ? "Detener y transcribir" : "Grabar nota de voz"} disabled={busy} onClick={startVoiceNote}>{voiceListening ? <Square size={15}/> : <Mic size={17}/>}</button><button className="icon-button" title="Adjuntar imágenes o archivos" onClick={() => fileInput.current?.click()}><Paperclip size={17}/></button><span>{voiceListening ? "Escuchando… el texto se enviará al detener la grabación" : "Los archivos se cargan y analizan antes de enviar"}</span><button className="send-button" disabled={busy || voiceListening || (!draft.trim() && !attachments.some((a) => a.status === "available"))} onClick={sendMessage}>{busy ? <Activity size={17}/> : <ArrowUp size={18}/>}</button></div></div></section>
    </div>
    <div className="artifact-column"><div className="artifact-view-tabs" role="tablist" aria-label="Vista del proyecto"><button role="tab" aria-selected={rightSection === "plan"} className={rightSection === "plan" ? "active" : ""} onClick={() => activateFeature("plan", rightSection, setRightSection)}><Cable size={14}/> Plano</button><button role="tab" aria-selected={rightSection === "artifact"} className={rightSection === "artifact" ? "active" : ""} onClick={() => activateFeature("artifact", rightSection, setRightSection)}><Box size={14}/> Artefacto</button><button role="tab" aria-selected={rightSection === "results"} className={rightSection === "results" ? "active" : ""} onClick={() => activateFeature("results", rightSection, setRightSection)}><Activity size={14}/> Resultados</button></div>{rightSection === "plan" ? <GroundingPlanDrawer key={project.id} projectId={project.id} projectName={project.name} conversation={conversation} token={token}/> : rightSection === "artifact" ? <AgentArtifactPanel project={project} conversation={conversation} token={token} refreshKey={artifactKey}/> : <AgentResultsPanel project={project} conversation={conversation} token={token} refreshKey={artifactKey}/>}</div>
    </div>}
  </main>;
}


export { ProjectChatWorkspace };
