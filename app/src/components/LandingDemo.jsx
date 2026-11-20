import React, { useEffect, useRef, useState } from "react";
import { Activity, Box, Cable, Check, FileText, Layers, Network, Paperclip, Play, Send, ShieldCheck, Zap } from "lucide-react";

// Scroll-driven product demo: a miniature of the app (chat with Aleia | design panel) that advances one
// step per screen of scroll. All numbers are illustrative; the section says so.

const STEPS = [
  { tab: "files", title: "Nos das tus documentos", sub: "Planos, mediciones y el unifilar, como los tengas." },
  { tab: "files", view: "graph", title: "Los entendemos", sub: "Sacamos los datos y te mostramos de dónde salió cada uno." },
  { tab: "soil", title: "Entendemos el terreno", sub: "Con tus mediciones de resistividad." },
  { tab: "plan", title: "Te sugerimos una malla", sub: "Conductores y varillas sobre tu plano." },
  { tab: "results", title: "Revisamos que sea segura", sub: "Si algo no cumple, lo corregimos y volvemos a calcular." },
  { tab: "artifact", view: "study", title: "Te entregamos el estudio", sub: "En PDF y como enlace, listo para que lo firmes." },
];

const TABS = [
  { id: "artifact", icon: Box, label: "Resumen" },
  { id: "files", icon: Layers, label: "Fuentes" },
  { id: "soil", icon: Network, label: "Suelo" },
  { id: "plan", icon: Cable, label: "Plano" },
  { id: "results", icon: Activity, label: "Resultado" },
];

// Chat script: each message appears at (step, t).
const CHAT = [
  { step: 0, at: 0.05, who: "user", text: "Me llegó esto del cliente. Necesito el estudio de la malla de la subestación.", files: ["plano_subestacion.pdf", "wenner_campo.xlsx", "unifilar.pdf"] },
  { step: 0, at: 0.45, who: "aleia", text: "Recibido. Los paso por cuarentena y OCR y empiezo a leer." },
  { step: 1, at: 0.2, who: "aleia", tool: "extraer_grafo", text: "Saqué 42 datos, cada uno con su página de origen. Me falta la corriente de falla: la tomo del unifilar como supuesto." },
  { step: 2, at: 0.2, who: "aleia", tool: "fit_soil", text: "Con tus 11 lecturas ajusté un suelo de 2 capas: ρ₁ = 182 Ω·m, ρ₂ = 61 Ω·m, h = 2,4 m." },
  { step: 3, at: 0.2, who: "aleia", tool: "run_grid_designer", text: "Propongo una malla de 6 × 6 con 8 varillas en el perímetro. Puedes moverla en el plano." },
  { step: 4, at: 0.1, who: "aleia", tool: "request_calculation", text: "Las 4 mallas de esquina superan el límite de toque. Agrego una varilla en cada esquina y recalculo." },
  { step: 4, at: 0.7, who: "aleia", tool: "run_safety_analyst", text: "Ahora cumple: toque máximo al 82 % del límite." },
  { step: 5, at: 0.1, who: "aleia", text: "El estudio está en borrador. Queda 1 supuesto: la corriente de falla. ¿La confirmas?" },
  { step: 5, at: 0.45, who: "user", text: "Confirmada: 12 kA." },
  { step: 5, at: 0.7, who: "aleia", text: "Publicado. Te dejé el enlace y el PDF." },
];

const clamp = (v, a = 0, b = 1) => Math.min(b, Math.max(a, v));
const ramp = (t, from, to) => clamp((t - from) / (to - from));

function FilesView({ t }) {
  const files = [["plano_subestacion.pdf", "PDF · 14 páginas"], ["wenner_campo.xlsx", "XLSX · 11 lecturas"], ["unifilar.pdf", "PDF · 2 páginas"]];
  return <div className="dw-files">
    <div className="dw-panel-head"><Layers size={14} /><b>Fuentes del proyecto</b><span className="dw-count">{files.filter((_, i) => t > 0.08 + i * 0.12).length}</span></div>
    {files.map(([name, meta], i) => {
      const shown = t > 0.08 + i * 0.12;
      const ready = t > 0.55 + i * 0.12;
      return <div key={name} className={`dw-file ${shown ? "is-in" : ""}`}>
        <span className="dw-file-icon"><FileText size={15} /></span>
        <span><strong>{name}</strong><small>{ready ? `Disponible · ${meta}` : "Cuarentena y OCR…"}</small></span>
        <i className={ready ? "ok" : "pending"} />
      </div>;
    })}
    <div className="dw-note"><ShieldCheck size={13} /> Todo archivo pasa por cuarentena y análisis antes de usarse.</div>
  </div>;
}

const NODES = [
  [150, 95, "Subestación", 1], [62, 42, "Área 40 × 40 m"], [240, 40, "Icc 12 kA"], [262, 120, "tf 0,5 s"],
  [222, 170, "Varillas 2,4 m"], [80, 162, "ρ Wenner"], [30, 104, ""], [115, 20, ""], [190, 15, ""], [285, 78, ""], [150, 185, ""], [40, 140, ""],
];
const EDGES = [[0, 1], [0, 2], [0, 3], [0, 4], [0, 5], [1, 6], [1, 7], [2, 8], [3, 9], [4, 10], [5, 11], [2, 9], [5, 6]];

function GraphView({ t }) {
  return <div className="dw-graph">
    <div className="dw-panel-head"><Network size={14} /><b>Lo extraído</b><span className="dw-count">42</span></div>
    <svg viewBox="0 0 300 205" role="img" aria-label="Grafo de datos extraídos">
      {EDGES.map(([a, b], i) => {
        const on = ramp(t, 0.05 + i * 0.04, 0.2 + i * 0.04);
        return <line key={i} x1={NODES[a][0]} y1={NODES[a][1]} x2={NODES[a][0] + (NODES[b][0] - NODES[a][0]) * on} y2={NODES[a][1] + (NODES[b][1] - NODES[a][1]) * on} />;
      })}
      {NODES.map(([x, y, label, main], i) => {
        const on = ramp(t, i * 0.05, i * 0.05 + 0.15);
        return <g key={i} transform={`translate(${x} ${y}) scale(${on})`} className={main ? "main" : label ? "labeled" : ""}>
          <circle r={main ? 9 : label ? 6 : 3.5} />
          {label && <text y={main ? -14 : -10}>{label}</text>}
        </g>;
      })}
    </svg>
  </div>;
}

const SPACINGS = [1, 1.5, 2, 3, 4, 6, 8, 12, 16, 24, 32];
const rhoApparent = (a) => 61 + 121 / (1 + (a / 4) ** 1.6);
const sx = (a) => 30 + (Math.log(a) / Math.log(32)) * 255;
const sy = (rho) => 165 - ((rho - 40) / 170) * 145;
const CURVE = Array.from({ length: 60 }, (_, i) => {
  const a = Math.exp((i / 59) * Math.log(32));
  return `${i ? "L" : "M"}${sx(a).toFixed(1)},${sy(rhoApparent(a)).toFixed(1)}`;
}).join(" ");

function SoilView({ t }) {
  const fit = ramp(t, 0.35, 0.8);
  return <div className="dw-soil">
    <div className="dw-panel-head"><Network size={14} /><b>Modelo de suelo</b><span className="dw-tag">2 capas</span></div>
    <svg viewBox="0 0 300 190" role="img" aria-label="Ajuste del modelo de suelo">
      <line className="axis" x1="30" y1="165" x2="290" y2="165" /><line className="axis" x1="30" y1="15" x2="30" y2="165" />
      <text className="tick" x="30" y="180">1 m</text><text className="tick" x="270" y="180">32 m</text><text className="tick" x="2" y="22">Ω·m</text>
      <path className="fit" d={CURVE} pathLength="1" strokeDasharray="1" strokeDashoffset={1 - fit} />
      {SPACINGS.map((a, i) => {
        const on = ramp(t, i * 0.025, i * 0.025 + 0.1);
        const noise = [4, -6, 3, -2, 5, -4, 2, -3, 4, -2, 1][i];
        return <circle key={a} className="pt" cx={sx(a)} cy={sy(rhoApparent(a) + noise)} r={3.2 * on} />;
      })}
    </svg>
    <div className={`dw-chips ${t > 0.8 ? "is-in" : ""}`}><span>ρ₁ 182 Ω·m</span><span>ρ₂ 61 Ω·m</span><span>h 2,4 m</span></div>
  </div>;
}

const GRID_N = 6;
const gx = (i) => 40 + (i / (GRID_N - 1)) * 200;

function PlanView({ t }) {
  const lines = [];
  for (let i = 0; i < GRID_N; i += 1) lines.push([gx(i), 40, gx(i), 240], [40, gx(i), 240, gx(i)]);
  const rods = [];
  for (let i = 0; i < GRID_N; i += 1) for (let j = 0; j < GRID_N; j += 1) {
    const edge = i === 0 || j === 0 || i === GRID_N - 1 || j === GRID_N - 1;
    const corner = (i === 0 || i === GRID_N - 1) && (j === 0 || j === GRID_N - 1);
    if (edge && !corner && (i + j) % 2 === 1) rods.push([gx(i), gx(j)]);
  }
  return <div className="dw-plan">
    <div className="dw-panel-head"><Cable size={14} /><b>Plano</b><span className="dw-tag">40 × 40 m</span></div>
    <svg viewBox="0 0 280 270" role="img" aria-label="Malla de puesta a tierra">
      <rect className="site" x="20" y="20" width="240" height="240" rx="6" />
      <rect className="building" x="100" y="96" width="62" height="40" rx="3" />
      <text className="building-label" x="131" y="120">Patio</text>
      {lines.map(([x1, y1, x2, y2], i) => <line key={i} className="cond" x1={x1} y1={y1} x2={x2} y2={y2} pathLength="1" strokeDasharray="1" strokeDashoffset={1 - ramp(t, i * 0.03, i * 0.03 + 0.3)} />)}
      {rods.map(([x, y], i) => <circle key={i} className="rod" cx={x} cy={y} r={5.5 * ramp(t, 0.6 + i * 0.03, 0.7 + i * 0.03)} />)}
    </svg>
  </div>;
}

function touch(i, j, fixed) {
  const x = Math.abs((i - 4.5) / 4.5);
  const y = Math.abs((j - 4.5) / 4.5);
  const base = 0.42 + 0.34 * (x ** 3 + y ** 3) / 2 + 0.17 * Math.max(x, y) ** 4;
  return base * (1 - 0.27 * fixed * (x * y) ** 2);
}
const cellColor = (v) => `hsl(${Math.round(clamp(165 - ((v - 0.42) / 0.5) * 160, 5, 165))} 62% ${v > 0.8 ? 56 : 60}%)`;

function ResultsView({ t }) {
  const fixed = ramp(t, 0.5, 0.75);
  const cells = [];
  let worst = 0;
  for (let i = 0; i < 10; i += 1) for (let j = 0; j < 10; j += 1) {
    const v = touch(i, j, fixed);
    worst = Math.max(worst, v);
    cells.push(<rect key={`${i}-${j}`} x={20 + i * 22} y={20 + j * 22} width="21" height="21" rx="2" fill={cellColor(v)} className={v > 0.8 ? "over" : ""} style={{ opacity: ramp(t, (i + j) * 0.012, (i + j) * 0.012 + 0.12) }} />);
  }
  const ok = worst <= 0.8;
  return <div className="dw-results">
    <div className="dw-panel-head"><Activity size={14} /><b>Tensión de toque</b><span className={`dw-status ${ok ? "ok" : "bad"}`}>{ok ? "Cumple" : "No cumple"}</span></div>
    <svg viewBox="0 0 260 260" role="img" aria-label="Mapa de tensión de toque">
      {cells}
      {[[20, 20], [240, 20], [20, 240], [240, 240]].map(([x, y], i) => <circle key={i} className="rod added" cx={x} cy={y} r={6 * fixed} />)}
    </svg>
    <div className="dw-meter">
      <span>Toque máx.</span>
      <div><i style={{ width: `${Math.min(100, (worst / 0.8) * 87)}%` }} className={ok ? "ok" : "bad"} /><em style={{ left: "87%" }} /></div>
      <b>{Math.round((worst / 0.8) * 87)} %</b>
    </div>
  </div>;
}

function StudyView({ t }) {
  const published = t > 0.7;
  return <div className="dw-study">
    <div className="dw-page">
      {!published && <span className="dw-watermark">BORRADOR</span>}
      <p className="dw-page-kicker">Estudio de puesta a tierra</p>
      <h4>Subestación La Esperanza</h4>
      <div className="dw-lines"><i /><i /><i style={{ width: "70%" }} /></div>
      <div className="dw-page-grid">
        <div className="dw-mini-heat">{Array.from({ length: 36 }, (_, k) => <i key={k} style={{ background: cellColor(touch((k % 6) * 1.8, Math.floor(k / 6) * 1.8, 1)) }} />)}</div>
        <div className="dw-lines"><i /><i style={{ width: "80%" }} /><i /><i style={{ width: "55%" }} /></div>
      </div>
      <div className="dw-page-foot"><span>IEEE Std 80 · RETIE</span><span>v7</span></div>
    </div>
    <div className="dw-study-actions">
      <span className={`dw-status ${published ? "ok" : "warn"}`}>{published ? "Publicado" : "1 supuesto sin confirmar"}</span>
      <button type="button" tabIndex={-1} className={published ? "done" : ""}>{published ? <><Check size={13} /> Enlace copiado</> : "Publicar estudio"}</button>
    </div>
  </div>;
}

function ChatPane({ step, t }) {
  const visible = CHAT.filter((m) => m.step < step || (m.step === step && t >= m.at));
  const next = CHAT.find((m) => !visible.includes(m));
  const typing = next && next.who === "aleia" && next.step === step && t >= next.at - 0.18;
  return <div className="dw-chat">
    <div className="dw-chat-head"><span className="dw-aleia-mark"><Zap size={12} fill="currentColor" /></span><b>Aleia</b><small>agente de diseño</small></div>
    <div className="dw-messages">
      {visible.map((m, i) => <div key={i} className={`dw-msg ${m.who}`}>
        {m.tool && <span className="dw-tool"><Check size={11} />{m.tool}</span>}
        <p>{m.text}</p>
        {m.files && <div className="dw-attachments">{m.files.map((f) => <span key={f}><Paperclip size={10} />{f}</span>)}</div>}
      </div>)}
      {typing && <div className="dw-msg aleia dw-typing"><i /><i /><i /></div>}
    </div>
    <div className="dw-composer"><span>Escríbele a Aleia…</span><Send size={13} /></div>
  </div>;
}

function DemoWindow({ step, t }) {
  const current = STEPS[step];
  const view = current.view === "graph" ? <GraphView t={t} />
    : current.view === "study" ? <StudyView t={t} />
    : current.tab === "files" ? <FilesView t={t} />
    : current.tab === "soil" ? <SoilView t={t} />
    : current.tab === "plan" ? <PlanView t={t} />
    : <ResultsView t={t} />;
  return <div className="dw-window">
    <div className="dw-bar">
      <span className="dw-dots"><i /><i /><i /></span>
      <span className="dw-url">app.allectricity.com/project/la-esperanza</span>
      <span className="dw-avatar">IR</span>
    </div>
    <div className="dw-body">
      <ChatPane step={step} t={t} />
      <div className="dw-artifact">
        <div className="dw-tabs" role="presentation">
          {TABS.map(({ id, icon: Icon, label }) => <span key={id} className={current.tab === id ? "active" : ""}><Icon size={12} />{label}</span>)}
        </div>
        <div className="dw-view" key={`${step}`}>{view}</div>
      </div>
    </div>
  </div>;
}

// Miniature for the hero: the same window playing on its own.
export function DemoThumbnail({ reducedMotion, href = "#demo" }) {
  const [frame, setFrame] = useState({ step: 4, t: 1 });
  useEffect(() => {
    if (reducedMotion) return undefined;
    let step = 0;
    let t = 0;
    const id = setInterval(() => {
      t += 0.035;
      if (t > 1.3) { t = 0; step = (step + 1) % STEPS.length; }
      setFrame({ step, t: Math.min(1, t) });
    }, 60);
    return () => clearInterval(id);
  }, [reducedMotion]);
  return <a className="demo-thumb" href={href} aria-label="Ver la demo de Aleia">
    <div className="demo-thumb-frame" aria-hidden="true"><div className="demo-thumb-scale"><DemoWindow step={frame.step} t={frame.t} /></div></div>
    <span className="demo-thumb-label"><span className="demo-thumb-play"><Play size={11} fill="currentColor" /></span>Mira a Aleia en acción<small>{STEPS[frame.step].title}</small></span>
  </a>;
}

export function LandingDemo() {
  const sectionRef = useRef(null);
  const [frame, setFrame] = useState({ step: 0, t: 0 });
  useEffect(() => {
    let raf = 0;
    const update = () => {
      raf = 0;
      const el = sectionRef.current;
      if (!el) return;
      const rect = el.getBoundingClientRect();
      const span = el.offsetHeight - window.innerHeight;
      const progress = clamp(-rect.top / Math.max(1, span)) * STEPS.length;
      const step = Math.min(STEPS.length - 1, Math.floor(progress));
      setFrame({ step, t: clamp((progress - step) * 1.25) });
    };
    const onScroll = () => { if (!raf) raf = requestAnimationFrame(update); };
    update();
    window.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", onScroll);
    return () => { cancelAnimationFrame(raf); window.removeEventListener("scroll", onScroll); window.removeEventListener("resize", onScroll); };
  }, []);
  const current = STEPS[frame.step];
  return <section className="landing-demo" id="demo" ref={sectionRef} data-formation="0" style={{ height: `${STEPS.length * 85 + 100}vh` }} aria-label="Demo de Aleia">
    <div className="landing-demo-sticky">
      <div className="landing-demo-head">
        <p className="landing-eyebrow">Demo</p>
        <h2 key={frame.step} className="landing-demo-title">{current.title}</h2>
        <p className="landing-demo-sub">{current.sub}</p>
        <ol className="landing-demo-steps" aria-hidden="true">
          {STEPS.map((s, i) => <li key={s.title} className={i < frame.step ? "done" : i === frame.step ? "active" : ""}><i style={{ transform: `scaleX(${i < frame.step ? 1 : i === frame.step ? frame.t : 0})` }} /></li>)}
        </ol>
      </div>
      <DemoWindow step={frame.step} t={frame.t} />
      <p className="landing-demo-note">Demo ilustrativa con un proyecto de ejemplo. Los valores reales dependen de tus datos.</p>
    </div>
  </section>;
}
