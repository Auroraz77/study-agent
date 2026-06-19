from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.routes import router
from app.config import BASE_DIR, ensure_dirs


ensure_dirs()

app = FastAPI(
    title="LangGraph 个性化学习多智能体系统",
    description="基于 FastAPI、LangGraph、通义千问和 RAG 的个性化学习系统 MVP",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api")

static_dir = Path(BASE_DIR) / "app" / "static"
app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")
