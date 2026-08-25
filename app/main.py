from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.core.config import get_settings
from app.core.limiter import limiter
from app.modules.auth.router import router as auth_router
from app.modules.case_attempts.router import faculty_router as case_attempts_faculty_router
from app.modules.case_attempts.router import learner_router as case_attempts_learner_router
from app.modules.case_categories.router import faculty_router as case_categories_faculty_router
from app.modules.case_categories.router import learner_router as case_categories_learner_router
from app.modules.case_categories.router import router as case_categories_router
from app.modules.cases.router import faculty_router as cases_faculty_router
from app.modules.cases.router import learner_router as cases_learner_router
from app.modules.cases.router import router as cases_router
from app.modules.course_certificates.router import faculty_router as course_certificates_faculty_router
from app.modules.course_certificates.router import learner_router as course_certificates_learner_router
from app.modules.course_lectures.router import faculty_router as course_lectures_faculty_router
from app.modules.course_lectures.router import learner_router as course_lectures_learner_router
from app.modules.course_progress.router import admin_router as course_progress_admin_router
from app.modules.course_progress.router import faculty_router as course_progress_faculty_router
from app.modules.course_progress.router import learner_router as course_progress_learner_router
from app.modules.course_resources.router import faculty_router as course_resources_faculty_router
from app.modules.course_resources.router import learner_router as course_resources_learner_router
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
app.include_router(case_attempts_faculty_router, prefix="/api/v1")
app.include_router(case_attempts_learner_router, prefix="/api/v1")
app.include_router(case_categories_router, prefix="/api/v1")
app.include_router(case_categories_faculty_router, prefix="/api/v1")
app.include_router(case_categories_learner_router, prefix="/api/v1")
app.include_router(cases_router, prefix="/api/v1")
app.include_router(cases_faculty_router, prefix="/api/v1")
app.include_router(cases_learner_router, prefix="/api/v1")
app.include_router(course_certificates_faculty_router, prefix="/api/v1")
app.include_router(course_certificates_learner_router, prefix="/api/v1")
app.include_router(course_lectures_faculty_router, prefix="/api/v1")
app.include_router(course_lectures_learner_router, prefix="/api/v1")
app.include_router(course_progress_admin_router, prefix="/api/v1")
app.include_router(course_progress_faculty_router, prefix="/api/v1")
app.include_router(course_progress_learner_router, prefix="/api/v1")
app.include_router(course_resources_faculty_router, prefix="/api/v1")
app.include_router(course_resources_learner_router, prefix="/api/v1")
app.include_router(courses_router, prefix="/api/v1")
app.include_router(faculty_applications_router, prefix="/api/v1")
app.include_router(registrations_router, prefix="/api/v1")
app.include_router(users_router, prefix="/api/v1")


@app.get("/health", tags=["health"])
async def health() -> dict[str, str]:
    return {"status": "ok"}
