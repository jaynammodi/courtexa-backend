from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import time

from app.core.config import settings
from app.api.routes import auth, users, workspaces, appointments, availability, cases, scraper

from app.db.session import SessionLocal
from app.models.workspace_refresh_job import WorkspaceRefreshJob
from datetime import datetime

app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json"
)

@app.middleware("http")
def add_delay(request, call_next):
    time.sleep(0)
    return call_next(request)

# Set all CORS enabled origins
if settings.API_V1_STR:
    app.add_middleware(
        CORSMiddleware,
        # allow_origins=["*"],
        allow_origins=[
            "http://localhost:3000",
            "http://127.0.0.1:3000",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

app.include_router(auth.router, prefix=f"{settings.API_V1_STR}/auth", tags=["auth"])
app.include_router(users.router, prefix=f"{settings.API_V1_STR}/users", tags=["users"])
app.include_router(workspaces.router, prefix=f"{settings.API_V1_STR}/workspaces", tags=["workspaces"])
app.include_router(appointments.router, prefix=f"{settings.API_V1_STR}/appointments", tags=["appointments"])
app.include_router(availability.router, prefix=f"{settings.API_V1_STR}/availability", tags=["availability"])
app.include_router(cases.router, prefix=f"{settings.API_V1_STR}/cases", tags=["cases"])
app.include_router(scraper.router, prefix=f"{settings.API_V1_STR}/scraper", tags=["scraper"])

@app.get("/health")
def health_check():
    return {"status": "ok"}

@app.on_event("startup")
def cleanup_refresh_jobs_on_startup():
    db = SessionLocal()
    try:
        running_jobs = db.query(WorkspaceRefreshJob).filter(
            WorkspaceRefreshJob.status == "running"
        ).all()

        for job in running_jobs:
            remaining = job.total_cases - (job.completed_cases + job.failed_cases)

            job.status = "aborted"
            job.failed_cases += max(0, remaining)
            job.finished_at = datetime.utcnow()

        db.commit()
        print(f"[startup] Marked {len(running_jobs)} stale refresh jobs as aborted")

    except Exception as e:
        db.rollback()
        print("[startup] cleanup failed:", e)

    finally:
        db.close()

@app.on_event("shutdown")
def cleanup_refresh_jobs_on_shutdown():
    db = SessionLocal()
    try:
        running_jobs = db.query(WorkspaceRefreshJob).filter(
            WorkspaceRefreshJob.status == "running"
        ).all()

        for job in running_jobs:
            remaining = job.total_cases - (job.completed_cases + job.failed_cases)

            job.status = "aborted"
            job.failed_cases += max(0, remaining)
            job.finished_at = datetime.utcnow()

        db.commit()
        print(f"[shutdown] Marked {len(running_jobs)} refresh jobs as aborted")

    except Exception as e:
        db.rollback()
        print("[shutdown] cleanup failed:", e)

    finally:
        db.close()