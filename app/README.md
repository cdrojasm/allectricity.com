# Allectricity frontend

React workspace for refining a grounding design. Run `npm ci` and `npm run dev`.
`npm run build` produces `dist/`, which can be served by any static host. The
Dockerfile builds the same assets and serves them through nginx.

Run `npm run test:e2e` for browser checks (install Chromium first with
`npx playwright install chromium` if needed). Tests cover parameter editing,
version restoration, attachments, section collapse, mobile width and export.
Run `npm run format` to format the frontend source.

- `src/main.jsx`: workspace, asset graph, chat composer, editable SVG mesh,
  parameter panels, session history and JSON export.
- `src/styles.css`: responsive layout and visual tokens.
- `../deploy/local/docker/docker-compose.yml`: local deployment with Nginx serving
  the frontend and proxying API requests.

The workspace authenticates against the API and uploads PDF, PNG, JPG, CSV and
XLSX files through presigned MinIO URLs. It calls the upload completion endpoint
and polls processing status for each file. Browser speech recognition is
optional and may use a remote service.

## Integration boundaries

Replace the demo response in `send()` with the agent API and stream responses.
Upload IDs and parser status are kept in asset state for the current page
session. Replace the fixed potential curve only after receiving
versioned solver results. Persist parameters and versions through the design
repository; map frontend fields to the backend geometry, soil and fault DTOs.
Pricing currently estimates copper only using an editable USD/m rate.

Geometry is a rectangular interactive preview with at most 20 subdivisions
drawn on either axis for readability. Material length uses full geometry
dimensions and spacing, not the visual subdivision cap. No compliance status
is inferred from these values.
