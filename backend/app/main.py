"""
Ghumi backend entrypoint.
Per Ghumi_TechStack.docx: FastAPI (async), LangGraph orchestration underneath.
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.api.trip import router as trip_router
from app.core.config import get_settings
from app.core.rate_limit import limiter

settings = get_settings()

if "*" in settings.cors_origins:
    raise RuntimeError(
        "CORS_ORIGINS cannot include '*' while allow_credentials=True — "
        "this combination lets any origin read credentialed responses."
    )

app = FastAPI(
    title="Ghumi API",
    version="0.1.0",
    description="Multi-agent travel planning backend (LangGraph orchestration).",
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(trip_router, prefix="/api")


@app.get("/health")
def health():
    """Basic liveness check — confirms the app boots and env is loaded."""
    return {"status": "ok", "env": settings.environment}