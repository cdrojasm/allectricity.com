import os
import socket
import struct

import magic
from minio import Minio


class ObjectStorage:
    """MinIO adapter. All untrusted objects enter through the quarantine bucket."""

    def __init__(self):
        access_key = os.environ["MINIO_ACCESS_KEY"]
        secret_key = os.environ["MINIO_SECRET_KEY"]
        secure = os.getenv("MINIO_SECURE", "false").lower() == "true"
        self.client = Minio(
            os.getenv("MINIO_ENDPOINT", "minio:9000"),
            access_key=access_key,
            secret_key=secret_key,
            secure=secure,
        )
        public_endpoint = os.getenv("MINIO_PUBLIC_ENDPOINT")
        self.signer = Minio(public_endpoint, access_key=access_key, secret_key=secret_key, secure=secure) if public_endpoint else self.client
        self.quarantine_bucket = os.getenv("MINIO_QUARANTINE_BUCKET", "quarantine")
        self.allowed_buckets = {
            "documents": os.getenv("MINIO_DOCUMENTS_BUCKET", "documents"),
            "designs": os.getenv("MINIO_DESIGNS_BUCKET", "designs"),
        }

    def presign_upload(self, key, mime_type):
        return self.signer.presigned_put_object(self.quarantine_bucket, key, expires=900)

    def read(self, key, max_bytes):
        response = self.client.get_object(self.quarantine_bucket, key)
        try:
            data = response.read(max_bytes + 1)
            if len(data) > max_bytes:
                raise ValueError("File exceeds the maximum permitted size")
            return data
        finally:
            response.close()
            response.release_conn()

    def detected_mime(self, data):
        detected = magic.from_buffer(data, mime=True)
        # libmagic classifies plain CSV as text/plain; only accept UTF-8 text here.
        if detected == "text/plain" and b"\0" not in data:
            try:
                data.decode("utf-8")
                return "text/csv"
            except UnicodeDecodeError:
                pass
        return detected

    def scan(self, data):
        """Submit bytes to a ClamAV clamd INSTREAM endpoint; fail closed on errors."""
        host = os.getenv("CLAMAV_HOST", "clamav")
        port = int(os.getenv("CLAMAV_PORT", "3310"))
        with socket.create_connection((host, port), timeout=30) as connection:
            connection.settimeout(30)
            connection.sendall(b"zINSTREAM\0")
            for offset in range(0, len(data), 64 * 1024):
                chunk = data[offset : offset + 64 * 1024]
                connection.sendall(struct.pack("!I", len(chunk)) + chunk)
            connection.sendall(struct.pack("!I", 0))
            response = b""
            while not response.endswith(b"\0"):
                part = connection.recv(4096)
                if not part:
                    raise RuntimeError("ClamAV closed the scan connection")
                response += part
        result = response.decode("utf-8", errors="replace").strip("\0")
        if result.endswith(": OK"):
            return
        if result.endswith(" FOUND"):
            raise ValueError("File failed malware scanning")
        raise RuntimeError("ClamAV could not complete the scan")

    def promote(self, key, target_bucket, object_key, mime_type):
        self.client.copy_object(
            target_bucket,
            object_key,
            f"/{self.quarantine_bucket}/{key}",
            metadata={"Content-Type": mime_type},
            metadata_directive="REPLACE",
        )
        self.client.remove_object(self.quarantine_bucket, key)
