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

from src.application.use_cases.assess_grounding_design import AssessGroundingDesign
from src.domain.identity import ServiceError
from src.domain.spat.models import (
    FaultScenario,
    GroundingDesign,
    GridGeometry,
    SoilLayer,
)
from src.infrastructure.calculations.ieee80_calculator import (
    PreliminaryIEEE80Calculator,
)
from src.infrastructure.entrypoint.api.schemas import DesignRequest, ProjectRequest
from src.infrastructure.entrypoint.api.identity_routes import router
from src.infrastructure.entrypoint.api.file_routes import router as file_router
from src.infrastructure.entrypoint.api.chat_routes import router as chat_router
from src.infrastructure.entrypoint.api.artifact_routes import router as artifact_router
from src.infrastructure.persistence.in_memory_design_repository import (
    InMemoryDesignRepository,
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
    app.include_router(chat_router)
    app.include_router(artifact_router)
    app.state.geocoder_search_url = getattr(
        settings,
        "geocoder_search_url",
        os.getenv("SPAT_GEOCODER_SEARCH_URL", "https://nominatim.openstreetmap.org/search"),
    )
    app.state.geocoder_cache = {}
    repository = InMemoryDesignRepository()
    assess = AssessGroundingDesign(repository, PreliminaryIEEE80Calculator())
    design_owners = {}

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
            return db.many("projects", owner_id=actor.user_id, limit=500)

    @app.get("/api/v1/projects/{project_id}", tags=["projects"])
    def get_project(project_id: str, actor=Depends(require())):
        with app.state.services.store.transaction() as db:
            return project_record(db, project_id, actor)

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

    @app.post("/api/v1/designs/assess", status_code=201, tags=["designs"])
    def create_design(request: DesignRequest, actor=Depends(require("designs:write"))):
        design = GroundingDesign(
            design_id=str(uuid4()),
            name=request.name,
            geometry=GridGeometry(**request.geometry.model_dump()),
            soil_layers=[
                SoilLayer(**layer.model_dump()) for layer in request.soil_layers
            ],
            fault=FaultScenario(**request.fault.model_dump()),
        )
        result = assess.execute(design)
        design_owners[design.design_id] = actor.user_id
        return asdict(result)

    @app.get("/api/v1/designs/{design_id}", tags=["designs"])
    def get_design(design_id: str, actor=Depends(require("designs:read"))):
        design = repository.get(design_id)
        if design is None or (
            not actor.privileged and design_owners.get(design_id) != actor.user_id
        ):
            raise HTTPException(404, "Design not found")
        return asdict(design)

    return app


app = create_app()
