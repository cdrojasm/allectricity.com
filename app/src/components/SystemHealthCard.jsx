import React, { useCallback, useEffect, useState } from "react";
import { HeartPulse, RotateCcw } from "lucide-react";

const statusLabels = { ok: "Operativo", error: "Con fallo", disabled: "No configurado" };

function SystemHealthCard({ token, isSuperAdmin = false }) {
  const [health, setHealth] = useState(null);
  const [error, setError] = useState("");
  const [checking, setChecking] = useState(false);

  const check = useCallback(async () => {
    setChecking(true);
    setError("");
    try {
      const headers = { Authorization: `Bearer ${token}` };
      const response = await fetch("/api/v1/system/health", { headers });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "No se pudo consultar el estado del sistema.");
      setHealth(data);
    } catch (e) {
      setHealth(null);
      setError(e.message || "La API no responde.");
    } finally {
      setChecking(false);
    }
  }, [token]);

  useEffect(() => {
    check();
    const timer = setInterval(check, 60_000);
    return () => clearInterval(timer);
  }, [check]);

  const overall = error ? "error" : health?.status;
  return <section className="dashboard-card system-health-card" aria-label="Estado del sistema">
    <div className="dashboard-section-heading">
      <div><HeartPulse size={17}/><h2>Estado del sistema</h2></div>
      <span className={`system-health-badge ${overall || "pending"}`}>{overall === "ok" ? "Todo operativo" : overall === "degraded" ? "Degradado" : overall === "error" ? "Sin conexión" : "Verificando…"}</span>
    </div>
    {error && <p className="system-health-error" role="alert">{error}</p>}
    {isSuperAdmin && health && <ul className="system-health-list">{health.components.map((component) => <li key={component.id}>
      <i className={`asset-dot ${component.status === "ok" ? "" : component.status === "disabled" ? "pending" : "error"}`}/>
      <span><strong>{component.label}</strong>{component.detail && <small>{component.detail}</small>}</span>
      <em>{statusLabels[component.status] || component.status} · {component.latency_ms} ms</em>
    </li>)}</ul>}
    <div className="system-health-footer">
      {isSuperAdmin ? <small>{health ? `Versión ${health.version} · ${new Date(health.checked_at * 1000).toLocaleTimeString("es-CO")}` : ""}</small> : <span/>}
      {isSuperAdmin && <button className="text-button" disabled={checking} onClick={check}><RotateCcw size={12}/>{checking ? "Verificando…" : "Verificar ahora"}</button>}
    </div>
  </section>;
}

export { SystemHealthCard };
