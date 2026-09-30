from fastapi import APIRouter

from app.api.routes import (
    adjustments,
    ai,
    auth,
    calendar,
    export,
    feedback,
    instances,
    photos,
    reminders,
    semesters,
    templates,
    textbooks,
)

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(semesters.router)
api_router.include_router(calendar.router)
api_router.include_router(templates.router)
api_router.include_router(instances.router)
api_router.include_router(ai.router)
api_router.include_router(adjustments.router)
api_router.include_router(feedback.router)
api_router.include_router(export.router)
api_router.include_router(textbooks.router)
api_router.include_router(photos.router)
api_router.include_router(reminders.router)
