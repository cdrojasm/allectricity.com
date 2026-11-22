import React from "react";

// Domain icons drawn for Allectricity: one 24 px grid, 1.6 stroke, round joins, currentColor.
// Generic UI actions (close, chevrons, undo…) keep lucide; these name the engineering concepts.
function Svg({ size = 16, title, children, ...props }) {
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden={title ? undefined : true} role={title ? "img" : undefined} focusable="false" {...props}>{title && <title>{title}</title>}{children}</svg>;
}

// Overview: the design sheet with its grid thumbnail.
export const IconOverview = (p) => <Svg {...p}><rect x="3.5" y="3.5" width="17" height="17" rx="2.5"/><path d="M7.5 8h9M7.5 12h4M7.5 16h4"/><rect x="13.5" y="11" width="3.5" height="5.5" rx=".8"/></Svg>;
// Sources: stacked documents.
export const IconSources = (p) => <Svg {...p}><path d="M8 3.5h6.5l4 4v10a1.5 1.5 0 0 1-1.5 1.5H8a1.5 1.5 0 0 1-1.5-1.5V5A1.5 1.5 0 0 1 8 3.5Z"/><path d="M14.5 3.5v4h4"/><path d="M4 7.5v11A2 2 0 0 0 6 20.5h8.5"/><path d="M9.5 12h5M9.5 15h3.5"/></Svg>;
// Measurements: four Wenner probes in the ground with the reading line.
export const IconMeasurements = (p) => <Svg {...p}><path d="M3 14.5h18"/><path d="M5 9v8M10 9v8M14 9v8M19 9v8"/><path d="M5 6.5h14"/><path d="M5 6.5v2.5M19 6.5v2.5"/></Svg>;
// Soil: stratified layers under the surface.
export const IconSoil = (p) => <Svg {...p}><path d="M3 6.5c3-1.4 6 1.4 9 0s6-1.4 9 0"/><path d="M3 11.5h18"/><path d="M3 16.5h18"/><path d="M6 9v.01M11 14v.01M16 9v.01M8 19v.01M15 19v.01M18 14v.01"/></Svg>;
// Electrical parameters: fault current, a bolt over the ground mark.
export const IconParameters = (p) => <Svg {...p}><path d="M13 3 7.5 12.5h4.5L10.5 19l6-9.5H12L13 3Z"/><path d="M5 20.5h14"/></Svg>;
// Plan: the grounding grid with rods at the corners.
export const IconPlan = (p) => <Svg {...p}><rect x="4" y="4" width="16" height="16" rx="1"/><path d="M4 12h16M12 4v16"/><circle cx="4" cy="4" r="1.6" fill="currentColor" stroke="none"/><circle cx="20" cy="4" r="1.6" fill="currentColor" stroke="none"/><circle cx="4" cy="20" r="1.6" fill="currentColor" stroke="none"/><circle cx="20" cy="20" r="1.6" fill="currentColor" stroke="none"/></Svg>;
// Result: a gauge against its limit.
export const IconResult = (p) => <Svg {...p}><path d="M4 16.5a8 8 0 1 1 16 0"/><path d="M12 16.5 15.5 10"/><circle cx="12" cy="16.5" r="1.3"/><path d="M4 20h16"/><path d="M17.6 11.2l1.3-.8" /></Svg>;
// Bill of materials: a list with a conductor reel.
export const IconMaterials = (p) => <Svg {...p}><rect x="4" y="3.5" width="16" height="17" rx="2"/><path d="M8 8h8M8 12h8M8 16h5"/><path d="M6.2 8h.01M6.2 12h.01M6.2 16h.01"/></Svg>;
// 3D surface.
export const Icon3D = (p) => <Svg {...p}><path d="M3 15.5 12 20l9-4.5"/><path d="M3 15.5c2-1 2.5-6 5-6s3 4 4.5 4 2.5-7 5-7 2.5 5 3.5 9"/><path d="M12 20v-6.5"/></Svg>;
// Surface potential map.
export const IconPotential = (p) => <Svg {...p}><rect x="3.5" y="3.5" width="17" height="17" rx="2"/><rect x="8" y="8" width="8" height="8" rx="1" strokeDasharray="2 1.6"/><circle cx="12" cy="12" r="1.2" fill="currentColor" stroke="none"/></Svg>;
// Calculation options: two sliders.
export const IconOptions = (p) => <Svg {...p}><path d="M4 7h10M18 7h2M4 17h2M10 17h10"/><circle cx="16" cy="7" r="2"/><circle cx="8" cy="17" r="2"/></Svg>;
// Improve: an arrow rising out of the grid.
export const IconImprove = (p) => <Svg {...p}><path d="M4 20h16"/><path d="M6 16.5 10.5 12l3 3L19 9.5"/><path d="M15 9.5h4v4"/></Svg>;
// Agent: the Allectricity spark.
export const IconAgent = (p) => <Svg {...p}><path d="M12 3.5 13.8 9l5.7 1.5-5.7 1.6L12 17.5l-1.8-5.4-5.7-1.6L10.2 9 12 3.5Z"/><path d="M18.5 16v4M16.5 18h4"/></Svg>;
// Mathematical optimizer: a cost curve with its minimum.
export const IconOptimizer = (p) => <Svg {...p}><path d="M4 5c1.5 9 4 12 8 12s6.5-3 8-12"/><circle cx="12" cy="17" r="1.6"/><path d="M4 21h16"/></Svg>;
// Suggestion: a light bulb.
export const IconSuggestion = (p) => <Svg {...p}><path d="M9 18h6M10 21h4"/><path d="M12 3a6 6 0 0 0-3.6 10.8c.7.5 1.1 1.3 1.1 2.2h5c0-.9.4-1.7 1.1-2.2A6 6 0 0 0 12 3Z"/></Svg>;
// Warning triangle and information.
export const IconWarning = (p) => <Svg {...p}><path d="M12 4 2.8 19.5h18.4L12 4Z"/><path d="M12 10v4.2M12 17v.01"/></Svg>;
export const IconInfo = (p) => <Svg {...p}><circle cx="12" cy="12" r="8.5"/><path d="M12 11v5.5M12 7.8v.01"/></Svg>;
export const IconCheckCircle = (p) => <Svg {...p}><circle cx="12" cy="12" r="8.5"/><path d="m8.3 12.2 2.5 2.5 5-5.2"/></Svg>;
export const IconFailCircle = (p) => <Svg {...p}><circle cx="12" cy="12" r="8.5"/><path d="M12 7.5v5.5M12 16.3v.01"/></Svg>;
// Print.
export const IconPrint = (p) => <Svg {...p}><path d="M7 8V3.5h10V8"/><rect x="3.5" y="8" width="17" height="8.5" rx="2"/><path d="M7 14h10v6.5H7z"/><path d="M17 11h.01"/></Svg>;
// Study / report.
export const IconReport = (p) => <Svg {...p}><path d="M6 3.5h9l3.5 3.5v13.5H6z"/><path d="M15 3.5V7h3.5"/><path d="M9 17v-3M12 17v-6M15 17v-4"/></Svg>;
// Report blocks of the study composer.
export const IconText = (p) => <Svg {...p}><path d="M5 6.5h14M5 10.5h14M5 14.5h14M5 18.5h8"/></Svg>;
export const IconInputs = (p) => <Svg {...p}><path d="M4 6h16M4 12h16M4 18h16"/><circle cx="9" cy="6" r="1.8" fill="var(--icon-fill, #fff)"/><circle cx="15" cy="12" r="1.8" fill="var(--icon-fill, #fff)"/><circle cx="7" cy="18" r="1.8" fill="var(--icon-fill, #fff)"/></Svg>;
export const IconReferences = (p) => <Svg {...p}><path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7L11.5 6.8"/><path d="M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1.5-1.5"/></Svg>;
// Material catalog: a price-tagged box.
export const IconCatalog = (p) => <Svg {...p}><path d="M3.5 8 12 3.5 20.5 8v8L12 20.5 3.5 16z"/><path d="M3.5 8 12 12.5 20.5 8M12 12.5v8"/></Svg>;
// All projects: a grid of project cards.
export const IconProjects = (p) => <Svg {...p}><rect x="3.5" y="3.5" width="7" height="7" rx="1.5"/><rect x="13.5" y="3.5" width="7" height="7" rx="1.5"/><rect x="3.5" y="13.5" width="7" height="7" rx="1.5"/><rect x="13.5" y="13.5" width="7" height="7" rx="1.5"/></Svg>;
