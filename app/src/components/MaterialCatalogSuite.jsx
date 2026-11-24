import React, { useEffect, useMemo, useRef, useState } from "react";
import { awaitJob } from "../asyncJobs.js";
import { Bot, Check, CheckCircle2, ChevronRight, CircleHelp, ExternalLink, Filter, Globe2, LoaderCircle, MapPin, Package, Plus, Search, Send, ShieldCheck, Sparkles, Trash2, X } from "lucide-react";

const CATEGORIES = ["Material", "Equipo", "Servicio", "Conductor", "Varilla", "Conector", "Soldadura", "Accesorio"];
const SEARCH_GROUP_PREFIX = "Búsqueda guardada: ";
const EMPTY_FORM = {
  name: "", category: "Conductor", material: "Cobre", section: "", price: "", quantity: "", unit: "unidad", currency: "COP",
  structured_options_text: "", contact_email: "", contact_phone: "", contact_whatsapp_url: "", contact_url: "", image_url: "", lead_time: "", lead_time_type: "dispatch",
  supplier: "", source_url: "", source_name: "", country: "", city: "", quoted_at: "", expires_at: "", notes: "",
};

function catalogItem(item) {
  const group = String(item.notes || "").split("\n").find((line) => line.startsWith(SEARCH_GROUP_PREFIX))?.slice(SEARCH_GROUP_PREFIX.length) || "";
  return { ...item, searchGroup: group, section: item.section || item.specification || "", price: item.price_per_unit ?? item.price ?? "",
    currency: (item.price_currency || item.currency || "COP").toUpperCase(), unit: normalizeUnit(item.quantity_unit || item.unit),
    quantity: item.quantity ?? "", source_url: item.source_url || "", captured_at: item.quoted_at || item.captured_at || item.created_at,
    supplier: item.supplier || "", source_type: item.source_type || (item.source_url ? "web" : "manual") };
}

function contactNote(contact = {}) {
  const parts = [
    contact.email && `correo: ${contact.email}`,
    contact.phone && `teléfono: ${contact.phone}`,
    contact.whatsapp_url && `WhatsApp: ${contact.whatsapp_url}`,
    contact.contact_url && `formulario: ${contact.contact_url}`,
    contact.image_url && `imagen: ${contact.image_url}`,
    contact.lead_time && `plazo: ${contact.lead_time}`,
  ].filter(Boolean);
  return parts.length ? `Contacto público: ${parts.join("; ")}` : "";
}

function contactsFromNotes(notes = "") {
  const line = String(notes).split("\n").find((value) => value.startsWith("Contacto público:")) || "";
  const get = (label) => line.match(new RegExp(`${label}: ([^;]+)`))?.[1]?.trim() || "";
  return { email: get("correo"), phone: get("teléfono"), whatsapp_url: get("WhatsApp"), contact_url: get("formulario"), image_url: get("imagen"), lead_time: get("plazo") };
}

function notesWithContacts(notes, contacts) {
  const clean = String(notes || "").split("\n").filter((line) => !line.startsWith("Contacto público:")).join("\n").trim();
  return [clean, contactNote(contacts)].filter(Boolean).join("\n");
}

function apiError(body, status) {
  const detail = body?.detail;
  const message = typeof detail === "string" ? detail : detail?.message;
  if ([502, 503, 504].includes(status)) return `Proveedor de búsqueda no disponible. ${message || "Revisa su configuración e inténtalo de nuevo."}`;
  if (message) return message;
  return `No se pudo completar la solicitud (${status}).`;
}

function displayDate(value) {
  if (!value) return "Fecha sin registrar";
  const date = typeof value === "number" || /^\d+$/.test(String(value)) ? new Date(Number(value) * 1000) : new Date(value);
  return Number.isNaN(date.getTime()) ? "Fecha sin registrar" : date.toLocaleDateString("es-CO");
}

function displayDateTime(value) {
  if (!value) return "Fecha sin registrar";
  const date = typeof value === "number" || /^\d+$/.test(String(value)) ? new Date(Number(value) * 1000) : new Date(value);
  return Number.isNaN(date.getTime()) ? "Fecha sin registrar" : date.toLocaleString("es-CO");
}

const HISTORY_ACTIONS = { created: "Creado", updated: "Actualizado", approved: "Aprobado", unapproved: "Retirado de aprobados", archived: "Archivado" };

function readAssistantHistory(key) {
  try {
    const legacyKey = key.replace("allectricity_material_catalog_", "terra_material_catalog_");
    const raw = localStorage.getItem(key) || localStorage.getItem(legacyKey) || "[]";
    if (!localStorage.getItem(key) && raw !== "[]") localStorage.setItem(key, raw);
    if (localStorage.getItem(legacyKey)) localStorage.removeItem(legacyKey);
    const saved = JSON.parse(raw);
    return Array.isArray(saved) ? saved : [];
  } catch { return []; }
}

function readMigratedItem(key) {
  try {
    const legacyKey = key.replace("allectricity_material_catalog_", "terra_material_catalog_");
    const current = localStorage.getItem(key);
    const legacy = localStorage.getItem(legacyKey);
    if (current !== null) return current;
    if (legacy !== null) {
      localStorage.setItem(key, legacy);
      localStorage.removeItem(legacyKey);
      return legacy;
    }
  } catch { /* storage is optional */ }
  return null;
}

function normalizeUnit(value) {
  const unit = String(value || "unidad").trim().toLowerCase();
  const aliases = { metro: "m", metros: "m", kilogramo: "kg", kilogramos: "kg", pieza: "unidad", piezas: "unidad", und: "unidad" };
  return aliases[unit] || unit;
}

function estimatedTotalsLabel(items) {
  const totals = {};
  items.filter((item) => item.status === "approved" && Number(item.price) > 0 && Number(item.quantity) > 0).forEach((item) => {
    const currency = item.currency || "COP";
    totals[currency] = (totals[currency] || 0) + Number(item.price) * Number(item.quantity);
  });
  const entries = Object.entries(totals);
  return entries.length ? entries.map(([currency, amount]) => money(amount, currency)).join(" · ") : "—";
}

function money(value, currency) {
  if (value === null || value === undefined || value === "" || !Number.isFinite(Number(value))) return "Precio pendiente";
  try { return new Intl.NumberFormat("es-CO", { style: "currency", currency, maximumFractionDigits: 2 }).format(Number(value)); }
  catch { return `${currency} ${value}`; }
}

export function MaterialCatalogSuite({ token, userId, initialProjectId, onNotice }) {
  const storageKey = `allectricity_material_catalog_project_v1:${userId || "local"}`;
  const [tab, setTab] = useState("discover");
  const [location, setLocation] = useState({ country: "Colombia", city: "", radius_km: "100", currency: "COP" });
  const [category, setCategory] = useState("Material");
  const [searchText, setSearchText] = useState("");
  const [maxResults, setMaxResults] = useState(8);
  const [projects, setProjects] = useState([]);
  const [projectId, setProjectId] = useState(() => initialProjectId || readMigratedItem(storageKey) || "");
  const assistantStorageKey = `allectricity_material_catalog_assistant_v1:${userId || "local"}:${projectId || "sin-proyecto"}`;
  const [items, setItems] = useState([]);
  const [estimatedTotal, setEstimatedTotal] = useState(null);
  const [loadingCatalog, setLoadingCatalog] = useState(false);
  const [discoveryMetadata, setDiscoveryMetadata] = useState(null);
  const [busy, setBusy] = useState(false);
  const [discoveryStatus, setDiscoveryStatus] = useState("");
  const [discoveryElapsed, setDiscoveryElapsed] = useState(0);
  const [assistantOpen, setAssistantOpen] = useState(false);
  const [assistantBusy, setAssistantBusy] = useState(false);
  const [assistantError, setAssistantError] = useState("");
  const [assistantDraft, setAssistantDraft] = useState(() => readMigratedItem(`${assistantStorageKey}:draft`) || "");
  const [assistantMessages, setAssistantMessages] = useState(() => readAssistantHistory(assistantStorageKey));
  const [message, setMessage] = useState("");
  const [formOpen, setFormOpen] = useState(false);
  const [editingId, setEditingId] = useState(null);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [historyVersions, setHistoryVersions] = useState([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyError, setHistoryError] = useState("");
  const [form, setForm] = useState(EMPTY_FORM);
  const [query, setQuery] = useState("");
  const [categoryFilter, setCategoryFilter] = useState("");
  const [groupFilter, setGroupFilter] = useState("");
  const [sortBy, setSortBy] = useState("recent");
  const assistantThread = useRef(null);
  const assistantLoadedKey = useRef("");
  const catalogLoadRef = useRef(0);
  const historyLoadRef = useRef(0);
  const discoveryStartedAt = useRef(0);

  useEffect(() => {
    if (!busy || !discoveryStartedAt.current) return undefined;
    const updateElapsed = () => setDiscoveryElapsed(Math.floor((Date.now() - discoveryStartedAt.current) / 1000));
    updateElapsed();
    const timer = window.setInterval(updateElapsed, 1000);
    return () => window.clearInterval(timer);
  }, [busy]);

  const headers = { Authorization: `Bearer ${token}`, "Content-Type": "application/json" };
  const catalogUrl = projectId ? `/api/v1/projects/${encodeURIComponent(projectId)}/material-catalog` : "";
  async function readJson(response) {
    const body = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(apiError(body, response.status));
    return body;
  }
  async function reloadCatalog(id = projectId) {
    if (!id) { setItems([]); setEstimatedTotal(null); return; }
    const requestId = ++catalogLoadRef.current;
    setLoadingCatalog(true);
    try {
      const result = await readJson(await fetch(`/api/v1/projects/${encodeURIComponent(id)}/material-catalog`, { headers }));
      if (requestId === catalogLoadRef.current) { setItems((result.items || []).map(catalogItem)); setEstimatedTotal(result.estimated_total || null); }
    } catch (error) { setMessage(error.message || "No se pudo cargar el inventario del proyecto."); }
    finally { if (requestId === catalogLoadRef.current) setLoadingCatalog(false); }
  }
  async function loadHistory(id = projectId) {
    if (!id) return;
    const requestId = ++historyLoadRef.current;
    setHistoryLoading(true); setHistoryError("");
    try {
      const result = await readJson(await fetch(`/api/v1/projects/${encodeURIComponent(id)}/material-catalog/history?limit=50`, { headers }));
      if (requestId === historyLoadRef.current) setHistoryVersions(result.versions || []);
    } catch (error) { if (requestId === historyLoadRef.current) setHistoryError(error.message || "No se pudo cargar el historial del inventario."); }
    finally { if (requestId === historyLoadRef.current) setHistoryLoading(false); }
  }
  useEffect(() => {
    let active = true;
    fetch("/api/v1/projects", { headers }).then(readJson).then((result) => {
      if (!active) return;
      const list = Array.isArray(result) ? result : result.items || result.projects || [];
      setProjects(list);
      if (projectId && !list.some((project) => String(project.id) === String(projectId))) setProjectId("");
    }).catch((error) => active && setMessage(error.message || "No se pudieron cargar tus proyectos."));
    return () => { active = false; };
  }, [token]);
  useEffect(() => {
    try { projectId ? localStorage.setItem(storageKey, projectId) : localStorage.removeItem(storageKey); } catch { /* storage is optional */ }
    reloadCatalog(projectId);
  }, [projectId, token]);
  useEffect(() => {
    let active = true;
    assistantLoadedKey.current = "";
    if (!projectId) { assistantLoadedKey.current = assistantStorageKey; return () => { active = false; }; }
    fetch(`/api/v1/material-catalog/assistant/conversation?project_id=${encodeURIComponent(projectId)}`, { headers })
      .then(readJson)
      .then((result) => {
        if (!active) return;
        const saved = Array.isArray(result.messages) ? result.messages : [];
        setAssistantMessages(saved.length ? saved : readAssistantHistory(assistantStorageKey));
        assistantLoadedKey.current = assistantStorageKey;
      })
      .catch(() => { if (active) assistantLoadedKey.current = assistantStorageKey; });
    return () => { active = false; };
  }, [projectId, token, userId]);
  useEffect(() => {
    try { localStorage.setItem(assistantStorageKey, JSON.stringify(assistantMessages)); } catch { /* conversation history is best-effort */ }
  }, [assistantStorageKey, assistantMessages]);
  useEffect(() => {
    try { assistantDraft ? localStorage.setItem(`${assistantStorageKey}:draft`, assistantDraft) : localStorage.removeItem(`${assistantStorageKey}:draft`); } catch { /* draft recovery is best-effort */ }
  }, [assistantStorageKey, assistantDraft]);
  useEffect(() => {
    if (!projectId || assistantLoadedKey.current !== assistantStorageKey) return undefined;
    const timer = window.setTimeout(() => {
      fetch(`/api/v1/material-catalog/assistant/conversation?project_id=${encodeURIComponent(projectId)}`, {
        method: "PUT", headers, body: JSON.stringify({ messages: assistantMessages.slice(-100) }),
      }).catch(() => {});
    }, 600);
    return () => window.clearTimeout(timer);
  }, [assistantStorageKey, assistantMessages, projectId, token]);

  function changeProject(nextProjectId) {
    const key = `allectricity_material_catalog_assistant_v1:${userId || "local"}:${nextProjectId || "sin-proyecto"}`;
    setAssistantMessages(readAssistantHistory(key));
    setAssistantDraft(readMigratedItem(`${key}:draft`) || "");
    setProjectId(nextProjectId);
    setItems([]);
    setMessage("");
  }

  const approved = items.filter((item) => item.status === "approved");
  const candidates = items.filter((item) => item.status === "candidate");
  const visible = useMemo(() => {
    const source = tab === "catalog" ? approved : candidates;
    const needle = query.trim().toLocaleLowerCase("es");
    const filtered = source.filter((item) => (!needle || [item.name, item.material, item.supplier, item.city, item.category, item.searchGroup].join(" ").toLocaleLowerCase("es").includes(needle))
      && (!categoryFilter || item.category === categoryFilter) && (!groupFilter || item.searchGroup === groupFilter));
    return filtered.sort((a, b) => {
      if (sortBy === "name") return (a.name || "").localeCompare(b.name || "", "es");
      if (sortBy === "price") {
        const left = a.price === "" || a.price == null ? Number.POSITIVE_INFINITY : Number(a.price);
        const right = b.price === "" || b.price == null ? Number.POSITIVE_INFINITY : Number(b.price);
        return left === right ? 0 : left - right;
      }
      const timestamp = (value) => !value ? 0 : /^\d+$/.test(String(value)) ? Number(value) * (Number(value) < 1e12 ? 1000 : 1) : Date.parse(value) || 0;
      return timestamp(b.captured_at) - timestamp(a.captured_at);
    });
  }, [approved, candidates, query, tab, categoryFilter, groupFilter, sortBy]);
  const searchGroups = [...new Set(items.map((item) => item.searchGroup).filter(Boolean))];
  const catalogCategories = [...new Set(items.map((item) => item.category).filter(Boolean))].sort((a, b) => a.localeCompare(b, "es"));
  const latestVersion = Math.max(0, ...items.map((item) => Number(item.version) || 0));

  useEffect(() => {
    assistantThread.current?.scrollTo({ top: assistantThread.current.scrollHeight, behavior: "smooth" });
  }, [assistantMessages, assistantBusy]);

  async function discover(event) {
    event.preventDefault();
    if (!projectId) { setMessage("Selecciona un proyecto para guardar los resultados del inventario."); return; }
    if (!location.country.trim() || !location.city.trim()) {
      setMessage("Indica el país y la ciudad o región para acotar proveedores cercanos.");
      return;
    }
    setBusy(true); setMessage(""); setDiscoveryElapsed(0); setDiscoveryStatus("Preparando la consulta");
    discoveryStartedAt.current = Date.now();
    try {
      const response = await fetch("/api/v1/material-catalog/discover", {
        method: "POST",
        headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
        body: JSON.stringify({ geography: { ...location, radius_km: Number(location.radius_km) || null, currency: location.currency.toUpperCase() }, category, query: searchText.trim() || category, max_results: Number(maxResults) }),
      });
      const queued = await readJson(response);
      setDiscoveryStatus("En cola");
      let body;
      while (true) {
        await new Promise((resolve) => window.setTimeout(resolve, queued.poll_after_ms || 1200));
        const job = await readJson(await fetch(`/api/v1/material-catalog/discover/${encodeURIComponent(queued.job_id)}`, { headers }));
        setDiscoveryStatus(job.status === "queued" ? "En cola para iniciar" : job.status === "running" ? "Buscando en fuentes web" : "");
        if (job.status === "completed") { body = job.result || {}; break; }
        if (job.status === "failed") throw new Error(job.error || "Falló la búsqueda de proveedores.");
      }
      const results = body.results || body.candidates || [];
      const searchGroup = `${(searchText.trim() || category).slice(0, 120)} · ${location.city}, ${location.country}`;
      const found = [];
      let skipped = 0;
      let saveErrors = 0;
      for (const item of results) {
        const name = item.name || item.title;
        const sourceUrl = item.source_url || item.url;
        if (!name || !sourceUrl) { skipped += 1; continue; }
        const payload = { name, category, material: item.material || "",
          specification: item.section || item.specification || "Pendiente de validar en la fuente.", quantity: null, quantity_unit: item.unit ? normalizeUnit(item.unit) : null,
          quantity_basis: null, price_per_unit: item.price ?? null, price_currency: (item.currency || location.currency).toUpperCase(),
          supplier: item.supplier || null, source_url: sourceUrl,
          source_name: item.source_name || body.metadata?.provider || null,
          country: location.country, city: location.city,
          quoted_at: Math.floor(new Date(item.captured_at || body.metadata?.captured_at || Date.now()).getTime() / 1000), expires_at: null,
          notes: notesWithContacts([item.notes, `${SEARCH_GROUP_PREFIX}${searchGroup}`].filter(Boolean).join("\n"), { email: item.contact_email, phone: item.contact_phone,
            whatsapp_url: item.contact_whatsapp_url, contact_url: item.contact_url, image_url: item.image_url, lead_time: item.lead_time }) || null };
        try {
          const saved = await readJson(await fetch(catalogUrl, { method: "POST", headers, body: JSON.stringify(payload) }));
          found.push(catalogItem(saved));
        } catch { saveErrors += 1; }
      }
      await reloadCatalog();
      setDiscoveryMetadata(body.metadata || null);
      setTab("discover");
      setMessage(found.length ? `${found.length} leads guardados en este proyecto.${saveErrors ? ` ${saveErrors} no se pudieron guardar.` : ""}${skipped ? ` ${skipped} se descartaron por no tener título o URL.` : ""} Son resultados web, no cotizaciones verificadas; confirma precios y disponibilidad con cada proveedor.` : results.length ? `No se guardaron resultados.${saveErrors ? ` Falló el guardado de ${saveErrors};` : ""} ${skipped ? `${skipped} no tenían título o URL verificable.` : "Revisa permisos de edición del proyecto."}` : "La búsqueda no encontró resultados en las fuentes disponibles.");
    } catch (error) {
      setMessage(error.message || "No se pudo conectar con el servicio de búsqueda.");
    } finally { setBusy(false); setDiscoveryStatus(""); discoveryStartedAt.current = 0; }
  }

  async function saveCandidate(event) {
    event.preventDefault();
    const normalizedPrice = form.price === "" ? null : Number(form.price);
    if (!projectId) { setMessage("Selecciona un proyecto antes de guardar."); return; }
    if (!form.name.trim() || (normalizedPrice !== null && (!Number.isFinite(normalizedPrice) || normalizedPrice <= 0))) {
      setMessage("Agrega el nombre del producto y, si tienes una cotización, un precio positivo por unidad.");
      return;
    }
    if ((normalizedPrice !== null || form.supplier.trim()) && !form.source_url.trim() && !form.notes.trim()) {
      setMessage("Para guardar precio o proveedor, agrega una URL o nota que permita rastrear la fuente.");
      return;
    }
    setBusy(true);
    try {
      const original = items.find((item) => item.id === editingId);
      const payload = { name: form.name.trim(), category: form.category,
        material: form.material, specification: form.section || "Pendiente de especificar", quantity: form.quantity === "" ? null : Number(form.quantity), quantity_unit: form.unit,
        quantity_basis: form.quantity === "" ? null : `${form.quantity} ${form.unit}`, price_per_unit: normalizedPrice,
        price_currency: form.currency.toUpperCase(), supplier: form.supplier || null, source_url: form.source_url || null,
        structured_options: original?.structured_options || null,
        country: form.country || location.country, city: form.city || location.city,
        source_name: form.source_name || null, quoted_at: form.quoted_at ? Math.floor(new Date(form.quoted_at).getTime() / 1000) : Math.floor(Date.now() / 1000),
        expires_at: form.expires_at ? Math.floor(new Date(form.expires_at).getTime() / 1000) : null,
        notes: notesWithContacts(form.notes, { email: form.contact_email, phone: form.contact_phone, whatsapp_url: form.contact_whatsapp_url, contact_url: form.contact_url, image_url: form.image_url, lead_time: form.lead_time }) || null };
      const saved = await readJson(await fetch(editingId ? `${catalogUrl}/${encodeURIComponent(editingId)}` : catalogUrl, { method: editingId ? "PATCH" : "POST", headers, body: JSON.stringify(payload) }));
      setItems((current) => [catalogItem(saved), ...current]); await reloadCatalog();
      setForm(EMPTY_FORM); setEditingId(null); setFormOpen(false); setTab("discover"); setMessage(editingId ? "Cotización actualizada en el proyecto." : "Renglón guardado en el proyecto como candidato. Verifica su fuente antes de aprobarlo.");
    } catch (error) { setMessage(error.message || "No se pudo guardar el renglón."); }
    finally { setBusy(false); }
  }

  async function approve(id) {
    const candidate = items.find((item) => item.id === id);
    if (!Number.isFinite(Number(candidate?.price)) || Number(candidate?.price) <= 0 || !candidate?.supplier?.trim() || (!candidate.source_url?.trim() && !candidate.notes?.trim())) {
      setMessage("Para aprobar una cotización registra precio, proveedor y fuente rastreable. Los leads web sin precio siguen como candidatos.");
      return;
    }
    try { await readJson(await fetch(`${catalogUrl}/${encodeURIComponent(id)}/approval`, { method: "POST", headers, body: JSON.stringify({ approved: true }) })); await reloadCatalog(); onNotice?.("Cotización aprobada en el catálogo del proyecto."); }
    catch (error) { setMessage(error.message || "No se pudo aprobar el material."); }
  }
  async function remove(id) {
    try { await readJson(await fetch(`${catalogUrl}/${encodeURIComponent(id)}`, { method: "DELETE", headers })); await reloadCatalog(); }
    catch (error) { setMessage(error.message || "No se pudo retirar el material."); }
  }

  function editCandidate(item) {
    const toDateInput = (value) => {
      if (!value) return "";
      const date = typeof value === "number" || /^\d+$/.test(String(value)) ? new Date(Number(value) * 1000) : new Date(value);
      return Number.isNaN(date.getTime()) ? "" : date.toISOString().slice(0, 10);
    };
    const contacts = contactsFromNotes(item.notes);
    setEditingId(item.id);
    setForm({ ...EMPTY_FORM, name: item.name || "", category: item.category || "Accesorio", material: item.material || "",
      section: item.section || "", price: item.price ?? "", quantity: item.quantity ?? "", unit: item.unit || "unidad",
      structured_options_text: "", contact_email: contacts.email, contact_phone: contacts.phone, contact_whatsapp_url: contacts.whatsapp_url,
      contact_url: contacts.contact_url, image_url: contacts.image_url, lead_time: contacts.lead_time,
      currency: item.currency || location.currency, supplier: item.supplier || "", source_url: item.source_url || "",
      source_name: item.source_name || "", country: item.country || location.country, city: item.city || location.city,
      quoted_at: toDateInput(item.quoted_at || item.captured_at), expires_at: toDateInput(item.expires_at), notes: item.notes || "" });
    setFormOpen(true);
  }

  async function askAssistant(textOverride = assistantDraft) {
    const content = textOverride.trim();
    if (!content || assistantBusy) return;
    const nextMessages = [...assistantMessages, { role: "user", content }].slice(-16);
    setAssistantMessages(nextMessages); setAssistantDraft(""); setAssistantBusy(true); setAssistantError("");
    try {
      const response = await fetch("/api/v1/material-catalog/assistant", {
        method: "POST",
        headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
        body: JSON.stringify({ geography: location, design_context: "El usuario está preparando cotizaciones de materiales para un sistema de puesta a tierra.", messages: nextMessages }),
      });
      const accepted = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(accepted.detail || "No se pudo consultar al asistente.");
      const body = await awaitJob(token, accepted);
      setAssistantMessages((current) => [...current, { role: "assistant", content: body.reply, questions: body.questions || [], recommendations: body.recommendations || [] }]);
    } catch (error) {
      setAssistantError(error.message || "El asistente no está disponible en este momento.");
    } finally { setAssistantBusy(false); }
  }

  function prepareRecommendation(item) {
    setForm({ ...EMPTY_FORM, name: item.name || item.specification || "", category: item.category || "Accesorio",
      material: item.material || "", currency: location.currency, country: location.country, city: location.city,
      notes: [item.specification, item.quantity_basis && `Cantidad: ${item.quantity_basis}`, item.why && `Compatibilidad: ${item.why}`].filter(Boolean).join("\n") });
    setFormOpen(true);
  }

  return <main className="catalog-suite">
    <header className="catalog-topbar">
      <div className="catalog-breadcrumb"><span>Allectricity</span><ChevronRight size={14}/><strong>Catálogo de materiales</strong></div>
      <div className="catalog-topbar-actions"><div className="catalog-version-wrap"><button className="catalog-version-chip" aria-expanded={historyOpen} disabled={!projectId} onClick={() => { const opening = !historyOpen; setHistoryOpen(opening); if (opening) loadHistory(); }}>Historial · {items.length} renglones</button>{historyOpen && <div className="catalog-version-popover"><strong>Historial del inventario</strong>{historyLoading ? <p>Cargando historial…</p> : historyError ? <div role="alert"><p>{historyError}</p><button className="button" onClick={() => loadHistory()}>Reintentar</button></div> : historyVersions.length ? historyVersions.map((version) => { const snapshot = version.snapshot || {}; const specification = [snapshot.material, snapshot.specification, snapshot.quantity != null ? `${snapshot.quantity} ${snapshot.quantity_unit || ""}`.trim() : ""].filter(Boolean).join(" · "); const evidence = [displayDateTime(version.created_at), specification, snapshot.price_per_unit != null ? money(snapshot.price_per_unit, snapshot.price_currency || "COP") : "Precio pendiente", snapshot.supplier].filter(Boolean).join(" · "); return <div key={version.id || `${version.item_id}-${version.version}`}><span>v{version.version} · {HISTORY_ACTIONS[version.action] || version.action} · {snapshot.name || "Material"}</span><small>{evidence}</small></div>; }) : <p>Aún no hay cambios registrados.</p>}</div>}</div><div className="catalog-scope"><Globe2 size={15}/>{location.city ? `${location.city}, ${location.country}` : location.country || "Define una ubicación"}</div></div>
    </header>

    <section className="catalog-heading">
      <div><div className="eyebrow">CATÁLOGO DE MATERIALES</div><h1>Catálogo de materiales y servicios</h1><p>Guarda referencias para reutilizarlas en tus proyectos y registra precios con su fuente.</p></div>
      <div className="catalog-heading-actions" style={{ display: "flex", alignItems: "end", gap: 10 }}><label className="catalog-project-select" style={{ display: "grid", gap: 5, color: "#64736f", fontSize: 10 }}>Proyecto<select style={{ minWidth: 190, height: 36, border: "1px solid #dfe5e7", borderRadius: 6, padding: "0 9px", background: "white" }} value={projectId} onChange={(event) => changeProject(event.target.value)}><option value="">Seleccionar proyecto…</option>{projects.map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}</select></label><button className="button primary" disabled={!projectId} onClick={() => { setEditingId(null); setForm(EMPTY_FORM); setFormOpen(true); }}><Plus size={15}/>Agregar cotización</button></div>
    </section>

    <div className="catalog-metrics">
      <div className="catalog-metric"><span>Materiales aprobados</span><strong>{approved.length}</strong><small><CheckCircle2 size={13}/>Listos para estimar</small></div>
      <div className="catalog-metric"><span>Por revisar</span><strong>{candidates.length}</strong><small><ShieldCheck size={13}/>Requieren validación</small></div>
      <div className="catalog-metric"><span>Ubicación activa</span><strong className="catalog-location-value">{location.city || "Sin definir"}</strong><small><MapPin size={13}/>{location.country || "Selecciona región"}</small></div>
      <div className="catalog-metric"><span>Total estimado</span><strong>{estimatedTotal ? money(estimatedTotal.amount, estimatedTotal.currency) : estimatedTotalsLabel(items)}</strong><small>{estimatedTotal ? `Cantidades cotizadas · ${estimatedTotal.currency}` : "Total por moneda, sin conversión artificial"}</small></div>
    </div>

    <section className="catalog-search-card">
      <div className="catalog-search-intro"><span className="catalog-icon-tile"><Sparkles size={18}/></span><div><h2>Búsqueda asistida por ubicación</h2><p>Configura la zona y el material. Los resultados siempre entran como candidatos hasta que revises la fuente.</p></div></div>
      <form className="catalog-search-form" onSubmit={discover}>
        <label>País<input value={location.country} onChange={(e) => setLocation({ ...location, country: e.target.value })} placeholder="Colombia" required/></label>
        <label>Ciudad o región<input value={location.city} onChange={(e) => setLocation({ ...location, city: e.target.value })} placeholder="Medellín" required/></label>
        <label>Radio<select value={location.radius_km} onChange={(e) => setLocation({ ...location, radius_km: e.target.value })}><option value="25">25 km</option><option value="50">50 km</option><option value="100">100 km</option><option value="250">250 km</option></select></label>
        <label>Moneda<select value={location.currency} onChange={(e) => setLocation({ ...location, currency: e.target.value })}><option value="COP">COP · Peso colombiano</option><option value="USD">USD · Dólar</option><option value="MXN">MXN · Peso mexicano</option><option value="PEN">PEN · Sol</option><option value="CLP">CLP · Peso chileno</option><option value="BRL">BRL · Real</option></select></label>
        <label>Tipo de referencia<select value={category} onChange={(e) => setCategory(e.target.value)}>{CATEGORIES.map((item) => <option key={item}>{item}</option>)}</select></label>
        <label className="catalog-form-wide">¿Qué necesitas encontrar?<input value={searchText} onChange={(e) => setSearchText(e.target.value)} placeholder="Ej.: bomba centrífuga 5 HP, cable THHN 12 AWG o excavación manual"/></label>
        <label>Resultados<select value={maxResults} onChange={(e) => setMaxResults(Number(e.target.value))}><option value={3}>3 resultados</option><option value={5}>5 resultados</option><option value={8}>8 resultados</option><option value={10}>10 resultados</option></select></label>
        <button className="button primary catalog-discover-button" type="submit" disabled={busy}><Search size={15}/>{busy ? `${discoveryStatus || "Iniciando búsqueda"}…` : "Buscar proveedores"}</button>
      </form>
      {busy && <div className="catalog-discovery-progress" role="status" aria-live="polite">
        <LoaderCircle size={17} className="catalog-discovery-spinner" />
        <div><strong>{discoveryStatus || "Iniciando búsqueda"}</strong><p>{discoveryElapsed < 8 ? "Estamos conectando con el proveedor de búsqueda." : discoveryElapsed < 30 ? "La consulta sigue activa; estamos esperando resultados de las fuentes disponibles." : "La búsqueda está tardando más de lo habitual. La pantalla sigue consultando y te avisará cuando termine o si ocurre un error."}</p></div>
        <span>{discoveryElapsed} s</span>
      </div>}
      {message && <div className="catalog-message" role="status"><CircleHelp size={15}/><span>{message}</span><button aria-label="Cerrar aviso" onClick={() => setMessage("")}><X size={14}/></button></div>}
      <div className="catalog-search-foot"><span><Sparkles size={13}/>{discoveryMetadata ? `Fuente: ${discoveryMetadata.provider || "buscador web"} · ${discoveryMetadata.result_count ?? 0} resultados. Son leads, no cotizaciones verificadas.` : "Los resultados dependen del proveedor de búsqueda configurado; no se generan precios ni disponibilidad."}</span><span>Radio de búsqueda: {location.radius_km} km</span></div>
    </section>

    {assistantOpen && <div className="catalog-agent-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) setAssistantOpen(false); }}><section className="catalog-agent-card" role="dialog" aria-modal="true" aria-label="Agente de cotización">
      <header className="catalog-agent-header"><span className="catalog-agent-avatar"><Bot size={18}/></span><div><h2>Agente de cotización</h2><p>Cuéntame sobre el diseño y te ayudo a convertirlo en materiales concretos para cotizar.</p></div><span className="catalog-agent-badge"><Sparkles size={12}/>Asistencia técnica</span><button className="icon-button" aria-label="Cerrar agente" onClick={() => setAssistantOpen(false)}><X size={17}/></button></header>
      <div className="catalog-agent-thread" ref={assistantThread} aria-live="polite">
        {!assistantMessages.length && <div className="catalog-agent-welcome"><strong>¡Hola! Te ayudo a preparar la lista de materiales.</strong><p>Puedo hacerte preguntas sobre la malla, revisar especificaciones que ya tengas y sugerir renglones para cotizar. No invento precios ni disponibilidad.</p><div className="catalog-agent-prompts"><button onClick={() => askAssistant("Ey, quiero que me ayudes a cotizar los materiales para una puesta a tierra.")}>Ayúdame a cotizar una puesta a tierra</button><button onClick={() => askAssistant("Tengo una malla diseñada y quiero convertirla en una lista de materiales para cotizar.")}>Ya tengo una malla diseñada</button></div></div>}
        {assistantMessages.map((message, index) => <article className={`catalog-agent-message ${message.role}`} key={`${message.role}-${index}`}><span className="catalog-message-avatar">{message.role === "assistant" ? <Bot size={14}/> : "Tú"}</span><div className="catalog-message-body"><p>{message.content}</p>{message.recommendations?.length > 0 && <div className="catalog-recommendations">{message.recommendations.map((item, recommendationIndex) => <div className="catalog-recommendation" key={`${item.name}-${recommendationIndex}`}><div className="catalog-recommendation-heading"><strong>{item.name}</strong><span>{item.category}</span></div><p>{item.specification}</p><small>{item.material}{item.quantity_basis ? ` · Cantidad: ${item.quantity_basis}` : ""}</small>{item.why && <small className="catalog-recommendation-why">{item.why}</small>}<button className="button" onClick={() => prepareRecommendation(item)}><Plus size={13}/>Preparar cotización</button></div>)}</div>}{message.questions?.map((question, questionIndex) => <small className="catalog-agent-question" key={questionIndex}>{question}</small>)}</div></article>)}
        {assistantBusy && <div className="catalog-agent-thinking"><LoaderCircle size={15}/>Revisando los datos del diseño…</div>}
      </div>
      {assistantError && <div className="catalog-agent-error" role="alert"><CircleHelp size={14}/>{assistantError}</div>}
      <form className="catalog-agent-composer" onSubmit={(event) => { event.preventDefault(); askAssistant(); }}><textarea aria-label="Mensaje para el agente de cotización" rows="2" value={assistantDraft} onChange={(event) => setAssistantDraft(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); askAssistant(); } }} placeholder="Ej.: tengo una malla de 30 × 20 m, cobre 2/0 AWG, varillas de 2,4 m…"/><button className="button primary" type="submit" disabled={assistantBusy || !assistantDraft.trim()}>{assistantBusy ? <LoaderCircle size={15}/> : <Send size={15}/>}Enviar</button></form>
      <div className="catalog-agent-foot"><ShieldCheck size={13}/>Las recomendaciones son borradores técnicos. Confirma el dimensionamiento y agrega fuentes/precios antes de aprobar.</div>
    </section></div>}
    <button className="catalog-agent-launcher" onClick={() => setAssistantOpen(true)} aria-label="Abrir agente cotizador"><Bot size={17}/>Agente cotizador</button>

    <section className="catalog-list-section">
      <div className="catalog-list-header"><div className="catalog-tabs" role="tablist" aria-label="Materiales"><button className={tab === "discover" ? "active" : ""} role="tab" aria-selected={tab === "discover"} onClick={() => { setTab("discover"); setQuery(""); }}>Candidatos <span>{candidates.length}</span></button><button className={tab === "catalog" ? "active" : ""} role="tab" aria-selected={tab === "catalog"} onClick={() => { setTab("catalog"); setQuery(""); }}>Catálogo aprobado <span>{approved.length}</span></button></div>
        <div className="catalog-list-tools"><label className="catalog-filter"><Search size={14}/><input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Buscar material o proveedor"/><Filter size={13}/></label>
          <select aria-label="Filtrar por búsqueda" value={groupFilter} onChange={(e) => setGroupFilter(e.target.value)}><option value="">Todas las búsquedas</option>{searchGroups.map((group) => <option key={group} value={group}>{group}</option>)}</select>
          <select aria-label="Filtrar por tipo" value={categoryFilter} onChange={(e) => setCategoryFilter(e.target.value)}><option value="">Todos los tipos</option>{catalogCategories.map((value) => <option key={value}>{value}</option>)}</select>
          <select aria-label="Ordenar materiales" value={sortBy} onChange={(e) => setSortBy(e.target.value)}><option value="recent">Más recientes</option><option value="name">Nombre A–Z</option><option value="price">Precio menor</option></select></div></div>
      {!projectId ? <div className="catalog-empty"><span className="catalog-empty-icon"><Package size={20}/></span><h3>Selecciona un proyecto</h3><p>El inventario y sus cotizaciones se guardan por proyecto.</p></div> : loadingCatalog ? <div className="catalog-empty"><LoaderCircle size={20}/><p>Cargando inventario…</p></div> : visible.length ? <div className="catalog-items">{visible.map((item) => {
        const expired = item.expires_at && new Date(Number(item.expires_at) * 1000) < new Date();
        return <article className="catalog-item" key={item.id}>
        <div className="catalog-item-mark"><Package size={18}/></div><div className="catalog-item-main"><div className="catalog-item-title"><h3 title={item.name || "Material sin nombre"}>{item.name || "Material sin nombre"}</h3><span className={`catalog-status ${item.status}`} title={item.status === "approved" ? "Material aprobado para reutilizar" : "Candidato pendiente de validación de fuente y precio"}>{item.status === "approved" ? "Aprobado" : "Por revisar"}</span></div>
          {item.searchGroup && <small className="catalog-item-search-group" title={item.searchGroup}>Búsqueda: {item.searchGroup}</small>}
          <p>{[item.material, item.section, item.category].filter(Boolean).join(" · ")}</p><div className="catalog-item-meta"><span><MapPin size={12}/>{[item.city, item.country].filter(Boolean).join(", ") || "Ubicación sin registrar"}</span>{item.supplier && <span>{item.supplier}</span>}<span>{displayDate(item.captured_at)}</span>{item.expires_at && <span>{expired ? "Cotización vencida" : `Vigente hasta ${displayDate(item.expires_at)}`}</span>}{item.source_url && <a href={item.source_url} target="_blank" rel="noreferrer">Ver fuente <ExternalLink size={11}/></a>}{item.source_name && <span>Fuente: {item.source_name}</span>}</div>
          {(() => { const contacts = contactsFromNotes(item.notes); return (Object.values(contacts).some(Boolean) || contacts.lead_time) && <div className="catalog-item-contacts"><strong>Contacto y disponibilidad</strong>{contacts.email && <a href={`mailto:${contacts.email}?subject=${encodeURIComponent(`Consulta: ${item.name}`)}`}>Email: {contacts.email}</a>}{contacts.phone && <a href={`tel:${contacts.phone.replace(/[^+\d]/g, "")}`}>Llamar: {contacts.phone}</a>}{contacts.whatsapp_url && <a href={contacts.whatsapp_url} target="_blank" rel="noreferrer">Abrir WhatsApp</a>}{contacts.contact_url && <a href={contacts.contact_url} target="_blank" rel="noreferrer">Formulario del proveedor</a>}{contacts.lead_time && <span>{contacts.lead_time}</span>}{contacts.image_url && <a href={contacts.image_url} target="_blank" rel="noreferrer">Ver imagen del producto</a>}</div>; })()}
        </div><div className="catalog-item-price"><strong>{money(item.price, item.currency || location.currency)}</strong><span>{item.quantity ? `${item.quantity} ${item.unit || "unidad"} · ${money(Number(item.price) * Number(item.quantity), item.currency || location.currency)} total` : `por ${item.unit || "unidad"}`}</span></div>
        <div className="catalog-item-actions">{item.status === "candidate" && <><button className="button" onClick={() => editCandidate(item)}>Editar</button><button className="button approve-button" disabled={expired || !item.price || !item.supplier} title={!item.price ? "Agrega un precio confirmado para aprobar" : expired ? "Actualiza la cotización vencida" : undefined} onClick={() => approve(item.id)}><Check size={14}/>Aprobar</button></>}<button className="icon-button catalog-remove" aria-label="Eliminar material" title="Eliminar" onClick={() => remove(item.id)}><Trash2 size={15}/></button></div>
      </article>;})}</div> : <div className="catalog-empty"><span className="catalog-empty-icon">{tab === "catalog" ? <Package size={20}/> : <Search size={20}/>}</span><h3>{tab === "catalog" ? "Tu catálogo aprobado empieza aquí" : "No hay candidatos para revisar"}</h3><p>{tab === "catalog" ? "Aprueba materiales con una fuente y un precio verificables para que estén listos para estimar." : "Busca proveedores por región o registra una cotización que ya tengas."}</p><button className="button" disabled={!projectId} onClick={() => { setForm(EMPTY_FORM); setFormOpen(true); }}><Plus size={14}/>Registrar cotización</button></div>}
    </section>

    <footer className="catalog-footer"><span><ShieldCheck size={14}/>Cada precio conserva proveedor, ubicación, moneda, unidad y fecha.</span><span>Los costos instalados se añadirán en una etapa posterior.</span></footer>

    {formOpen && <div className="catalog-modal-backdrop" role="presentation" onMouseDown={(e) => { if (e.target === e.currentTarget) setFormOpen(false); }}><section className="catalog-modal" role="dialog" aria-modal="true" aria-labelledby="catalog-modal-title">
      <header><div><div className="eyebrow">REGISTRO DE FUENTE</div><h2 id="catalog-modal-title">{editingId ? "Actualizar cotización" : "Agregar cotización"}</h2><p>Los datos se guardan en el proyecto. Registra precio y fuente solo si puedes sustentarlos.</p></div><button className="icon-button" aria-label="Cerrar" onClick={() => { setFormOpen(false); setEditingId(null); }}><X size={17}/></button></header>
      <form onSubmit={saveCandidate}>
        <label className="catalog-form-wide">Nombre del producto<input autoFocus required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="Conductor de cobre desnudo"/></label>
        <label>Tipo<select value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })}>{CATEGORIES.map((item) => <option key={item}>{item}</option>)}</select></label>
        <label>Material<input value={form.material} onChange={(e) => setForm({ ...form, material: e.target.value })} placeholder="Cobre"/></label>
        <label>Sección / referencia<input value={form.section} onChange={(e) => setForm({ ...form, section: e.target.value })} placeholder="2/0 AWG · 67,4 mm²"/></label>
        <label>Precio por unidad<div className="catalog-price-fields"><input type="number" min="0.01" step="any" value={form.price} onChange={(e) => setForm({ ...form, price: e.target.value })} placeholder="Opcional"/><select value={form.currency} onChange={(e) => setForm({ ...form, currency: e.target.value })}><option>COP</option><option>USD</option><option>MXN</option><option>PEN</option><option>CLP</option><option>BRL</option></select></div></label>
        <label>Cantidad estimada<input type="number" min="0.001" step="any" value={form.quantity} onChange={(e) => setForm({ ...form, quantity: e.target.value })} placeholder="Opcional"/></label>
        <label>Unidad de compra<select value={form.unit} onChange={(e) => setForm({ ...form, unit: e.target.value })}><option value="unidad">Unidad (und)</option><option value="m">Metro (m)</option><option value="kg">Kilogramo (kg)</option><option value="hora">Hora (h)</option><option value="día">Día</option><option value="m2">Metro cuadrado (m²)</option><option value="m3">Metro cúbico (m³)</option><option value="viaje">Viaje</option><option value="rollo">Rollo</option><option value="kit">Kit</option></select></label>
        {form.category === "Servicio" && <label>Forma de cobro<select value={form.unit === "servicio" ? "unique" : "measured"} onChange={(e) => setForm({ ...form, quantity: "1", unit: e.target.value === "unique" ? "servicio" : "hora", notes: e.target.value === "unique" ? "Alcance: servicio único; confirma entregables y duración en las notas." : "Servicio medido; especifica alcance, criterio de aceptación y duración en las notas." })}><option value="unique">Por un servicio completo</option><option value="measured">Por unidad ejecutada (hora, m², m³…)</option></select></label>}
        <label>Proveedor<input value={form.supplier} onChange={(e) => setForm({ ...form, supplier: e.target.value })} placeholder="Pendiente de confirmar"/></label>
        <label>Ciudad<input value={form.city} onChange={(e) => setForm({ ...form, city: e.target.value })} placeholder={location.city || "Ciudad"}/></label>
        <label className="catalog-form-wide">URL de la fuente<input type="url" value={form.source_url} onChange={(e) => setForm({ ...form, source_url: e.target.value })} placeholder="https://proveedor.com/producto"/></label>
        <label>Email<input type="email" value={form.contact_email} onChange={(e) => setForm({ ...form, contact_email: e.target.value })} placeholder="ventas@proveedor.com"/></label>
        <label>Teléfono<input type="tel" value={form.contact_phone} onChange={(e) => setForm({ ...form, contact_phone: e.target.value })} placeholder="+57…"/></label>
        <label>Enlace de WhatsApp<input type="url" value={form.contact_whatsapp_url} onChange={(e) => setForm({ ...form, contact_whatsapp_url: e.target.value })} placeholder="https://wa.me/…"/></label>
        <label>Imagen de referencia<input type="url" value={form.image_url} onChange={(e) => setForm({ ...form, image_url: e.target.value })} placeholder="URL pública de imagen"/></label>
        <label>Plazo informado<input value={form.lead_time} onChange={(e) => setForm({ ...form, lead_time: e.target.value })} placeholder={form.category === "Servicio" ? "Duración: 2 días; espera: 1 semana" : "Disponible; despacho en 3–5 días"}/></label>
        <label>Fecha de cotización<input type="date" value={form.quoted_at} onChange={(e) => setForm({ ...form, quoted_at: e.target.value })}/></label>
        <label>Válida hasta<input type="date" value={form.expires_at} onChange={(e) => setForm({ ...form, expires_at: e.target.value })}/></label>
        <label className="catalog-form-wide">Notas<textarea rows="2" value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} placeholder="Impuestos, disponibilidad, cantidad mínima…"/></label>
        <div className="catalog-modal-actions"><button className="button" type="button" onClick={() => { setFormOpen(false); setEditingId(null); }}>Cancelar</button><button className="button primary" type="submit" disabled={busy}>{busy ? <LoaderCircle size={14}/> : <Plus size={14}/>}Guardar candidato</button></div>
      </form>
    </section></div>}
  </main>;
}
