from contextlib import asynccontextmanager
from dataclasses import asdict
from time import monotonic, time
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request as UrlRequest, urlopen
from uuid import uuid4
import json
import os

from fastapi import FastAPI, HTTPException, Depends, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError

from src.domain.identity import ServiceError
from src.infrastructure.entrypoint.api.schemas import ProjectRequest
from src.infrastructure.entrypoint.api.identity_routes import router
from src.infrastructure.entrypoint.api.file_routes import router as file_router
from src.infrastructure.entrypoint.api.billing_routes import router as billing_router
from src.infrastructure.entrypoint.api.chat_routes import router as chat_router
from src.infrastructure.entrypoint.api.agent_routes import router as agent_router
from src.infrastructure.entrypoint.api.artifact_routes import catalog_router, router as artifact_router
from src.infrastructure.entrypoint.api.knowledge_graph_routes import (
    router as knowledge_graph_router,
)
from src.infrastructure.entrypoint.api.system_routes import router as system_router
from src.infrastructure.entrypoint.api.study_routes import router as study_router, public_router as public_study_router
from src.infrastructure.entrypoint.api.optimizer_routes import router as optimizer_router
from src.infrastructure.entrypoint.api.material_catalog_routes import router as material_catalog_router
from src.infrastructure.entrypoint.api.material_catalog_persistence_routes import (
    router as material_catalog_persistence_router,
)
from src.infrastructure.entrypoint.api.constraint_profile_routes import (
    router as constraint_profile_router,
)
from src.infrastructure.security.container import build_services
from src.infrastructure.security.middleware import (
    AuthenticationMiddleware,
    require,
    validate_endpoint_policies,
)
from src.infrastructure.security.settings import Settings


def create_app(settings=None, services=None):
    @asynccontextmanager
    async def lifespan(app):
        validate_endpoint_policies(app)
        app.state.services = services or build_services(settings or Settings.from_env())
        try:
            yield
        finally:
            if services is None:
                app.state.services.store.engine.dispose()

    app = FastAPI(title="SPAT Design Agent", version="0.2.0", lifespan=lifespan)
    app.add_middleware(AuthenticationMiddleware)
    app.include_router(router)
    app.include_router(file_router)
    app.include_router(billing_router)
    app.include_router(chat_router)
    app.include_router(agent_router)
    app.include_router(artifact_router)
    app.include_router(catalog_router)
    app.include_router(knowledge_graph_router)
    app.include_router(system_router)
    app.include_router(study_router)
    app.include_router(public_study_router)
    app.include_router(material_catalog_router)
    app.include_router(material_catalog_persistence_router)
    app.include_router(constraint_profile_router)
    app.include_router(optimizer_router)
    app.state.geocoder_search_url = getattr(
        settings,
        "geocoder_search_url",
        os.getenv("SPAT_GEOCODER_SEARCH_URL", "https://nominatim.openstreetmap.org/search"),
    )
    app.state.geocoder_cache = {}

    @app.get("/api/v1/locations/search", tags=["locations"])
    def search_locations(
        actor=Depends(require()), country: str | None = None, city: str | None = None
    ):
        country = (country or "").strip()[:120]
        city = (city or "").strip()[:120]
        if not country and not city:
            raise HTTPException(422, "Enter a country or city to search")
        query = ", ".join(part for part in (city, country) if part)
        cache_key = query.casefold()
        cached = app.state.geocoder_cache.get(cache_key)
        if cached and cached[0] > monotonic():
            return cached[1]
        # A shared SQL-backed throttle keeps the public geocoder below its
        # per-application request limit across API worker processes.
        app.state.services.identity.throttle("location_search", "nominatim", limit=1, seconds=2)
        params = urlencode({"q": query, "format": "jsonv2", "addressdetails": 1, "limit": 5})
        url = f"{app.state.geocoder_search_url}?{params}"
        request = UrlRequest(url, headers={"User-Agent": "TerraWorkspace/0.1 (location search)"})
        try:
            with urlopen(request, timeout=12) as response:
                matches = json.loads(response.read(512_000))
        except (OSError, URLError, ValueError) as exc:
            raise HTTPException(502, "The city search service is unavailable") from exc
        results = []
        for match in matches:
            address = match.get("address", {})
            results.append({
                "label": match.get("display_name", query),
                "latitude": float(match["lat"]),
                "longitude": float(match["lon"]),
                "city": address.get("city") or address.get("town") or address.get("village") or address.get("municipality") or city,
                "country": address.get("country") or country,
            })
        payload = {"results": results}
        app.state.geocoder_cache[cache_key] = (monotonic() + 86_400, payload)
        return payload

    def project_record(db, project_id, actor):
        record = db.one("projects", id=project_id)
        if record is None or (not actor.privileged and record["owner_id"] != actor.user_id):
            raise HTTPException(404, "Project not found")
        return record

    @app.get("/api/v1/projects", tags=["projects"])
    def list_projects(actor=Depends(require())):
        with app.state.services.store.transaction() as db:
            from src.infrastructure.entrypoint.api.artifact_routes import design_status
            return [{**project, "design_status": design_status(db, project["id"])}
                    for project in db.many("projects", owner_id=actor.user_id, limit=500)]

    @app.get("/api/v1/projects/{project_id}", tags=["projects"])
    def get_project(project_id: str, actor=Depends(require())):
        with app.state.services.store.transaction() as db:
            from src.infrastructure.entrypoint.api.artifact_routes import design_status
            record = project_record(db, project_id, actor)
            return {**record, "design_status": design_status(db, project_id)}

    @app.post("/api/v1/projects", status_code=201, tags=["projects"])
    def create_project(data: ProjectRequest, actor=Depends(require())):
        from time import time
        now = int(time())
        record = {"id": uuid4().hex[:12], "owner_id": actor.user_id, **data.model_dump(), "created_at": now, "updated_at": now}
        with app.state.services.store.transaction(write=True) as db:
            db.add("projects", **record)
        return record

    @app.patch("/api/v1/projects/{project_id}", tags=["projects"])
    def update_project(project_id: str, data: ProjectRequest, actor=Depends(require())):
        from time import time
        with app.state.services.store.transaction(write=True) as db:
            project_record(db, project_id, actor)
            changes = data.model_dump()
            changes["updated_at"] = int(time())
            db.change("projects", project_id, **changes)
            return db.one("projects", id=project_id)

    @app.delete("/api/v1/projects/{project_id}", status_code=204, tags=["projects"])
    def delete_project(project_id: str, actor=Depends(require())):
        with app.state.services.store.transaction(write=True) as db:
            project_record(db, project_id, actor)
            db.remove("projects", project_id)
        return Response(status_code=204)

    @app.exception_handler(ServiceError)
    async def service_error(request, exc):
        headers = {"WWW-Authenticate": "Bearer"} if exc.status == 401 else {}
        if exc.status == 429:
            headers["Retry-After"] = "300"
        return JSONResponse(
            {"detail": exc.message}, status_code=exc.status, headers=headers
        )

    @app.exception_handler(IntegrityError)
    async def conflict(request, exc):
        return JSONResponse(
            {"detail": "Conflicting record or invalid reference"}, status_code=409
        )

    @app.get("/health", tags=["health"])
    def health():
        return {"status": "ok", "service": "spat-design-agent"}

    @app.get("/ready", tags=["health"])
    def ready(request: Request):
        with request.app.state.services.store.transaction() as db:
            if not db.one("security_lock", id="identity"):
                raise HTTPException(503, "Database not initialized")
        return {"status": "ready"}

    @app.post("/api/v1/designs/assess", status_code=410, tags=["designs"], deprecated=True)
    def retired_design_assessment(actor=Depends(require())):
        raise HTTPException(
            410,
            "Este estimador preliminar fue retirado. Use el flujo trazable de artefactos "
            "POST /api/v1/projects/{project_id}/artefactos-diseno-tierras y "
            "POST /api/v1/projects/{project_id}/artefactos-diseno-tierras/{artifact_id}/versions/{version}/calculos-potencial.",
        )

    return app


app = create_app()
