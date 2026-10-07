import hmac
import base64
import importlib
import io
import os
import threading
import time
from typing import Protocol

import pytesseract
from fastapi import FastAPI, Header, HTTPException, Request, Response
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, Field

app = FastAPI(title="SPAT OCR service", version="1.1.0")
MAX_IMAGE_BYTES = int(os.getenv("OCR_MAX_IMAGE_BYTES", str(20 * 1024 * 1024)))
MAX_REQUEST_BYTES = ((MAX_IMAGE_BYTES + 2) // 3) * 4 + 64 * 1024
INTERNAL_API_TOKEN = os.getenv("OCR_INTERNAL_API_TOKEN", "")
MIN_MEAN_CONFIDENCE = float(os.getenv("OCR_MIN_MEAN_CONFIDENCE", "60"))
MAX_LOW_CONFIDENCE_RATIO = float(os.getenv("OCR_MAX_LOW_CONFIDENCE_RATIO", "0.20"))
LOW_WORD_CONFIDENCE = float(os.getenv("OCR_LOW_WORD_CONFIDENCE", "45"))


class OCRRequest(BaseModel):
    image_base64: str = Field(min_length=1)
    language: str = Field(default="eng+spa", pattern="^(eng|spa|eng\\+spa)$")


class OCRProvider(Protocol):
    """Provider contract; managed OCR adapters can replace Tesseract here."""

    def recognize(self, image: Image.Image, language: str) -> dict: ...


class TesseractProvider:
    def recognize(self, image: Image.Image, language: str) -> dict:
        return pytesseract.image_to_data(image, lang=language, output_type=pytesseract.Output.DICT)


def load_provider() -> OCRProvider:
    target = os.getenv("OCR_PROVIDER", "tesseract")
    if target == "tesseract":
        return TesseractProvider()
    module_name, separator, class_name = target.partition(":")
    if not separator or not module_name or not class_name:
        raise RuntimeError("OCR_PROVIDER must be 'tesseract' or 'python.module:ProviderClass'")
    adapter = getattr(importlib.import_module(module_name), class_name)
    return adapter()


provider: OCRProvider = load_provider()
metrics_lock = threading.Lock()
metrics = {"requests": 0, "successes": 0, "errors": 0, "duration_seconds": 0.0}


@app.get("/health")
def health():
    return {"status": "ok", "engine": type(provider).__name__}


@app.middleware("http")
async def limit_request_size(request: Request, call_next):
    length = request.headers.get("content-length")
    if length:
        try:
            if int(length) > MAX_REQUEST_BYTES:
                return Response("Request exceeds configured size limit", status_code=413)
        except ValueError:
            return Response("Invalid Content-Length", status_code=400)
    if request.url.path != "/v1/ocr" or request.method != "POST":
        return await call_next(request)
    started = time.monotonic()
    with metrics_lock:
        metrics["requests"] += 1
    response = await call_next(request)
    with metrics_lock:
        metrics["successes" if response.status_code < 400 else "errors"] += 1
        metrics["duration_seconds"] += time.monotonic() - started
    return response


@app.get("/metrics", include_in_schema=False)
def get_metrics():
    with metrics_lock:
        snapshot = dict(metrics)
    body = (
        "# HELP spat_ocr_requests_total Total OCR requests\n# TYPE spat_ocr_requests_total counter\n"
        f"spat_ocr_requests_total {snapshot['requests']}\n"
        "# HELP spat_ocr_successes_total Successful OCR requests\n# TYPE spat_ocr_successes_total counter\n"
        f"spat_ocr_successes_total {snapshot['successes']}\n"
        "# HELP spat_ocr_errors_total Failed OCR requests\n# TYPE spat_ocr_errors_total counter\n"
        f"spat_ocr_errors_total {snapshot['errors']}\n"
        "# HELP spat_ocr_processing_seconds_total Total OCR processing time\n# TYPE spat_ocr_processing_seconds_total counter\n"
        f"spat_ocr_processing_seconds_total {snapshot['duration_seconds']:.6f}\n"
    )
    return Response(body, media_type="text/plain; version=0.0.4")


def _line_summary(key, line):
    summary = {"text": " ".join(line["tokens"]), "page": key[0],
               "confidence": round(sum(line["confidences"]) / len(line["confidences"]), 2)}
    if line["boxes"]:
        left = min(box[0] for box in line["boxes"])
        top = min(box[1] for box in line["boxes"])
        right = max(box[0] + box[2] for box in line["boxes"])
        bottom = max(box[1] + box[3] for box in line["boxes"])
        summary["bbox"] = [left, top, right - left, bottom - top]
    return summary


@app.post("/v1/ocr")
def recognize(payload: OCRRequest, authorization: str | None = Header(default=None)):
    if not INTERNAL_API_TOKEN:
        raise HTTPException(503, "OCR internal authentication is not configured")
    supplied = authorization.removeprefix("Bearer ") if authorization else ""
    if not authorization or not authorization.startswith("Bearer ") or not hmac.compare_digest(supplied, INTERNAL_API_TOKEN):
        raise HTTPException(401, "Invalid OCR service credentials", headers={"WWW-Authenticate": "Bearer"})
    try:
        data = base64.b64decode(payload.image_base64, validate=True)
    except (ValueError, base64.binascii.Error) as exc:
        raise HTTPException(400, "Invalid base64 image") from exc
    if len(data) > MAX_IMAGE_BYTES:
        raise HTTPException(413, "Image exceeds configured size limit")
    try:
        image = Image.open(io.BytesIO(data))
        image.verify()
        image = Image.open(io.BytesIO(data)).convert("RGB")
    except (UnidentifiedImageError, OSError) as exc:
        raise HTTPException(415, "Unsupported or invalid image") from exc
    try:
        result = provider.recognize(image, payload.language)
    except Exception as exc:
        raise HTTPException(502, "OCR provider failed") from exc
    words = []
    lines = {}
    for index, (raw_text, raw_confidence) in enumerate(zip(result["text"], result["conf"])):
        text = raw_text.strip()
        try:
            confidence = float(raw_confidence)
        except (TypeError, ValueError):
            continue
        if text and confidence >= 0:
            words.append({"text": text, "confidence": confidence})
            line_key = (
                result["page_num"][index],
                result["block_num"][index],
                result["par_num"][index],
                result["line_num"][index],
            )
            line = lines.setdefault(line_key, {"tokens": [], "confidences": [], "boxes": []})
            line["tokens"].append(text)
            line["confidences"].append(confidence)
            if all(key in result for key in ("left", "top", "width", "height")):
                line["boxes"].append(tuple(int(result[key][index])
                                           for key in ("left", "top", "width", "height")))

    mean_confidence = (
        sum(word["confidence"] for word in words) / len(words) if words else 0.0
    )
    low_confidence_ratio = (
        sum(word["confidence"] < LOW_WORD_CONFIDENCE for word in words) / len(words)
        if words
        else 1.0
    )
    needs_review = (
        not words
        or mean_confidence < MIN_MEAN_CONFIDENCE
        or low_confidence_ratio > MAX_LOW_CONFIDENCE_RATIO
    )
    response = {
        "text": "\n".join(" ".join(line["tokens"]) for line in lines.values()),
        # Per-line text, confidence and pixel region let callers cite the exact passage.
        "lines": [_line_summary(key, line) for key, line in lines.items()],
        "mean_confidence": round(mean_confidence, 2),
        "low_confidence_ratio": round(low_confidence_ratio, 3),
        "word_count": len(words),
        "needs_review": needs_review,
    }
    return response
