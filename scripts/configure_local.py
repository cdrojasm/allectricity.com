"""Create local-only secrets without overwriting an existing environment."""

import base64
import os
from pathlib import Path
import secrets

root = Path(__file__).resolve().parent.parent
template = (root / "config/.env.example").read_text()
for key, value in {
    "__POSTGRES_PASSWORD__": secrets.token_hex(24),
    "__JWT_SECRET__": secrets.token_urlsafe(48),
    "__MAIL_KEY__": base64.urlsafe_b64encode(secrets.token_bytes(32)).decode(),
    "__MINIO_ACCESS_KEY__": "spat" + secrets.token_hex(8),
    "__MINIO_SECRET_KEY__": secrets.token_urlsafe(36),
    "__MINIO_WEBHOOK_TOKEN__": secrets.token_urlsafe(32),
    "__NEO4J_PASSWORD__": secrets.token_urlsafe(32),
    "__OCR_INTERNAL_TOKEN__": secrets.token_urlsafe(32),
}.items():
    template = template.replace(key, value)
try:
    fd = os.open(root / ".env", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
except FileExistsError:
    raise SystemExit(".env already exists; preserved without modification")
with os.fdopen(fd, "w") as stream:
    stream.write(template)
print("Created local .env with private permissions; secrets were not printed.")
