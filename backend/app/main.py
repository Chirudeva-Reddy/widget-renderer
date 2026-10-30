import json
from typing import Literal, TypedDict

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.validator import InvalidSource, ValidationResult, unique_object, validate_source

app: FastAPI = FastAPI()


class HealthResponse(TypedDict):
    status: Literal["ok"]


@app.get("/api/health")
async def health() -> HealthResponse:
    return {"status": "ok"}


def error_response(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"code": code, "message": message})


@app.post("/api/payloads/validate")
async def validate_payload(request: Request) -> JSONResponse:
    content_type: str = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type != "application/json":
        return error_response(415, "unsupported_media_type", "Content type must be application/json.")
    body: bytearray = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > 262144:
            return error_response(413, "body_limit", "Request body exceeds the size limit.")
        body.extend(chunk)
    try:
        envelope: object = json.loads(body, object_pairs_hook=unique_object)
    except (json.JSONDecodeError, UnicodeDecodeError, InvalidSource, RecursionError):
        return error_response(422, "invalid_envelope", "Request must contain a valid JSON object.")
    if not isinstance(envelope, dict) or set(envelope) != {"source"} or not isinstance(envelope["source"], str):
        return error_response(422, "invalid_envelope", "Request must contain only a string source field.")
    source: str = envelope["source"]
    try:
        source.encode("utf-8")
    except UnicodeEncodeError:
        return error_response(422, "invalid_unicode", "Source contains invalid Unicode.")
    try:
        result: ValidationResult = validate_source(source)
    except UnicodeEncodeError:
        return error_response(422, "invalid_unicode", "Source contains invalid Unicode.")
    return JSONResponse(content=result)
