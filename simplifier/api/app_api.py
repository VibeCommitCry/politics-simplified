from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from ..core.pipeline import error_response, run
from .schemas import SimplifyRequest, SimplifyResponse

app = FastAPI()


@app.post("/simplify")
def simplify(request: SimplifyRequest) -> SimplifyResponse:
    return run(request)


@app.exception_handler(RequestValidationError)
def invalid_request(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Keep the contract: a bad body still gets a valid response with `error` filled."""
    case_id = str(exc.body.get("case_id", "")) if isinstance(exc.body, dict) else ""
    problems = [f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()]
    message = f"invalid request: {'; '.join(problems)}"
    response = error_response(case_id, message)
    return JSONResponse(status_code=422, content=response.model_dump(mode="json"))
