import React, { useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { ExternalLink, X } from "lucide-react";
import { HELP } from "../help.jsx";

/**
 * «?» next to a field: opens a card with what the value means, its equation, a small figure when a picture
 * says it better, where the number usually comes from, and a reference. The card is portalled to <body>,
 * so scrolling panels never clip it.
 */
export function HelpTip({ topic, label }) {
  const entry = HELP[topic];
  const [open, setOpen] = useState(false);
  const [position, setPosition] = useState(null);
  const button = useRef(null);
  const card = useRef(null);
  useLayoutEffect(() => {
    if (!open || !button.current) return;
    const place = () => {
      const anchor = button.current.getBoundingClientRect();
      const width = Math.min(340, window.innerWidth - 24);
      const height = card.current?.offsetHeight || 260;
      const left = Math.max(12, Math.min(anchor.left - 16, window.innerWidth - width - 12));
      const below = anchor.bottom + 8;
      const top = below + height > window.innerHeight - 12 ? Math.max(12, anchor.top - height - 8) : below;
      setPosition({ left, top, width });
    };
    place();
    const frame = requestAnimationFrame(place);
    return () => cancelAnimationFrame(frame);
  }, [open]);
  useEffect(() => {
    if (!open) return undefined;
    const close = (event) => { if (!card.current?.contains(event.target) && !button.current?.contains(event.target)) setOpen(false); };
    const onKey = (event) => { if (event.key === "Escape") { setOpen(false); button.current?.focus(); } };
    const onScroll = (event) => { if (!card.current?.contains(event.target)) setOpen(false); };
    document.addEventListener("pointerdown", close);
    document.addEventListener("keydown", onKey);
    window.addEventListener("scroll", onScroll, true);
    window.addEventListener("resize", onScroll);
    return () => { document.removeEventListener("pointerdown", close); document.removeEventListener("keydown", onKey); window.removeEventListener("scroll", onScroll, true); window.removeEventListener("resize", onScroll); };
  }, [open]);
  if (!entry) return null;
  return <>
    {/* A span, not a <button>: inside a <label> a button would become the labelled control instead of the field. */}
    <span role="button" tabIndex={0} ref={button} className={`help-tip${open ? " open" : ""}`} aria-label="Más información" title={`Qué es: ${label || entry.title}`} aria-expanded={open}
      onClick={(event) => { event.preventDefault(); event.stopPropagation(); setOpen((value) => !value); }}
      onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); event.stopPropagation(); setOpen((value) => !value); } }}>?</span>
    {open && createPortal(<div ref={card} className="help-card" role="dialog" aria-label={entry.title} style={position ? { left: position.left, top: position.top, width: position.width } : { visibility: "hidden" }}>
      <header><strong>{entry.title}</strong><button type="button" className="icon-button" aria-label="Cerrar ayuda" onClick={() => setOpen(false)}><X size={14}/></button></header>
      <div className="help-card-body">
        {entry.figure && <figure className="help-card-figure">{entry.figure}</figure>}
        {[].concat(entry.text).map((text, index) => <p key={index}>{text}</p>)}
        {entry.formula && <div className="help-card-formula">{[].concat(entry.formula).map((line, index) => <div key={index}>{line}</div>)}{entry.where && <small>{entry.where}</small>}</div>}
        {entry.typical && <p className="help-card-typical"><strong>Valores típicos:</strong> {entry.typical}</p>}
        {entry.source && <p className="help-card-source"><strong>De dónde sale:</strong> {entry.source}</p>}
        {entry.link && <a className="help-card-link" href={entry.link.href} target="_blank" rel="noopener noreferrer">{entry.link.label} <ExternalLink size={12}/></a>}
      </div>
    </div>, document.body)}
  </>;
}

// Field label with its help button, for forms whose labels are plain text.
export function HelpLabel({ text, topic }) {
  return <span className="help-label">{text}<HelpTip topic={topic} label={typeof text === "string" ? text : undefined}/></span>;
}
