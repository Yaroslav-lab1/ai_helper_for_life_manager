from fastapi import APIRouter

from backend.api import account, ai, auth, events, goals, habits, insights, notifications, settings, tasks

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(account.router)
api_router.include_router(events.router)
api_router.include_router(tasks.router)
api_router.include_router(goals.router)
api_router.include_router(habits.router)
api_router.include_router(insights.router)
api_router.include_router(settings.router)
api_router.include_router(ai.router)
api_router.include_router(notifications.router)
