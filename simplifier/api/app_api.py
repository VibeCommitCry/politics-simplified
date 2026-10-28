import os
import secrets
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from .. import REPO_ROOT
from ..core.pipeline import error_response, run
from .schemas import SimplifyRequest, SimplifyResponse

API_KEY_ENV = "SIMPLIFY_API_KEY"


class Unauthorized(Exception):
    """The `X-Api-Key` header is missing or wrong."""


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Refuse to start without the shared secret, so the service is never open by accident."""
    load_dotenv(REPO_ROOT / ".env")
    if not os.environ.get(API_KEY_ENV):
        raise RuntimeError(f"{API_KEY_ENV} is not set")
    yield


app = FastAPI(lifespan=lifespan)


def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    expected = os.environ.get(API_KEY_ENV, "")
    given = x_api_key or ""
    # Constant-time comparison; an empty expected key never matches.
    if not expected or not secrets.compare_digest(given.encode(), expected.encode()):
        raise Unauthorized


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


# Plain `def`, not `async def`: the pipeline blocks on HTTP calls, so FastAPI runs it in a thread.
@app.post("/simplify", dependencies=[Depends(require_api_key)])
def simplify(request: SimplifyRequest) -> SimplifyResponse:
    return run(request)


@app.exception_handler(Unauthorized)
def unauthorized(request: Request, exc: Unauthorized) -> JSONResponse:
    response = error_response("", "unauthorized: missing or invalid X-Api-Key")
    return JSONResponse(status_code=401, content=response.model_dump(mode="json"))


@app.exception_handler(RequestValidationError)
def invalid_request(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Keep the contract: a bad body still gets a valid response with `error` filled."""
    case_id = str(exc.body.get("case_id", "")) if isinstance(exc.body, dict) else ""
    problems = [f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()]
    message = f"invalid request: {'; '.join(problems)}"
    response = error_response(case_id, message)
    return JSONResponse(status_code=422, content=response.model_dump(mode="json"))
