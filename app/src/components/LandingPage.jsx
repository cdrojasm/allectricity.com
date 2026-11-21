import React, { useEffect, useRef, useState } from "react";
import { ArrowRight, ArrowUpRight, Check, FileText, Layers, Network, ShieldCheck, Waves, Zap } from "lucide-react";
import { createSwarm } from "../landingSwarm.js";
import { LandingVideo, VideoThumbnail } from "./LandingVideo.jsx";
import "../landing.css";

const STEPS = [
  {
    id: "documentos",
    icon: Network,
    kicker: "01 · Documentos",
    title: "Nos das tus documentos y los entendemos.",
    body: "Planos, informes y mediciones, como los tengas. Sacamos los datos que hacen falta y te mostramos de dónde salió cada uno. Si falta algo, te preguntamos.",
    points: ["PDF, Word, Excel, CSV, DXF e imágenes", "Ves de dónde salió cada dato", "Te preguntamos lo que no encontramos"],
  },
  {
    id: "terreno",
    icon: Layers,
    kicker: "02 · Terreno",
    title: "Entendemos tu terreno.",
    body: "Con tus mediciones de resistividad sabemos cómo es el suelo, capa por capa, y te mostramos la gráfica para que la revises.",
    points: ["Mediciones Wenner y Schlumberger", "Suelo de 2 o más capas", "Gráfica del ajuste"],
  },
  {
    id: "malla",
    icon: Zap,
    kicker: "03 · Malla",
    title: "Te sugerimos una malla.",
    body: "Conductores y varillas sobre tu plano. La cambias tú o nos pides cambios en el chat.",
    points: ["Editor de plano", "Cambios por chat", "Materiales del catálogo"],
  },
  {
    id: "seguridad",
    icon: ShieldCheck,
    kicker: "04 · Seguridad",
    title: "Revisamos que sea segura.",
    body: "Calculamos las tensiones de toque y paso con IEEE 80 y RETIE. Si no cumple, te decimos dónde y cómo corregirla.",
    points: ["Toque, paso y resistencia de la malla", "Mapa de dónde falla", "Qué cambiar para que cumpla"],
  },
  {
    id: "estudio",
    icon: FileText,
    kicker: "05 · Estudio",
    title: "Te entregamos el estudio.",
    body: "En PDF y como enlace para compartir. No queda como final hasta que confirmes los datos importantes. Tú lo revisas y lo firmas.",
    points: ["PDF y enlace para compartir", "Con tu logo", "Marca qué datos son supuestos"],
  },
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
          <a href="#principios">Cómo trabajamos</a>
          <a href="#demo">Demo</a>
        </nav>
        <a className="landing-button ghost small" href={appHref}>Iniciar sesión</a>
      </header>

      <main>
        <section className="landing-hero" data-formation="0">
          <p className="landing-eyebrow reveal">Allectricity</p>
          <h1 className="reveal">
            Agente para diseñar <span>puestas a tierra</span>.
          </h1>
          <p className="landing-lede reveal">
            Nos das tus documentos, los entendemos, te sugerimos una malla, revisamos que sea segura y te entregamos el estudio.
          </p>
          <div className="landing-actions reveal">
            <a className="landing-button primary" href={appHref}>Empezar un proyecto <ArrowRight size={16} /></a>
            <a className="landing-button ghost" href="#demo">Ver la demo</a>
          </div>
          <dl className="landing-facts reveal">
            <div><dt>Nos das</dt><dd>Planos, PDF, Excel</dd></div>
            <div><dt>Revisamos con</dt><dd>IEEE 80 · RETIE</dd></div>
            <div><dt>Te entregamos</dt><dd>Estudio en PDF y web</dd></div>
          </dl>
          <p className="landing-hint" aria-hidden="true">{reducedMotion ? "" : "Haz clic para simular una falla"}</p>
          <VideoThumbnail reducedMotion={reducedMotion} />
        </section>

        <LandingVideo />

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
            <p className="landing-eyebrow">Cómo trabajamos</p>
            <h2>Hacemos el trabajo. Tú decides.</h2>
          </div>
          <div className="landing-principle-grid">
            <article className="reveal">
              <Waves size={18} />
              <h3>No nos quedamos trabados</h3>
              <p>Si falta un dato, usamos un valor razonable, te avisamos y seguimos. Tú lo confirmas después.</p>
            </article>
            <article className="reveal">
              <Layers size={18} />
              <h3>Todo queda guardado</h3>
              <p>Cada cambio crea una versión nueva. Puedes compararlas y volver atrás cuando quieras.</p>
            </article>
            <article className="reveal">
              <ShieldCheck size={18} />
              <h3>Tú firmas</h3>
              <p>No reemplazamos al ingeniero. Hacemos la parte repetitiva; la decisión final es tuya.</p>
            </article>
          </div>
        </section>

        <section className="landing-cta" data-formation="0">
          <h2 className="reveal">Danos tus documentos del próximo proyecto.</h2>
          <a className="landing-button primary reveal" href={appHref}>Empezar <ArrowUpRight size={16} /></a>
        </section>
      </main>

      <footer className="landing-footer">
        <span>© {new Date().getFullYear()} Allectricity</span>
        <span>Allectricity te ayuda a diseñar; no reemplaza al ingeniero que firma el estudio.</span>
      </footer>
    </div>
  );
}
