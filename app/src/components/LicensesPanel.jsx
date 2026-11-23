import React, { useEffect, useState } from "react";
import { Copy, KeyRound, Search, X } from "lucide-react";

// Super-admin: generate license codes (one per person, single use), see who redeemed them and revoke them.
// Plain codes are returned only once, right after creation; the server keeps just a hash.

async function request(token, url, options = {}) {
  const response = await fetch(url, { ...options, headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json", ...(options.headers || {}) } });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = body.detail;
    throw new Error(typeof detail === "string" ? detail : detail?.[0]?.msg || `La operación falló (${response.status}).`);
  }
  return body;
}

const day = (seconds) => (seconds ? new Date(seconds * 1000).toLocaleDateString("es-CO") : "—");

function stateOf(license) {
  if (license.revoked_at) return "Revocada";
  if (license.redeemed_at) return `Canjeada por ${license.redeemed_by_email || "un usuario"} el ${day(license.redeemed_at)}`;
  if (license.redeem_before && license.redeem_before * 1000 < Date.now()) return "Vencida sin canjear";
  return license.redeem_before ? `Disponible hasta el ${day(license.redeem_before)}` : "Disponible";
}

export function LicensesPanel({ token, onNotice }) {
  const [licenses, setLicenses] = useState([]);
  const [tiers, setTiers] = useState([]);
  const [form, setForm] = useState({ tier: "", months: 1, count: 1, note: "", redeem_days: "" });
  const [created, setCreated] = useState([]);
  const [confirming, setConfirming] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [query, setQuery] = useState("");
  const [licenseStatus, setLicenseStatus] = useState("all");
  const [licenseTier, setLicenseTier] = useState("all");
  const [page, setPage] = useState(0);
  const pageSize = 8;

  async function reload() {
    try {
      const [list, catalog] = await Promise.all([request(token, "/api/v1/billing/licenses"), request(token, "/api/v1/billing/plans")]);
      setLicenses(list.licenses || []);
      const names = (catalog.plans || []).sort((a, b) => a.rank - b.rank).map((plan) => plan.name);
      setTiers(names);
      setForm((current) => ({ ...current, tier: current.tier || names[0] || "" }));
    } catch (e) { setError(e.message); }
  }
  useEffect(() => { reload(); }, [token]);
  function statusKey(license) {
    if (license.revoked_at) return "revoked";
    if (license.redeemed_at) return "redeemed";
    if (license.redeem_before && license.redeem_before * 1000 < Date.now()) return "expired";
    return "available";
  }
  const filteredLicenses = licenses.filter((license) => {
    const needle = query.trim().toLocaleLowerCase("es");
    const matches = !needle || [license.code_hint, license.tier, license.note, license.redeemed_by_email].some((value) => String(value || "").toLocaleLowerCase("es").includes(needle));
    return matches && (licenseStatus === "all" || statusKey(license) === licenseStatus) && (licenseTier === "all" || license.tier === licenseTier);
  }).sort((a, b) => (b.created_at || 0) - (a.created_at || 0));
  const pageLicenses = filteredLicenses.slice(page * pageSize, (page + 1) * pageSize);
  const pageCount = Math.max(1, Math.ceil(filteredLicenses.length / pageSize));
  useEffect(() => { if (page >= pageCount) setPage(pageCount - 1); }, [page, pageCount]);

  async function create(event) {
    event.preventDefault();
    setBusy(true); setError("");
    try {
      const body = { tier: form.tier, months: Number(form.months), count: Number(form.count), note: form.note || null,
        redeem_days: form.redeem_days ? Number(form.redeem_days) : null };
      const result = await request(token, "/api/v1/billing/licenses", { method: "POST", body: JSON.stringify(body) });
      setCreated(result.licenses || []);
      await reload();
    } catch (e) { setError(e.message); }
    finally { setBusy(false); }
  }

  async function revoke(license) {
    if (confirming !== license.id) { setConfirming(license.id); return; }
    setConfirming(null);
    try {
      await request(token, `/api/v1/billing/licenses/${license.id}/revoke`, { method: "POST" });
      onNotice?.("Licencia revocada.");
      await reload();
    } catch (e) { setError(e.message); }
  }

  async function copyCodes() {
    try {
      await navigator.clipboard.writeText(created.map((item) => item.code).join("\n"));
      onNotice?.("Códigos copiados.");
    } catch { setError("No se pudieron copiar; selecciónalos y cópialos a mano."); }
  }

  return <div className="licenses-panel" data-testid="licenses-panel">
    <div className="licenses-head"><div><div className="eyebrow">LICENCIAS</div><h2>Códigos de licencia</h2><p>Cada código es para una persona y se usa una sola vez. Da acceso al plan durante los meses indicados y recarga sus tokens cada mes.</p></div></div>
    {error && <div className="project-error" role="alert">{error}<button onClick={() => setError("")} aria-label="Cerrar"><X size={14}/></button></div>}
    <form className="licenses-form" onSubmit={create}>
      <label>Plan<select value={form.tier} onChange={(e) => setForm({ ...form, tier: e.target.value })} required>{tiers.map((tier) => <option key={tier} value={tier}>{tier}</option>)}</select></label>
      <label>Meses<input type="number" min="1" max="36" value={form.months} onChange={(e) => setForm({ ...form, months: e.target.value })} required/></label>
      <label>Cantidad<input type="number" min="1" max="100" value={form.count} onChange={(e) => setForm({ ...form, count: e.target.value })} required/></label>
      <label>Canjear antes de (días) <span className="optional">Opcional</span><input type="number" min="1" max="365" value={form.redeem_days} onChange={(e) => setForm({ ...form, redeem_days: e.target.value })}/></label>
      <label className="licenses-note">Nota <span className="optional">Opcional</span><input maxLength="200" value={form.note} placeholder="Ej.: piloto empresa ACME" onChange={(e) => setForm({ ...form, note: e.target.value })}/></label>
      <button className="button primary" type="submit" disabled={busy || !form.tier}><KeyRound size={14}/>{busy ? "Generando…" : "Generar códigos"}</button>
    </form>
    {created.length > 0 && <div className="license-codes" role="status">
      <div><strong>Copia estos códigos ahora: no se vuelven a mostrar.</strong><button className="button" onClick={copyCodes}><Copy size={13}/> Copiar</button><button className="icon-button" aria-label="Ocultar códigos" onClick={() => setCreated([])}><X size={15}/></button></div>
      <ul>{created.map((item) => <li key={item.id}><code>{item.code}</code> · {item.tier} · {item.months} {item.months === 1 ? "mes" : "meses"}</li>)}</ul>
    </div>}
    <div className="projects-table-tools"><label><Search size={15}/><input aria-label="Buscar licencias" placeholder="Buscar por código, plan o nota" value={query} onChange={(event) => { setQuery(event.target.value); setPage(0); }}/></label><select aria-label="Filtrar licencias por estado" value={licenseStatus} onChange={(event) => { setLicenseStatus(event.target.value); setPage(0); }}><option value="all">Todos los estados</option><option value="available">Disponibles</option><option value="redeemed">Canjeadas</option><option value="expired">Vencidas</option><option value="revoked">Revocadas</option></select><select aria-label="Filtrar licencias por plan" value={licenseTier} onChange={(event) => { setLicenseTier(event.target.value); setPage(0); }}><option value="all">Todos los planes</option>{tiers.map((tier) => <option key={tier} value={tier}>{tier}</option>)}</select></div>
    <div className="projects-table-wrap"><table className="projects-table" data-testid="licenses-table"><thead><tr><th>CÓDIGO</th><th>PLAN</th><th>DURACIÓN</th><th>ESTADO</th><th>CREADA</th><th></th></tr></thead><tbody>
      {pageLicenses.map((license) => <tr key={license.id}><td><strong>…{license.code_hint}</strong>{license.note && <small>{license.note}</small>}</td><td>{license.tier}</td><td>{license.months} {license.months === 1 ? "mes" : "meses"}</td><td>{stateOf(license)}</td><td>{day(license.created_at)}</td>
        <td>{!license.revoked_at && <button className="button" onClick={() => revoke(license)}>{confirming === license.id ? "¿Confirmar revocación?" : "Revocar"}</button>}</td></tr>)}
      {!pageLicenses.length && <tr><td colSpan="6" className="projects-empty">{licenses.length ? "No hay licencias que coincidan." : "Aún no hay códigos."}</td></tr>}
      {pageLicenses.length > 0 && Array.from({ length: Math.max(0, pageSize - pageLicenses.length) }, (_, index) => <tr className="projects-placeholder-row" aria-hidden="true" key={`license-placeholder-${index}`}><td colSpan="6"/></tr>)}
    </tbody></table></div><div className="projects-pagination"><span>{filteredLicenses.length ? `${page * pageSize + 1}–${Math.min((page + 1) * pageSize, filteredLicenses.length)} de ${filteredLicenses.length} licencias` : "0 licencias"}</span><div><button className="button" disabled={!page} onClick={() => setPage((value) => Math.max(0, value - 1))}>Anterior</button><span>Página {page + 1} de {pageCount}</span><button className="button" disabled={page + 1 >= pageCount} onClick={() => setPage((value) => Math.min(pageCount - 1, value + 1))}>Siguiente</button></div></div>
  </div>;
}
