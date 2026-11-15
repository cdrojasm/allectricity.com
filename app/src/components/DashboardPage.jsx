import React, { useEffect, useState } from "react";
import { Activity, ArrowRight, Box, CalendarClock, Layers, Sparkles } from "lucide-react";
import { SystemHealthCard } from "./SystemHealthCard.jsx";
import { DesignStatusBadge } from "../shared.jsx";

const featureNames = {
  workspace: "Espacio de trabajo",
  "knowledge-graph": "Grafo de conocimiento",
  files: "Archivos del proyecto",
  measurements: "Mediciones de resistividad",
  soil: "Modelo de suelo",
  safety: "Parámetros eléctricos",
  plan: "Plano de puesta a tierra",
  artifact: "Artefacto de puesta a tierra",
  results: "Resultados de seguridad",
};

function formatDate(timestamp, includeTime = false) {
  if (!timestamp) return "Sin registro";
  const date = new Date(timestamp > 10_000_000_000 ? timestamp : timestamp * 1000);
  if (!Number.isFinite(date.getTime())) return "Sin registro";
  return date.toLocaleString("es-CO", includeTime
    ? { dateStyle: "medium", timeStyle: "short" }
    : { dateStyle: "medium" });
}

function DashboardPage({ token, user, lastVisit, onOpen, onShowProjects }) {
  const [projects, setProjects] = useState([]);
  const [tokensUsed, setTokensUsed] = useState(null);
  const [features, setFeatures] = useState([]);
  const [error, setError] = useState("");

  useEffect(() => {
    let live = true;
    const headers = { Authorization: `Bearer ${token}` };
    async function load() {
      try {
        const response = await fetch("/api/v1/projects", { headers });
        const data = await response.json();
        if (!response.ok) throw new Error(data.detail || "No se pudieron cargar los proyectos.");
        if (live) setProjects(data.sort((a, b) => (b.updated_at || 0) - (a.updated_at || 0)));
      } catch (e) { if (live) setError(e.message); }
      try {
        const response = await fetch("/api/v1/budgets", { headers });
        if (!response.ok) throw new Error("Consumo no disponible");
        const budgets = await response.json();
        if (live) setTokensUsed(budgets.reduce((sum, budget) => sum + Number(budget.used_tokens || 0), 0));
      } catch { if (live) setTokensUsed(undefined); }
      try {
        const recent = JSON.parse(localStorage.getItem(`terra_recent_features:${user.id}`) || "[]");
        if (live && Array.isArray(recent)) setFeatures(recent.slice(0, 6));
      } catch { if (live) setFeatures([]); }
    }
    load();
    return () => { live = false; };
  }, [token, user.id]);

  // Activity of projects that no longer exist is not shown.
  const visibleFeatures = features.filter((item) => projects.some((project) => project.name === item.projectName));
  return <main className="dashboard-page">
    <header className="dashboard-heading"><div><div className="eyebrow">TERRA WORKSPACE / INICIO</div><h1>Hola, {user.first_name || ""}</h1><p>Resumen de tus proyectos y actividad reciente.</p></div><button className="button primary" onClick={onShowProjects}><Layers size={15}/> Ver proyectos <ArrowRight size={14}/></button></header>
    {error && <div className="project-error" role="alert">{error}</div>}
    <section className="dashboard-metrics" aria-label="Resumen de cuenta">
      <article className="dashboard-metric"><span><Layers size={17}/> Proyectos</span><strong>{projects.length}</strong><small>Proyectos de tu cuenta</small></article>
      <article className="dashboard-metric"><span><Activity size={17}/> Tokens consumidos</span><strong>{tokensUsed === null ? "…" : tokensUsed === undefined ? "—" : Number(tokensUsed).toLocaleString("es-CO")}</strong><small>{tokensUsed === null ? "Cargando consumo…" : tokensUsed === undefined ? "Consumo no disponible para tu cuenta" : "Total registrado en tus presupuestos"}</small></article>
      <article className="dashboard-metric"><span><CalendarClock size={17}/> Última visita</span><strong className="dashboard-date">{formatDate(lastVisit || user.last_login_at)}</strong><small>Fecha de última visita registrada</small></article>
    </section>
    <div className="dashboard-content-grid">
      <section className="dashboard-card dashboard-projects"><div className="dashboard-section-heading"><div><Layers size={17}/><h2>Tus proyectos</h2></div><button className="text-button" onClick={onShowProjects}>Administrar <ArrowRight size={13}/></button></div>
        {projects.length ? <div className="dashboard-project-list">{projects.map((project) => <button className="dashboard-project-row" key={project.id} onClick={() => onOpen(project)}><span className="dashboard-project-mark"><Box size={17}/></span><span className="dashboard-project-info"><strong>{project.name} <DesignStatusBadge status={project.design_status}/></strong><small>{[project.city, project.country].filter(Boolean).join(", ") || project.description || "Sin ubicación"}</small></span><span className="dashboard-project-date">{formatDate(project.updated_at)}<ArrowRight size={14}/></span></button>)}</div> : <div className="dashboard-empty"><Layers size={25}/><strong>Aún no tienes proyectos</strong><span>Crea un proyecto para empezar a trabajar.</span><button className="button" onClick={onShowProjects}>Crear proyecto</button></div>}
      </section>
      <section className="dashboard-card dashboard-activity"><div className="dashboard-section-heading"><div><Sparkles size={17}/><h2>Funciones usadas recientemente</h2></div></div>
        {visibleFeatures.length ? <ul className="dashboard-feature-list">{visibleFeatures.map((item, index) => <li key={`${item.usedAt}-${index}`}><span className="dashboard-feature-icon"><Activity size={15}/></span><span><strong>{featureNames[item.feature] || item.feature}</strong><small>{item.projectName || "Proyecto"} · {formatDate(item.usedAt, true)}</small></span></li>)}</ul> : <div className="dashboard-empty compact"><Sparkles size={23}/><strong>Sin actividad reciente</strong><span>Las funciones que abras aparecerán aquí.</span></div>}
      </section>
      <SystemHealthCard token={token}/>
    </div>
  </main>;
}

export { DashboardPage };
