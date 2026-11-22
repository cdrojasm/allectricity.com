import React from "react";

// Illustrations for empty states: one 96 px scene per situation, in the app's greens.
const ART = {
  // A gauge with no needle yet: nothing has been calculated.
  calculate: <><circle cx="48" cy="48" r="40" fill="var(--es-bg)"/><path d="M24 58a24 24 0 1 1 48 0" fill="none" stroke="var(--es-line)" strokeWidth="3" strokeLinecap="round"/><path d="M48 58 58 40" stroke="var(--es-accent)" strokeWidth="3" strokeLinecap="round" strokeDasharray="3 4"/><circle cx="48" cy="58" r="4" fill="var(--es-accent)"/><path d="M30 68h36" stroke="var(--es-line)" strokeWidth="3" strokeLinecap="round"/></>,
  // A checklist with open boxes: data is missing.
  missing: <><circle cx="48" cy="48" r="40" fill="var(--es-warn-bg)"/><rect x="28" y="24" width="40" height="50" rx="6" fill="#fff" stroke="var(--es-warn)" strokeWidth="3"/><rect x="35" y="34" width="7" height="7" rx="2" fill="none" stroke="var(--es-warn)" strokeWidth="2.5"/><path d="M47 37.5h14" stroke="var(--es-warn)" strokeWidth="2.5" strokeLinecap="round"/><path d="m35.5 52 2.5 2.5 4.5-5" stroke="var(--es-warn)" strokeWidth="2.5" fill="none" strokeLinecap="round" strokeLinejoin="round"/><path d="M47 52h14" stroke="var(--es-warn)" strokeWidth="2.5" strokeLinecap="round"/><rect x="35" y="61" width="7" height="7" rx="2" fill="none" stroke="var(--es-warn)" strokeWidth="2.5"/><path d="M47 64.5h10" stroke="var(--es-warn)" strokeWidth="2.5" strokeLinecap="round"/></>,
  // A grid drawn in dashes: no mesh yet.
  mesh: <><circle cx="48" cy="48" r="40" fill="var(--es-bg)"/><rect x="26" y="26" width="44" height="44" rx="3" fill="#fff" stroke="var(--es-accent)" strokeWidth="3" strokeDasharray="5 4"/><path d="M48 26v44M26 48h44" stroke="var(--es-line)" strokeWidth="2.5" strokeDasharray="4 4"/><circle cx="26" cy="26" r="4" fill="var(--es-accent)"/><circle cx="70" cy="70" r="4" fill="var(--es-accent)"/></>,
  // Stacked documents: no sources.
  documents: <><circle cx="48" cy="48" r="40" fill="var(--es-bg)"/><rect x="34" y="22" width="34" height="44" rx="5" fill="#fff" stroke="var(--es-line)" strokeWidth="3"/><rect x="26" y="30" width="34" height="44" rx="5" fill="#fff" stroke="var(--es-accent)" strokeWidth="3"/><path d="M33 44h20M33 52h20M33 60h12" stroke="var(--es-line)" strokeWidth="2.5" strokeLinecap="round"/></>,
  // A list with a reel of conductor: no bill of materials.
  materials: <><circle cx="48" cy="48" r="40" fill="var(--es-bg)"/><rect x="26" y="24" width="36" height="48" rx="5" fill="#fff" stroke="var(--es-accent)" strokeWidth="3"/><path d="M33 36h22M33 46h22M33 56h14" stroke="var(--es-line)" strokeWidth="2.5" strokeLinecap="round"/><circle cx="66" cy="64" r="11" fill="#fff" stroke="var(--es-accent)" strokeWidth="3"/><circle cx="66" cy="64" r="3.5" fill="var(--es-accent)"/></>,
  // A report with bars: no study.
  report: <><circle cx="48" cy="48" r="40" fill="var(--es-bg)"/><path d="M30 22h26l10 10v42H30z" fill="#fff" stroke="var(--es-accent)" strokeWidth="3" strokeLinejoin="round"/><path d="M56 22v10h10" fill="none" stroke="var(--es-accent)" strokeWidth="3" strokeLinejoin="round"/><path d="M39 64V54M48 64V44M57 64v-6" stroke="var(--es-line)" strokeWidth="4" strokeLinecap="round"/></>,
  // A check: everything is ready.
  ready: <><circle cx="48" cy="48" r="40" fill="var(--es-bg)"/><circle cx="48" cy="48" r="24" fill="#fff" stroke="var(--es-accent)" strokeWidth="3"/><path d="m37 48.5 7.5 7.5L60 40.5" fill="none" stroke="var(--es-accent)" strokeWidth="4" strokeLinecap="round" strokeLinejoin="round"/></>,
  // A spark: start talking to the agent.
  agent: <><circle cx="48" cy="48" r="40" fill="var(--es-bg)"/><path d="M48 24 53 41l17 5-17 5-5 17-5-17-17-5 17-5 5-17Z" fill="#fff" stroke="var(--es-accent)" strokeWidth="3" strokeLinejoin="round"/></>,
};

/**
 * What a section shows while it has nothing yet: a picture of what is missing, what it means, and the one
 * action that fills it. `children` can add detail under the action (for example, the list of missing data).
 */
export function EmptyState({ art = "calculate", title, description, action, secondary, children, compact = false, testId }) {
  return <section className={`empty-state${compact ? " compact" : ""}`} data-testid={testId}>
    <svg className="empty-state-art" viewBox="0 0 96 96" aria-hidden="true">{ART[art] || ART.calculate}</svg>
    <h3>{title}</h3>
    {description && <p>{description}</p>}
    {(action || secondary) && <div className="empty-state-actions">{action}{secondary}</div>}
    {children}
  </section>;
}
