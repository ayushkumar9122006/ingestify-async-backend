from fastapi import APIRouter
from app.api.v1.endpoints import jobs, analytics, auth

api_router = APIRouter()

api_router.include_router(jobs.router)
api_router.include_router(analytics.router)
api_router.include_router(auth.router)
