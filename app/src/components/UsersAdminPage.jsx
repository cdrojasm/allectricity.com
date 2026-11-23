import React, { useEffect, useState } from "react";
import { Search, Send, UserPlus, Users, X } from "lucide-react";
import { LicensesPanel } from "./LicensesPanel.jsx";

// Pilot onboarding for super_admin: invite an engineer with the designer role and a token budget.
// The account gets a random password nobody sees; the engineer chooses their own through the reset link.

const roleLabels = { super_admin: "Superadministrador", user_admin: "Administrador de usuarios", designer: "Diseñador", viewer: "Lector" };

function randomPassword() {
  const bytes = new Uint8Array(24);
  crypto.getRandomValues(bytes);
  return `Tmp-${Array.from(bytes, (b) => b.toString(36).padStart(2, "0")).join("")}`.slice(0, 64);
}

async function request(token, url, options = {}) {
  const response = await fetch(url, { ...options, headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json", ...(options.headers || {}) } });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = body.detail;
    throw new Error(typeof detail === "string" ? detail : detail?.message || `La operación falló (${response.status}).`);
  }
  return body;
}

export function UsersAdminPage({ token, onNotice }) {
  const [users, setUsers] = useState([]);
  const [roles, setRoles] = useState([]);
  const [assignments, setAssignments] = useState([]);
  const [budgets, setBudgets] = useState([]);
  const [error, setError] = useState("");
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [query, setQuery] = useState("");
  const [userStatus, setUserStatus] = useState("all");
  const [roleFilter, setRoleFilter] = useState("all");
  const [page, setPage] = useState(0);
  const pageSize = 8;
  const [form, setForm] = useState({ email: "", first_name: "", last_name: "", tokens: 2000000 });

  async function reload() {
    try {
      const [u, r, a, b] = await Promise.all([
        request(token, "/api/v1/users?limit=100"), request(token, "/api/v1/roles?limit=100"),
        request(token, "/api/v1/user-roles?limit=100"), request(token, "/api/v1/budgets?limit=100"),
      ]);
      setUsers(u); setRoles(r); setAssignments(Array.isArray(a) ? a : a.items || []); setBudgets(b); setError("");
    } catch (e) { setError(e.message); }
  }
  useEffect(() => { reload(); }, [token]);

  const roleName = (id) => roles.find((role) => role.id === id)?.name;
  const rolesOf = (userId) => assignments.filter((item) => item.user_id === userId).map((item) => roleName(item.role_id)).filter(Boolean);
  const budgetOf = (userId) => budgets.filter((item) => item.user_id === userId && item.active);
  const filteredUsers = users.filter((user) => {
    const needle = query.trim().toLocaleLowerCase("es");
    const matches = !needle || [user.first_name, user.last_name, user.email].some((value) => String(value || "").toLocaleLowerCase("es").includes(needle));
    return matches && (userStatus === "all" || (user.active === false ? "inactive" : "active") === userStatus) && (roleFilter === "all" || rolesOf(user.id).includes(roleFilter));
  });
  const pageUsers = filteredUsers.slice(page * pageSize, (page + 1) * pageSize);
  const pageCount = Math.max(1, Math.ceil(filteredUsers.length / pageSize));
  useEffect(() => { if (page >= pageCount) setPage(pageCount - 1); }, [page, pageCount]);

  async function invite(event) {
    event.preventDefault();
    const designer = roles.find((role) => role.name === "designer");
    if (!designer) return setError("No existe el rol «designer» en esta instalación.");
    setBusy(true); setError("");
    try {
      const user = await request(token, "/api/v1/users", { method: "POST", body: JSON.stringify({ email: form.email, first_name: form.first_name, last_name: form.last_name, password: randomPassword() }) });
      await request(token, "/api/v1/user-roles", { method: "POST", body: JSON.stringify({ user_id: user.id, role_id: designer.id }) });
      if (Number(form.tokens) > 0) await request(token, "/api/v1/budgets", { method: "POST", body: JSON.stringify({ user_id: user.id, name: "Piloto", total_tokens: Math.round(Number(form.tokens)) }) });
      await fetch("/api/v1/auth/forgot-password", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ email: form.email }) });
      onNotice?.(`Invitación enviada a ${form.email}: recibirá un enlace para elegir su contraseña.`);
      setOpen(false); setForm({ email: "", first_name: "", last_name: "", tokens: 2000000 });
      await reload();
    } catch (e) { setError(e.message); }
    finally { setBusy(false); }
  }

  async function resend(user) {
    try {
      await fetch("/api/v1/auth/forgot-password", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ email: user.email }) });
      onNotice?.(`Se reenvió el enlace de acceso a ${user.email}.`);
    } catch { setError("No se pudo reenviar el enlace."); }
  }

  return <section className="projects-page users-admin-page">
    <div className="projects-topline"><div><div className="eyebrow">ALLECTRICITY WORKSPACE / USUARIOS</div><h1>Usuarios</h1><p>Invita ingenieros al piloto con permiso de diseño y una bolsa de tokens para el agente.</p></div><button className="button primary" onClick={() => setOpen(true)}><UserPlus size={15}/> Invitar ingeniero</button></div>
    <div className="project-summary"><span><Users size={17}/><strong>{users.length}</strong> usuarios</span></div>
    {error && <div className="project-error" role="alert">{error}<button onClick={() => setError("")} aria-label="Cerrar"><X size={14}/></button></div>}
    <div className="projects-table-tools"><label><Search size={15}/><input aria-label="Buscar usuarios" placeholder="Buscar por nombre o correo" value={query} onChange={(event) => { setQuery(event.target.value); setPage(0); }}/></label><select aria-label="Filtrar usuarios por estado" value={userStatus} onChange={(event) => { setUserStatus(event.target.value); setPage(0); }}><option value="all">Todos los estados</option><option value="active">Activos</option><option value="inactive">Desactivados</option></select><select aria-label="Filtrar usuarios por rol" value={roleFilter} onChange={(event) => { setRoleFilter(event.target.value); setPage(0); }}><option value="all">Todos los roles</option>{roles.map((role) => <option key={role.id} value={role.name}>{roleLabels[role.name] || role.name}</option>)}</select></div>
    <div className="projects-table-wrap"><table className="projects-table" data-testid="users-table"><thead><tr><th>USUARIO</th><th>ROLES</th><th>TOKENS</th><th>ESTADO</th><th></th></tr></thead><tbody>
      {pageUsers.map((user) => { const own = budgetOf(user.id); const total = own.reduce((sum, item) => sum + item.total_tokens, 0); const used = own.reduce((sum, item) => sum + item.used_tokens, 0);
        return <tr key={user.id}><td><strong>{`${user.first_name || ""} ${user.last_name || ""}`.trim() || user.email}</strong><small>{user.email}</small></td>
          <td>{rolesOf(user.id).map((name) => roleLabels[name] || name).join(", ") || "—"}</td>
          <td>{own.length ? `${used.toLocaleString("es-CO")} de ${total.toLocaleString("es-CO")}` : "Sin bolsa"}</td>
          <td>{user.active === false ? "Desactivado" : "Activo"}</td>
          <td>{user.active !== false && <button className="button" onClick={() => resend(user)}><Send size={13}/> Reenviar enlace</button>}</td></tr>; })}
      {Array.from({ length: Math.max(0, pageSize - pageUsers.length) }, (_, index) => <tr className="projects-placeholder-row" aria-hidden="true" key={`user-placeholder-${index}`}><td colSpan="5"/></tr>)}
    </tbody></table></div><div className="projects-pagination"><span>{filteredUsers.length ? `${page * pageSize + 1}–${Math.min((page + 1) * pageSize, filteredUsers.length)} de ${filteredUsers.length} usuarios` : "0 usuarios"}</span><div><button className="button" disabled={!page} onClick={() => setPage((value) => Math.max(0, value - 1))}>Anterior</button><span>Página {page + 1} de {pageCount}</span><button className="button" disabled={page + 1 >= pageCount} onClick={() => setPage((value) => Math.min(pageCount - 1, value + 1))}>Siguiente</button></div></div>
    <LicensesPanel token={token} onNotice={onNotice} />
    {open && <div className="modal-backdrop project-modal-backdrop" onMouseDown={(e) => { if (e.target === e.currentTarget && !busy) setOpen(false); }}><form className="project-modal" onSubmit={invite} aria-label="Invitar ingeniero">
      <div className="project-modal-head"><div><div className="eyebrow">PILOTO</div><h2>Invitar ingeniero</h2></div><button type="button" className="icon-button" aria-label="Cerrar" onClick={() => setOpen(false)}><X size={18}/></button></div>
      <div className="project-form-body">
        <label>Correo electrónico<input type="email" required value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })}/></label>
        <label>Nombre<input required maxLength="100" value={form.first_name} onChange={(e) => setForm({ ...form, first_name: e.target.value })}/></label>
        <label>Apellido <span className="optional">Opcional</span><input maxLength="100" value={form.last_name} onChange={(e) => setForm({ ...form, last_name: e.target.value })}/></label>
        <label>Tokens para el agente<input type="number" min="0" step="100000" value={form.tokens} onChange={(e) => setForm({ ...form, tokens: e.target.value })}/></label>
        <p className="map-optional-hint">Tendrá el rol de diseñador. Recibirá un correo con un enlace para elegir su contraseña; nadie más la conoce.</p>
      </div>
      {error && <div className="project-modal-error" role="alert">{error}</div>}
      <div className="project-modal-actions"><button className="button" type="button" onClick={() => setOpen(false)}>Cancelar</button><button className="button primary" type="submit" disabled={busy}>{busy ? "Invitando…" : "Enviar invitación"}</button></div>
    </form></div>}
  </section>;
}
