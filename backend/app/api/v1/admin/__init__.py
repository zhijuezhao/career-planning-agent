from fastapi import APIRouter

from app.api.v1.admin import auth as admin_auth
from app.api.v1.admin.chat import router as chat_router
from app.api.v1.admin.companies import router as companies_router
from app.api.v1.admin.dashboard import router as dashboard_router
from app.api.v1.admin.import_module import router as import_router
from app.api.v1.admin.jobs import router as jobs_router
from app.api.v1.admin.matching import router as matching_router
from app.api.v1.admin.raw_data import router as raw_data_router
from app.api.v1.admin.reports import router as reports_router
from app.api.v1.admin.system import router as system_router
from app.api.v1.admin.users import router as users_router

router = APIRouter()
router.include_router(admin_auth.router, prefix="/auth", tags=["admin-auth"])
router.include_router(chat_router, prefix="/chat", tags=["admin-chat"])
router.include_router(companies_router, prefix="/companies", tags=["admin-companies"])
router.include_router(dashboard_router, prefix="/dashboard", tags=["admin-dashboard"])
router.include_router(import_router, prefix="/import", tags=["admin-import"])
router.include_router(jobs_router, prefix="/jobs", tags=["admin-jobs"])
router.include_router(matching_router, prefix="/matching", tags=["admin-matching"])
router.include_router(raw_data_router, prefix="/raw-data", tags=["admin-raw-data"])
router.include_router(reports_router, prefix="/reports", tags=["admin-reports"])
router.include_router(system_router, prefix="/system", tags=["admin-system"])
router.include_router(users_router, prefix="/users", tags=["admin-users"])

__all__ = ["router", "admin_auth"]

