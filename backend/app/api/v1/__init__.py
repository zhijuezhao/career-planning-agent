from fastapi import APIRouter

from app.api.v1.admin import router as admin_router
from app.api.v1.auth import router as auth_router
from app.api.v1.career import router as career_router
from app.api.v1.chat import router as chat_router
from app.api.v1.jobs import router as jobs_router
from app.api.v1.journey import router as journey_router
from app.api.v1.matching import router as matching_router
from app.api.v1.profile import router as profile_router
from app.api.v1.reports import router as reports_router
from app.api.v1.resume import router as resume_router
from app.api.v1.users import router as users_router

router = APIRouter()
router.include_router(admin_router, prefix="/admin", tags=["admin"])
router.include_router(auth_router, prefix="/auth", tags=["auth"])
router.include_router(career_router, prefix="/career", tags=["career"])
router.include_router(chat_router, prefix="/chat", tags=["chat"])
router.include_router(journey_router, prefix="/journey", tags=["journey"])
router.include_router(jobs_router, prefix="/jobs", tags=["jobs"])
router.include_router(matching_router, prefix="/matching", tags=["matching"])
router.include_router(profile_router, prefix="", tags=["profile"])
router.include_router(reports_router, prefix="/reports", tags=["reports"])
router.include_router(resume_router, prefix="/resume", tags=["resume"])
router.include_router(users_router, prefix="/users", tags=["users"])
