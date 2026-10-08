"""Consulta y revisión humana del grafo documental de un proyecto (EG-08, EG-11)."""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from src.application.use_cases.knowledge_review import KnowledgeReview
from src.domain.knowledge_graph.claims import DECISIONS, STATUSES, ReviewError
from src.domain.knowledge_graph.taxonomy import ATTRIBUTES, ENTITY_TYPES
from src.infrastructure.entrypoint.api.artifact_routes import owned_project
from src.infrastructure.security.middleware import require

router = APIRouter(prefix="/api/v1/projects/{project_id}/knowledge-graph",
                   tags=["knowledge-graph"])
_ERRORS = {"not_found": 404, "conflict": 409, "invalid": 422}


class ClaimDecisionRequest(BaseModel):
    decision: Literal[DECISIONS]
    reason: str = Field(min_length=3, max_length=2000)
    corrected_value: str | None = Field(default=None, max_length=120)
    corrected_unit: str | None = Field(default=None, max_length=20)
    supersede_claim_ids: list[str] = Field(default_factory=list, max_length=20)


class BatchClaimDecisionItem(ClaimDecisionRequest):
    claim_id: str = Field(min_length=1, max_length=128)


class BatchClaimDecisionRequest(BaseModel):
    items: list[BatchClaimDecisionItem] = Field(min_length=1, max_length=50)


class QuestionResolutionRequest(BaseModel):
    status: Literal["resolved", "dismissed"]
    resolution: str = Field(min_length=3, max_length=2000)


def _graph(request: Request, project_id: str, actor):
    with request.app.state.services.store.transaction() as db:
        owned_project(db, project_id, actor)
    graph = getattr(request.app.state.services, "knowledge_graph", None)
    if graph is None:
        raise HTTPException(503, "Knowledge graph is not configured")
    return graph


def _review_error(exc: ReviewError):
    detail = {"message": exc.message, **exc.details} if exc.details else exc.message
    return HTTPException(_ERRORS.get(exc.code, 422), detail)


@router.get("/summary")
def graph_summary(project_id: str, request: Request, actor=Depends(require("files:read"))):
    return _graph(request, project_id, actor).summary(project_id)


@router.get("/claims")
def list_claims(project_id: str, request: Request,
                status: Literal[STATUSES] | None = None,
                upload_id: str | None = Query(default=None, max_length=36),
                kind: Literal["entity", "attribute", "relation"] | None = None,
                entity_type: str | None = Query(default=None, max_length=40),
                attribute: str | None = Query(default=None, max_length=60),
                limit: int = Query(default=50, ge=1, le=200),
                skip: int = Query(default=0, ge=0, le=100_000),
                actor=Depends(require("files:read"))):
    if entity_type is not None and entity_type not in ENTITY_TYPES:
        raise HTTPException(422, "Unknown entity type")
    if attribute is not None and attribute not in ATTRIBUTES:
        raise HTTPException(422, "Unknown attribute")
    return _graph(request, project_id, actor).list_claims(
        project_id, status=status, upload_id=upload_id, kind=kind, entity_type=entity_type,
        attribute=attribute, limit=limit, skip=skip)


@router.get("/claims/{claim_id}")
def claim_detail(project_id: str, claim_id: str, request: Request,
                 actor=Depends(require("files:read"))):
    claim = _graph(request, project_id, actor).get_claim(project_id, claim_id)
    if claim is None:
        raise HTTPException(404, "Claim not found")
    return claim


@router.post("/claims/{claim_id}/decision")
def decide_claim(project_id: str, claim_id: str, payload: ClaimDecisionRequest,
                 request: Request, actor=Depends(require("designs:write"))):
    review = KnowledgeReview(_graph(request, project_id, actor))
    try:
        return review.decide(project_id, claim_id, actor.user_id, payload.decision,
                             payload.reason, payload.corrected_value, payload.corrected_unit,
                             payload.supersede_claim_ids)
    except ReviewError as exc:
        raise _review_error(exc) from exc


@router.post("/claims/decisions")
def decide_claims(project_id: str, payload: BatchClaimDecisionRequest,
                  request: Request, actor=Depends(require("designs:write"))):
    """Registra varias confirmaciones en un solo viaje desde la UX.

    Cada elemento conserva su resultado: un conflicto de una afirmación no oculta los
    éxitos de las demás ni obliga a repetirlas individualmente.
    """
    review = KnowledgeReview(_graph(request, project_id, actor))
    results, errors = [], []
    for item in payload.items:
        try:
            results.append(review.decide(
                project_id, item.claim_id, actor.user_id, item.decision, item.reason,
                item.corrected_value, item.corrected_unit, item.supersede_claim_ids))
        except ReviewError as exc:
            errors.append({"claim_id": item.claim_id, "status": _ERRORS.get(exc.code, 422),
                           "detail": {"message": exc.message, **exc.details} if exc.details
                           else exc.message})
    return {"accepted": results, "errors": errors, "total": len(payload.items),
            "succeeded": len(results), "failed": len(errors)}


@router.get("/questions")
def list_questions(project_id: str, request: Request,
                   status: Literal["pending", "resolved", "dismissed", "obsolete", "all"] =
                   "pending",
                   limit: int = Query(default=50, ge=1, le=200),
                   skip: int = Query(default=0, ge=0, le=100_000),
                   actor=Depends(require("files:read"))):
    return _graph(request, project_id, actor).list_questions(
        project_id, None if status == "all" else status, limit=limit, skip=skip)


@router.post("/questions/{question_key}/resolution")
def resolve_question(project_id: str, question_key: str, payload: QuestionResolutionRequest,
                     request: Request, actor=Depends(require("designs:write"))):
    review = KnowledgeReview(_graph(request, project_id, actor))
    try:
        return review.resolve_question(project_id, question_key, actor.user_id, payload.status,
                                       payload.resolution)
    except ReviewError as exc:
        raise _review_error(exc) from exc


@router.get("/entities")
def entity_map(project_id: str, request: Request,
               limit: int = Query(default=300, ge=1, le=1000),
               actor=Depends(require("files:read"))):
    return _graph(request, project_id, actor).entity_map(project_id, limit=limit)


@router.get("/runs")
def extraction_runs(project_id: str, request: Request,
                    upload_id: str | None = Query(default=None, max_length=36),
                    limit: int = Query(default=50, ge=1, le=200),
                    actor=Depends(require("files:read"))):
    runs = _graph(request, project_id, actor).list_runs(project_id, upload_id, limit)
    return {"items": runs}


@router.get("/documents/{upload_id}/source")
def document_source(project_id: str, upload_id: str, request: Request,
                    actor=Depends(require("files:read"))):
    """URL temporal del documento original para abrir la evidencia en su localizador."""
    with request.app.state.services.store.transaction() as db:
        owned_project(db, project_id, actor)
        upload = db.one("file_uploads", id=upload_id, project_id=project_id)
    if not upload or upload["status"] != "available":
        raise HTTPException(404, "Document not found")
    from src.infrastructure.entrypoint.api.file_routes import storage_client

    url = storage_client().presign_download(upload["target_bucket"], upload["object_key"])
    return {"upload_id": upload_id, "filename": upload["filename"],
            "mime_type": upload["expected_mime"], "url": url, "expires_in": 300}


@router.post("/documents/{upload_id}/reprocess", status_code=202)
def reprocess_document(project_id: str, upload_id: str, request: Request,
                       actor=Depends(require("designs:write"))):
    """Encola una nueva extracción; es idempotente si no cambió parser, prompts ni modelo."""
    _graph(request, project_id, actor)
    with request.app.state.services.store.transaction() as db:
        upload = db.one("file_uploads", id=upload_id, project_id=project_id)
    if not upload or upload["status"] != "available":
        raise HTTPException(404, "Document not found")
    from src.infrastructure.entrypoint.worker.tasks import reprocess_document as task

    try:
        task.delay(upload_id)
    except Exception as exc:
        raise HTTPException(503, "Unable to queue document reprocessing") from exc
    return {"upload_id": upload_id, "status": "queued"}
