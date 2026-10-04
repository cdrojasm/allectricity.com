import os
from dataclasses import dataclass, field
from urllib.parse import urlparse


@dataclass(frozen=True)
class Settings:
    database_url: str = field(repr=False)
    jwt_secret: str = field(repr=False)
    mail_key: str = field(repr=False)
    issuer: str = "spat-api"
    audience: str = "spat-workspace"
    access_seconds: int = 900
    refresh_seconds: int = 2592000
    reset_seconds: int = 1800
    reset_url: str = "http://localhost:3000/reset-password"
    google_client_id: str = ""
    geocoder_search_url: str = "https://nominatim.openstreetmap.org/search"
    environment: str = "local"

    def __post_init__(self):
        if len(self.jwt_secret.encode()) < 32:
            raise ValueError("AUTH_JWT_SECRET must contain at least 32 bytes")
        if not self.issuer or not self.audience:
            raise ValueError("JWT issuer and audience are required")
        if min(self.access_seconds, self.refresh_seconds, self.reset_seconds) <= 0:
            raise ValueError("Token lifetimes must be positive")
        url = urlparse(self.reset_url)
        if not url.netloc or url.fragment or url.query:
            raise ValueError(
                "AUTH_RESET_URL must be an absolute URL without query or fragment"
            )
        if url.scheme != "https" and not (
            self.environment in {"local", "test"}
            and url.hostname in {"localhost", "127.0.0.1"}
        ):
            raise ValueError("AUTH_RESET_URL must use HTTPS outside local/test")

    @classmethod
    def from_env(cls):
        return cls(
            database_url=os.environ["DATABASE_URL"],
            jwt_secret=os.environ["AUTH_JWT_SECRET"],
            mail_key=os.environ["AUTH_MAIL_ENCRYPTION_KEY"],
            issuer=os.getenv("AUTH_JWT_ISSUER", "spat-api"),
            audience=os.getenv("AUTH_JWT_AUDIENCE", "spat-workspace"),
            access_seconds=int(os.getenv("AUTH_ACCESS_SECONDS", "900")),
            refresh_seconds=int(os.getenv("AUTH_REFRESH_SECONDS", "2592000")),
            reset_seconds=int(os.getenv("AUTH_RESET_SECONDS", "1800")),
            reset_url=os.getenv(
                "AUTH_RESET_URL", "http://localhost:3000/reset-password"
            ),
            google_client_id=os.getenv("GOOGLE_CLIENT_ID", ""),
            geocoder_search_url=os.getenv(
                "SPAT_GEOCODER_SEARCH_URL", "https://nominatim.openstreetmap.org/search"
            ),
            environment=os.getenv("SPAT_ENVIRONMENT", "local"),
        )
