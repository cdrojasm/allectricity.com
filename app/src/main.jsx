import React, { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { CircleAlert, CircleHelp, Layers, LayoutGrid, LogOut, PackageSearch, X, Zap } from "lucide-react";
import { IconButton } from "./shared.jsx";
import { Login, ProjectsPage } from "./components/ProjectPages.jsx";
import { DashboardPage } from "./components/DashboardPage.jsx";
import { ProjectChatWorkspace } from "./components/ProjectChatWorkspace.jsx";
import { PublicStudyPage } from "./components/StudyPage.jsx";
import { MaterialCatalogSuite } from "./components/MaterialCatalogSuite.jsx";
import { EXPIRED_EVENT, installAuthenticatedFetch } from "./authFetch.js";
import "./styles.css";

function App() {
  const publicStudy = window.location.pathname.match(/^\/e\/([^/]+)\/?$/);
  const [token, setToken] = useState(() => localStorage.getItem("spat_access_token"));
  const [user, setUser] = useState(null);
  const [authChecking, setAuthChecking] = useState(true);
  const [sessionExpired, setSessionExpired] = useState(false);
  const [notice, setNotice] = useState("");
  const [lastVisit, setLastVisit] = useState(null);
  const [tab, setTab] = useState("dashboard");
  const [activeProject, setActiveProject] = useState(null);
  useEffect(() => installAuthenticatedFetch(), []);
  useEffect(() => {
    const markExpired = () => setSessionExpired(true);
    window.addEventListener(EXPIRED_EVENT, markExpired);
    return () => window.removeEventListener(EXPIRED_EVENT, markExpired);
  }, []);
  useEffect(() => {
    let cancelled = false;
    if (publicStudy) { setAuthChecking(false); return () => { cancelled = true; }; }
    if (!token) {
      localStorage.removeItem("spat_access_token");
      if (window.location.pathname !== "/login") window.history.replaceState({}, "", "/login");
      setAuthChecking(false);
      return () => { cancelled = true; };
    }
    fetch("/api/v1/auth/me", { headers: { Authorization: `Bearer ${token}` } })
      .then(async (response) => {
        if (!response.ok) throw Object.assign(new Error("Session validation failed"), { status: response.status });
        return response.json();
      })
      .then((profile) => {
        if (cancelled) return;
        setUser(profile);
        if (window.location.pathname === "/login") window.history.replaceState({}, "", "/");
      })
      .catch((error) => {
        if (cancelled) return;
        if (error.status === 401) setSessionExpired(true);
        else {
          localStorage.removeItem("spat_access_token");
          localStorage.removeItem("spat_refresh_token");
          localStorage.removeItem("spat_access_expires_at");
          setToken(null);
          setUser(null);
          if (window.location.pathname !== "/login") window.history.replaceState({}, "", "/login");
        }
      })
      .finally(() => { if (!cancelled) setAuthChecking(false); });
    return () => { cancelled = true; };
  }, [token]);
  useEffect(() => {
    if (!user?.id) return;
    const key = `terra_last_visit:${user.id}`;
    const previousVisit = Number(localStorage.getItem(key));
    setLastVisit(previousVisit || null);
    localStorage.setItem(key, String(Date.now()));
  }, [user?.id]);
  useEffect(() => {
    if (publicStudy || !token || !user) return undefined;
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
      } else if (window.location.pathname === "/catalog") {
        setActiveProject(null); setTab("catalog");
      } else {
        setActiveProject(null); setTab("dashboard");
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
  function showDashboard() {
    window.history.pushState({}, "", "/");
    setActiveProject(null);
    setTab("dashboard");
  }
  const [catalogProjectId, setCatalogProjectId] = useState(null);
  function showCatalog(projectId) {
    window.history.pushState({}, "", "/catalog");
    setCatalogProjectId(typeof projectId === "string" ? projectId : null);
    setActiveProject(null);
    setTab("catalog");
  }
  function acceptToken(pair) {
    const accessToken = typeof pair === "string" ? pair : pair.access_token;
    localStorage.setItem("spat_access_token", accessToken);
    if (pair.refresh_token) localStorage.setItem("spat_refresh_token", pair.refresh_token);
    if (pair.expires_in) localStorage.setItem("spat_access_expires_at", String(Date.now() + Number(pair.expires_in) * 1000));
    setSessionExpired(false);
    setAuthChecking(true);
    setToken(accessToken);
  }
  function logout() {
    localStorage.removeItem("spat_access_token");
    localStorage.removeItem("spat_refresh_token");
    localStorage.removeItem("spat_access_expires_at");
    setToken(null);
    setUser(null);
    setSessionExpired(false);
  }
  function goToLogin() {
    logout();
    window.history.replaceState({}, "", "/login");
  }
  function exitExpiredSession() {
    logout();
    window.history.replaceState({}, "", "/");
  }
  useEffect(() => {
    if (!notice) return undefined;
    const id = setTimeout(() => setNotice(""), 5000);
    return () => clearTimeout(id);
  }, [notice]);
  if (authChecking) return <main className="login-page"><div className="login-loading">Loading your workspace…</div></main>;
  if (publicStudy) return <PublicStudyPage slug={decodeURIComponent(publicStudy[1])} />;
  if (!token || !user) return <><Login onLogin={acceptToken} />{sessionExpired && <SessionExpiredDialog onExit={exitExpiredSession} onLogin={goToLogin} />}</>;
  return (
    <div className="app-shell">
      <nav className="rail" aria-label="Main navigation">
        <a className="brand" href="/" aria-label="Terra home" onClick={(event) => { event.preventDefault(); showDashboard(); }}>
          <Zap size={23} fill="currentColor" />
        </a>
        <div className="rail-top">
          <IconButton title="Dashboard" className={`rail-button ${tab === "dashboard" ? "active" : ""}`} onClick={showDashboard}><LayoutGrid size={21} /></IconButton>
          <IconButton title="Proyectos" aria-label="Proyectos" className={`rail-button ${tab === "projects" ? "active" : ""}`} onClick={showProjects}><Layers size={21} /></IconButton>
          <IconButton title="Catálogo de materiales" aria-label="Catálogo de materiales" className={`rail-button ${tab === "catalog" ? "active" : ""}`} onClick={() => showCatalog()}><PackageSearch size={21} /></IconButton>
        </div>
        <div className="rail-bottom">
          <IconButton title="Ayuda del espacio" onClick={() => setNotice("Abre un proyecto para revisar sus archivos, mediciones, plano y seguridad.")}><CircleHelp size={20} /></IconButton>
          <button className="avatar" title={`${user.email} · ${user.roles.join(", ")}. Cerrar sesión`} onClick={logout}>{`${user.first_name?.[0] || "U"}${user.last_name?.[0] || ""}`.toUpperCase()}</button>
        </div>
      </nav>
      {tab === "projects" ? <ProjectsPage token={token} onNotice={setNotice} onOpen={openProject} /> : tab === "catalog" ? <MaterialCatalogSuite token={token} userId={user.id} initialProjectId={catalogProjectId} onNotice={setNotice} /> : activeProject ? <ProjectChatWorkspace onOpenCatalog={showCatalog} project={activeProject} token={token} userId={user.id} onBack={showProjects} onNotice={setNotice} /> : <DashboardPage token={token} user={user} lastVisit={lastVisit} onOpen={openProject} onShowProjects={showProjects} />}
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
      {sessionExpired && <SessionExpiredDialog onExit={exitExpiredSession} onLogin={goToLogin} />}
    </div>
  );
}

function SessionExpiredDialog({ onExit, onLogin }) {
  return <div className="session-expired-backdrop"><section className="session-expired-dialog" role="alertdialog" aria-modal="true" aria-labelledby="session-expired-title" aria-describedby="session-expired-description">
    <span className="session-expired-icon"><CircleAlert size={23}/></span>
    <div className="eyebrow">SEGURIDAD DE LA CUENTA</div>
    <h2 id="session-expired-title">Tu sesión ya expiró</h2>
    <p id="session-expired-description">Por seguridad, terminamos esta sesión. Vuelve a iniciar sesión para continuar.</p>
    <div className="session-expired-actions"><button className="button" onClick={onExit}><LogOut size={15}/>Salir</button><button className="button primary" onClick={onLogin}>Ir al login</button></div>
  </section></div>;
}

createRoot(document.getElementById("root")).render(<App />);
