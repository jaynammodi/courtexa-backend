from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from app.routes import cases, meta
from app.config import settings

app = FastAPI(title="eCourts Scraper API", version="2.0")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routes
app.include_router(cases.router)
app.include_router(meta.router, prefix="/meta", tags=["meta"])

# Static files (Frontend)
app.mount("/", StaticFiles(directory="static", html=True), name="static")

@app.get("/health")
def health_check():
    return {"status": "ok", "redis": settings.REDIS_URL}