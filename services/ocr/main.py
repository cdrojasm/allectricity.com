import base64
import io
import os

import pytesseract
from fastapi import FastAPI, HTTPException
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, Field

app = FastAPI(title="SPAT OCR service", version="1.0.0")
MAX_IMAGE_BYTES = 20 * 1024 * 1024
MIN_MEAN_CONFIDENCE = float(os.getenv("OCR_MIN_MEAN_CONFIDENCE", "60"))
MAX_LOW_CONFIDENCE_RATIO = float(os.getenv("OCR_MAX_LOW_CONFIDENCE_RATIO", "0.20"))
LOW_WORD_CONFIDENCE = float(os.getenv("OCR_LOW_WORD_CONFIDENCE", "45"))


class OCRRequest(BaseModel):
    image_base64: str = Field(min_length=1)
    language: str = Field(default="eng+spa", pattern="^(eng|spa|eng\\+spa)$")


@app.get("/health")
def health():
    return {"status": "ok", "engine": "tesseract"}


@app.post("/v1/ocr")
def recognize(payload: OCRRequest):
    try:
        data = base64.b64decode(payload.image_base64, validate=True)
    except (ValueError, base64.binascii.Error) as exc:
        raise HTTPException(400, "Invalid base64 image") from exc
    if len(data) > MAX_IMAGE_BYTES:
        raise HTTPException(413, "Image exceeds 20 MiB")
    try:
        image = Image.open(io.BytesIO(data))
        image.verify()
        image = Image.open(io.BytesIO(data)).convert("RGB")
    except (UnidentifiedImageError, OSError) as exc:
        raise HTTPException(415, "Unsupported or invalid image") from exc
    result = pytesseract.image_to_data(
        image, lang=payload.language, output_type=pytesseract.Output.DICT
    )
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
            lines.setdefault(line_key, []).append(text)

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
    return {
        "text": "\n".join(" ".join(tokens) for tokens in lines.values()),
        "mean_confidence": round(mean_confidence, 2),
        "low_confidence_ratio": round(low_confidence_ratio, 3),
        "word_count": len(words),
        "needs_review": needs_review,
    }
