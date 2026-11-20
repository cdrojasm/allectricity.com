import React, { useEffect, useRef, useState } from "react";
import { ArrowRight, ArrowUpRight, Check, FileText, Layers, Network, ShieldCheck, Waves, Zap } from "lucide-react";
import { createSwarm } from "../landingSwarm.js";
import { DemoThumbnail, LandingDemo } from "./LandingDemo.jsx";
import "../landing.css";

const STEPS = [
  {
    id: "fuentes",
    icon: Network,
    kicker: "01 · Fuentes",
    title: "Tus documentos se vuelven un grafo con evidencia.",
    body: "Sube planos, memorias, tablas de mediciones y especificaciones en PDF o imagen. Allectricity hace OCR, lee el plano y extrae cada dato como una afirmación que apunta a la página de donde salió.",
    points: ["OCR y rasterizado de PDF", "Afirmaciones, decisiones y preguntas abiertas", "Cada valor enlaza a su fuente"],
  },
  {
    id: "suelo",
    icon: Layers,
    kicker: "02 · Suelo",
    title: "De las lecturas Wenner a un modelo de suelo por capas.",
    body: "El agente toma las mediciones de campo, ajusta un modelo estratificado y te muestra la curva de ajuste. Si falta un dato, lo propone como supuesto explícito en lugar de detenerse.",
    points: ["Ajuste multicapa con gráfica", "Plantillas de medición", "Supuestos visibles, nunca silenciosos"],
  },
  {
    id: "malla",
    icon: Zap,
    kicker: "03 · Malla",
    title: "Diseña la malla o edita la que ya existe.",
    body: "Conductores, varillas y elementos constructivos sobre el plano real del sitio. El optimizador de topología explora alternativas y el catálogo de materiales mantiene el diseño construible.",
    points: ["Editor de plano con varillas y conductores", "Optimizador de topología", "Catálogo de materiales"],
  },
  {
    id: "seguridad",
    icon: ShieldCheck,
    kicker: "04 · Seguridad",
    title: "Potencial de superficie, toque y paso, calculados.",
    body: "El solver calcula el potencial de cada red respecto a tierra remota y lo compara con los límites tolerables de IEEE Std 80 y RETIE. Los puntos que exceden el límite se marcan sobre el mapa, escenario por escenario.",
    points: ["Escenarios de falla con inyecciones por red", "Mapa de potencial y vista 3D", "Validación térmica de conductores"],
  },
  {
    id: "estudio",
    icon: FileText,
    kicker: "05 · Estudio",
    title: "Un estudio que puedes compartir y defender.",
    body: "Allectricity arma el estudio completo como página web y PDF. Queda en borrador, con marca de agua, mientras haya supuestos sin confirmar; publicado, se fija a una versión del diseño.",
    points: ["Web + PDF personalizable", "Borrador hasta confirmar lo crítico", "Trazabilidad técnica en anexo"],
  },
];

const ORIGINS = [
  ["claim", "extraído del grafo, con evidencia"],
  ["document", "leído de un documento"],
  ["tool", "calculado o ajustado"],
  ["user", "confirmado por ti"],
  ["assumption", "supuesto explícito"],
];

// The landing lives on the root domain and the app on app.<domain>; locally the landing is
// landing.localhost:<port> and the app localhost:<port>.
function appOrigin() {
  const { protocol, hostname, port } = window.location;
  if (hostname === "localhost" || hostname.startsWith("app.")) return "";
  if (hostname.endsWith(".localhost")) return `${protocol}//localhost${port ? `:${port}` : ""}`;
  return `${protocol}//app.${hostname.replace(/^www\./, "")}${port ? `:${port}` : ""}`;
}

function useReducedMotion() {
  const [reduced] = useState(() => window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false);
  return reduced;
}

function SwarmCanvas({ formation, reducedMotion }) {
  const canvasRef = useRef(null);
  const swarmRef = useRef(null);
  useEffect(() => {
    const swarm = createSwarm(canvasRef.current, { reducedMotion });
    swarmRef.current = swarm;
    const move = (event) => swarm.pointer(event.clientX, event.clientY);
    const leave = () => swarm.leave();
    window.addEventListener("pointermove", move, { passive: true });
    document.addEventListener("pointerleave", leave);
    return () => {
      window.removeEventListener("pointermove", move);
      document.removeEventListener("pointerleave", leave);
      swarm.destroy();
    };
  }, [reducedMotion]);
  useEffect(() => swarmRef.current?.setFormation(formation), [formation]);
  useEffect(() => {
    if (formation !== 0) return undefined;
    const strike = (event) => {
      if (event.target.closest("a, button")) return;
      swarmRef.current?.strike();
    };
    window.addEventListener("pointerdown", strike);
    return () => window.removeEventListener("pointerdown", strike);
  }, [formation]);
  return <canvas ref={canvasRef} className="landing-canvas" aria-hidden="true" />;
}

export function LandingPage() {
  const reducedMotion = useReducedMotion();
  const [formation, setFormation] = useState(0);
  const [scrolled, setScrolled] = useState(false);
  const rootRef = useRef(null);

  useEffect(() => {
    const sections = rootRef.current.querySelectorAll("[data-formation]");
    const observer = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) setFormation(Number(entry.target.dataset.formation));
      });
    }, { rootMargin: "-48% 0px -48% 0px" });
    sections.forEach((section) => observer.observe(section));
    const onScroll = () => setScrolled(window.scrollY > 24);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => { observer.disconnect(); window.removeEventListener("scroll", onScroll); };
  }, []);

  useEffect(() => {
    if (reducedMotion) return undefined;
    const items = rootRef.current.querySelectorAll(".reveal");
    const observer = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) { entry.target.classList.add("is-in"); observer.unobserve(entry.target); }
      });
    }, { threshold: 0.18 });
    items.forEach((item) => observer.observe(item));
    return () => observer.disconnect();
  }, [reducedMotion]);

  const appHref = `${appOrigin()}/login`;
  const stepIndex = Math.max(0, formation - 1);

  return (
    <div className={`landing ${reducedMotion ? "is-static" : ""}`} ref={rootRef}>
      <SwarmCanvas formation={formation} reducedMotion={reducedMotion} />
      <div className="landing-vignette" aria-hidden="true" />

      <header className={`landing-nav ${scrolled ? "is-scrolled" : ""}`}>
        <a className="landing-brand" href="/" aria-label="Allectricity">
          <span className="landing-brand-mark"><Zap size={16} fill="currentColor" /></span>
          Allectricity
        </a>
        <nav aria-label="Secciones">
          <a href="#como-funciona">Cómo funciona</a>
          <a href="#principios">Principios</a>
          <a href="#demo">Demo</a>
        </nav>
        <a className="landing-button ghost small" href={appHref}>Iniciar sesión</a>
      </header>

      <main>
        <section className="landing-hero" data-formation="0">
          <p className="landing-eyebrow reveal">Agente de ingeniería para puestas a tierra</p>
          <h1 className="reveal">
            Del documento<br />al estudio de <span>puesta a tierra</span>.
          </h1>
          <p className="landing-lede reveal">
            Allectricity lee tus planos y mediciones, modela el suelo, diseña la malla y verifica tensiones de toque y paso.
            Cada número del estudio queda enlazado a su fuente.
          </p>
          <div className="landing-actions reveal">
            <a className="landing-button primary" href={appHref}>Empezar un proyecto <ArrowRight size={16} /></a>
            <a className="landing-button ghost" href="#demo">Ver la demo</a>
          </div>
          <dl className="landing-facts reveal">
            <div><dt>Normativa</dt><dd>IEEE Std 80 · RETIE</dd></div>
            <div><dt>Entradas</dt><dd>PDF · planos · tablas Wenner</dd></div>
            <div><dt>Salida</dt><dd>Estudio web + PDF</dd></div>
            <div><dt>Orígenes por valor</dt><dd>5, siempre visibles</dd></div>
          </dl>
          <p className="landing-hint" aria-hidden="true">{reducedMotion ? "" : "Haz clic para inyectar una corriente de falla"}</p>
          <DemoThumbnail reducedMotion={reducedMotion} />
        </section>

        <LandingDemo />

        <section className="landing-steps" id="como-funciona" aria-label="Cómo funciona">
          <ol className={`landing-rail ${formation >= 1 && formation <= 5 ? "is-visible" : ""}`} aria-hidden="true">
            {STEPS.map((step, index) => (
              <li key={step.id} className={formation >= 1 && index === stepIndex ? "is-active" : ""}>
                <span>{String(index + 1).padStart(2, "0")}</span>
              </li>
            ))}
          </ol>
          {STEPS.map((step, index) => {
            const Icon = step.icon;
            return (
              <article key={step.id} className="landing-step" data-formation={index + 1}>
                <div className="landing-step-card reveal">
                  <p className="landing-kicker"><Icon size={15} />{step.kicker}</p>
                  <h2>{step.title}</h2>
                  <p>{step.body}</p>
                  <ul>
                    {step.points.map((point) => <li key={point}><Check size={14} />{point}</li>)}
                  </ul>
                </div>
              </article>
            );
          })}
        </section>

        <section className="landing-principles" id="principios" data-formation="5">
          <div className="landing-section-head reveal">
            <p className="landing-eyebrow">Principios</p>
            <h2>Una sola verdad, construida contigo.</h2>
          </div>
          <div className="landing-principle-grid">
            <article className="reveal">
              <Waves size={18} />
              <h3>Mostrar primero, confirmar después</h3>
              <p>El agente construye el diseño completo con lo que encuentra. Lo que no encuentra lo marca como supuesto y te lo pide con un clic.</p>
            </article>
            <article className="reveal">
              <Layers size={18} />
              <h3>Un artefacto versionado</h3>
              <p>Plano, suelo, cálculo y estudio viven en un solo diseño con versiones, diferencias y restauración. Si cambia una entrada, lo que depende de ella queda marcado como desactualizado.</p>
            </article>
            <article className="reveal">
              <ShieldCheck size={18} />
              <h3>El ingeniero firma</h3>
              <p>Allectricity no certifica ni reemplaza tu criterio. Te da un estudio trazable, listo para revisión, y la última palabra es tuya.</p>
            </article>
          </div>
          <div className="landing-origins reveal" aria-label="Orígenes de un valor">
            {ORIGINS.map(([name, label]) => (
              <span key={name} className={`origin-${name}`}><code>{name}</code>{label}</span>
            ))}
          </div>
        </section>

        <section className="landing-cta" data-formation="0">
          <h2 className="reveal">Tu próximo estudio empieza con un archivo.</h2>
          <a className="landing-button primary reveal" href={appHref}>Entrar a Allectricity <ArrowUpRight size={16} /></a>
        </section>
      </main>

      <footer className="landing-footer">
        <span>© {new Date().getFullYear()} Allectricity</span>
        <span>Allectricity apoya el diseño; no certifica ni sustituye al ingeniero que firma el estudio.</span>
      </footer>
    </div>
  );
}
