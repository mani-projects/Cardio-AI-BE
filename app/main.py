from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.core.config import get_settings
from app.core.limiter import limiter
from app.modules.auth.router import router as auth_router
from app.modules.courses.router import router as courses_router
from app.modules.faculty_applications.router import router as faculty_applications_router
from app.modules.registrations.router import router as registrations_router
from app.modules.users.router import router as users_router

settings = get_settings()

app = FastAPI(title="CardioAI API", version="0.1.0")
app.state.limiter = limiter


async def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded) -> Response:
    # Same {"detail": ...} shape as every other error response in this app
    # (FastAPI's own HTTPException handling), with a Retry-After header —
    # matching the existing 429 convention already used for OTP/reset-token
    # cooldowns — rather than slowapi's default {"error": ...} plain response.
    response = JSONResponse({"detail": "Too many requests. Please try again later."}, status_code=429)
    return limiter._inject_headers(response, request.state.view_rate_limit)


app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router, prefix="/api/v1")
app.include_router(courses_router, prefix="/api/v1")
app.include_router(faculty_applications_router, prefix="/api/v1")
app.include_router(registrations_router, prefix="/api/v1")
app.include_router(users_router, prefix="/api/v1")


@app.get("/health", tags=["health"])
async def health() -> dict[str, str]:
    return {"status": "ok"}
