import asyncio
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse

from backend.api.router import api_router
from backend.config import settings
from backend.schemas.common import HealthResponse
from backend.services.time import utc_now
from backend.services.notifications import NotificationWorker


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings.validate_runtime()
    worker = NotificationWorker() if settings.notification_worker_enabled else None
    worker_task = asyncio.create_task(worker.run()) if worker else None
    try:
        yield
    finally:
        if worker and worker_task:
            worker.stop()
            try:
                await asyncio.wait_for(worker_task, timeout=20)
            except TimeoutError:
                worker_task.cancel()
                with suppress(asyncio.CancelledError):
                    await worker_task

app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    description="Personal life management API: plans, habits, goals, insights and contextual AI assistance.",
    contact={"name": "Axel One"},
    lifespan=lifespan,
    openapi_tags=[
        {"name": "Authentication", "description": "Registration, JWT sessions and user profile"},
        {"name": "Calendar", "description": "Events, recurrence metadata and reminders"},
        {"name": "Tasks & reminders", "description": "Prioritized work and completion tracking"},
        {"name": "Goals", "description": "Goals and AI-assisted decomposition"},
        {"name": "Habits", "description": "Habit check-ins and streak calculation"},
        {"name": "Insights & AI", "description": "Balance, analytics, recommendations and overload warnings"},
        {"name": "AI chat", "description": "Persistent context-aware streaming chat"},
    ],
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.trusted_host_list)
app.include_router(api_router)


@app.middleware("http")
async def production_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    if settings.is_production:
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    return response


@app.exception_handler(RequestValidationError)
async def validation_error(_: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content=jsonable_encoder({"detail": "Validation failed", "errors": exc.errors()}),
    )


@app.get("/health", response_model=HealthResponse, tags=["System"])
def health():
    return {"status": "ok", "service": "axel-one-api", "timestamp": utc_now()}
