import React, { useEffect, useRef, useState } from "react";
import { Play } from "lucide-react";

// Real recording of the app (local agent and solver on the La Esperanza sample files), edited so the
// agent's waits last about 2.5 s. Chapter times are seconds in that edit.
const VIDEO = "/media/allectricity-demo.mp4";
const POSTER = "/media/allectricity-demo-poster.jpg";

export const CHAPTERS = [
  { at: 2, title: "Nos das tus documentos", sub: "Subimos los siete archivos del proyecto: planos, sondeos y el estudio de cortocircuito." },
  { at: 16, title: "Los entendemos", sub: "Sacamos los datos y te mostramos de qué archivo salió cada uno." },
  { at: 30, title: "Te sugerimos una malla", sub: "Patio de 40 × 30 m, con varillas en las esquinas y en el perímetro." },
  { at: 46, title: "Entendemos el terreno", sub: "Ajustamos el suelo con tu sondeo Wenner." },
  { at: 61, title: "Te preguntamos lo que no está claro", sub: "El estudio trae tres corrientes de falla: te mostramos cuáles y te preguntamos cuál usar." },
  { at: 74, title: "Revisamos que sea segura", sub: "Calculamos la tensión de contacto y de paso con IEEE 80. Esta primera versión no cumple." },
  { at: 91, title: "Mejoramos el diseño", sub: "Ajustamos la malla y recalculamos. Si todavía no cumple, te decimos qué falta." },
  { at: 135, title: "Te entregamos el estudio", sub: "Publicado como página y PDF, con el origen de cada dato." },
];

const chapterAt = (time) => CHAPTERS.reduce((current, chapter, index) => (time >= chapter.at - 0.3 ? index : current), 0);
const clock = (seconds) => `${Math.floor(seconds / 60)}:${String(Math.floor(seconds % 60)).padStart(2, "0")}`;

// Miniature for the hero: the recording, muted and looping.
export function VideoThumbnail({ reducedMotion, href = "#demo" }) {
  return <a className="demo-thumb" href={href} aria-label="Ver la demo grabada">
    <div className="demo-thumb-frame" aria-hidden="true">
      {reducedMotion
        ? <img src={POSTER} alt="" />
        : <video src={`${VIDEO}#t=30`} poster={POSTER} muted autoPlay loop playsInline preload="metadata" />}
    </div>
    <span className="demo-thumb-label"><span className="demo-thumb-play"><Play size={11} fill="currentColor" /></span>Míralo funcionando<small>Grabación real · 2:44</small></span>
  </a>;
}

export function LandingVideo() {
  const videoRef = useRef(null);
  const [chapter, setChapter] = useState(0);
  const [time, setTime] = useState(0);
  const [duration, setDuration] = useState(164);

  // Plays muted while the section is on screen, so it reads as a demo without a click.
  useEffect(() => {
    const video = videoRef.current;
    if (!video || !("IntersectionObserver" in window)) return undefined;
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const observer = new IntersectionObserver(([entry]) => {
      if (entry.isIntersecting && !reduced) video.play().catch(() => {});
      else if (!entry.isIntersecting) video.pause();
    }, { threshold: 0.45 });
    observer.observe(video);
    return () => observer.disconnect();
  }, []);

  const seek = (index) => {
    const video = videoRef.current;
    if (!video) return;
    video.currentTime = CHAPTERS[index].at;
    setChapter(index);
    video.play().catch(() => {});
  };
  const current = CHAPTERS[chapter];

  return <section className="landing-video" id="demo" data-formation="0" aria-label="Demo grabada">
    <div className="landing-video-head">
      <p className="landing-eyebrow">Demo · grabación real</p>
      <h2 key={chapter} className="landing-video-title">{current.title}</h2>
      <p className="landing-video-sub">{current.sub}</p>
    </div>
    <div className="landing-video-body">
      <div className="landing-video-frame">
        <video
          ref={videoRef}
          src={VIDEO}
          poster={POSTER}
          muted
          playsInline
          controls
          preload="metadata"
          onLoadedMetadata={(event) => setDuration(event.currentTarget.duration || 164)}
          onTimeUpdate={(event) => { const t = event.currentTarget.currentTime; setTime(t); setChapter(chapterAt(t)); }}
        />
      </div>
      <ol className="landing-video-chapters">
        {CHAPTERS.map((item, index) => {
          const end = CHAPTERS[index + 1]?.at ?? duration;
          const fill = index < chapter ? 1 : index === chapter ? Math.min(1, Math.max(0, (time - item.at) / (end - item.at))) : 0;
          return <li key={item.title}>
            <button type="button" className={index === chapter ? "active" : index < chapter ? "done" : ""} onClick={() => seek(index)}>
              <span className="landing-video-time">{clock(item.at)}</span>
              <span>{item.title}</span>
              <i style={{ transform: `scaleX(${fill})` }} />
            </button>
          </li>;
        })}
      </ol>
    </div>
    <p className="landing-video-note">Grabado con el agente y el cálculo reales sobre un proyecto de ejemplo. Las esperas están aceleradas.</p>
  </section>;
}
