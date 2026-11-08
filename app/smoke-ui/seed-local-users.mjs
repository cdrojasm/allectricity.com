// SOLO DESARROLLO LOCAL: crea un usuario de prueba por perfil dentro del stack Docker y escribe
// app/.env.smoke-ui (ignorado por git). En producción no se usa: ahí las credenciales las pones tú.
import { execFileSync } from "node:child_process";
import { randomBytes } from "node:crypto";
import fs from "node:fs";
import path from "node:path";

const ROOT = path.resolve(import.meta.dirname, "../..");
const COMPOSE = ["compose", "--env-file", path.join(ROOT, ".env"), "-f", path.join(ROOT, "deploy/local/docker/docker-compose.yml")];
const ROLES = ["designer", "viewer", "user_admin"];
const script = `
import os
from src.application.use_cases.identity import assign, new_user
from src.infrastructure.security.container import build_services
from src.infrastructure.security.settings import Settings
s = build_services(Settings.from_env())
with s.store.transaction(write=True) as db:
    u = new_user(db, email=os.environ["E_EMAIL"], first_name="Smoke", last_name=os.environ["E_ROLE"],
                 password_hash=s.identity.passwords.hash(os.environ["E_PASSWORD"]))
    assign(db, u["id"], os.environ["E_ROLE"])
`;
const lines = ["SMOKE_BASE_URL=http://127.0.0.1:3001"];
const stamp = Date.now();
for (const role of ROLES) {
  const email = `smoke-ui-${role}-${stamp}@example.com`;
  const password = randomBytes(18).toString("base64url");
  execFileSync("docker", [...COMPOSE, "exec", "-T", "-e", "E_EMAIL", "-e", "E_PASSWORD", "-e", "E_ROLE", "api", "python", "-c", script],
    { env: { ...process.env, E_EMAIL: email, E_PASSWORD: password, E_ROLE: role }, stdio: ["ignore", "ignore", "inherit"] });
  const key = role.toUpperCase();
  lines.push(`SMOKE_${key}_EMAIL=${email}`, `SMOKE_${key}_PASSWORD=${password}`);
}
const out = path.resolve(import.meta.dirname, "../.env.smoke-ui");
fs.writeFileSync(out, lines.join("\n") + "\n", { mode: 0o600 });
console.log(`Usuarios creados para: ${ROLES.join(", ")} -> ${path.relative(ROOT, out)}`);
