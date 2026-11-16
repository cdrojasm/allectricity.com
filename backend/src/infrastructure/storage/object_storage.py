import io
import os
import socket
import struct
import zipfile
from datetime import timedelta

import magic
from minio import Minio
from minio.commonconfig import REPLACE, CopySource
from minio.error import S3Error


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
        # Con región fija el firmante no consulta el bucket: el endpoint público no es
        # alcanzable desde el contenedor y solo se usa para firmar URLs del navegador.
        # The public host can be HTTPS while the private one is plain HTTP (Railway public domains).
        public_secure = os.getenv("MINIO_PUBLIC_SECURE", str(secure)).lower() == "true"
        self.signer = Minio(public_endpoint, access_key=access_key, secret_key=secret_key, secure=public_secure,
                            region=os.getenv("MINIO_REGION", "us-east-1")) if public_endpoint else self.client
        self.quarantine_bucket = os.getenv("MINIO_QUARANTINE_BUCKET", "quarantine")
        self.allowed_buckets = {
            "documents": os.getenv("MINIO_DOCUMENTS_BUCKET", "documents"),
            "designs": os.getenv("MINIO_DESIGNS_BUCKET", "designs"),
            "templates": os.getenv("MINIO_TEMPLATES_BUCKET", "plantillas"),
        }

    def presign_upload(self, key, mime_type):
        return self.signer.presigned_put_object(self.quarantine_bucket, key,
                                                expires=timedelta(seconds=900))

    def presign_download(self, bucket, key, filename=None):
        if bucket not in self.allowed_buckets.values():
            raise ValueError("Bucket is not readable")
        headers = {"response-content-disposition": f'attachment; filename="{filename}"'} if filename else None
        return self.signer.presigned_get_object(bucket, key, expires=timedelta(seconds=300),
                                                response_headers=headers)

    def missing_buckets(self):
        """Buckets the deployment expects but MinIO does not have (empty when healthy)."""
        expected = [self.quarantine_bucket, *self.allowed_buckets.values()]
        return [bucket for bucket in expected if not self.client.bucket_exists(bucket)]

    def read(self, key, max_bytes):
        return self._read(self.quarantine_bucket, key, max_bytes)

    def read_object(self, bucket, key, max_bytes):
        """Read a promoted (scanned) object from one of the allowed buckets."""
        if bucket not in self.allowed_buckets.values():
            raise ValueError("Bucket is not readable")
        return self._read(bucket, key, max_bytes)

    def exists(self, bucket, key):
        try:
            self.client.stat_object(bucket, key)
            return True
        except S3Error as exc:
            if exc.code in {"NoSuchKey", "NoSuchObject"}:
                return False
            raise

    def remove_quarantine(self, key):
        self.client.remove_object(self.quarantine_bucket, key)

    def _read(self, bucket, key, max_bytes):
        response = self.client.get_object(bucket, key)
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
        # DXF is an ASCII CAD exchange format; libmagic reports it as image/vnd.dxf or text/plain.
        if detected in {"text/plain", "image/vnd.dxf"} and b"SECTION" in data[:4096] and b"ENTITIES" in data:
            return "application/dxf"
        # Some libmagic builds report DOCX as a generic ZIP; confirm the Word part exists.
        if detected in {"application/zip", "application/octet-stream"} and data[:2] == b"PK":
            try:
                with zipfile.ZipFile(io.BytesIO(data)) as archive:
                    if "word/document.xml" in archive.namelist():
                        return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            except zipfile.BadZipFile:
                pass
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
            CopySource(self.quarantine_bucket, key),
            metadata={"Content-Type": mime_type},
            metadata_directive=REPLACE,
        )
        self.client.remove_object(self.quarantine_bucket, key)

    def write_object(self, bucket, key, data, content_type):
        if bucket not in self.allowed_buckets.values():
            raise ValueError("Bucket is not writable")
        self.client.put_object(bucket, key, io.BytesIO(data), len(data), content_type=content_type)
