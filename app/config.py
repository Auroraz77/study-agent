import os
from pathlib import Path

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

DATA_DIR = BASE_DIR / "data"
KNOWLEDGE_DIR = DATA_DIR / "knowledge"
INDEX_FILE = DATA_DIR / "rag_index.json"

QWEN_BASE_URL = os.getenv(
    "QWEN_BASE_URL",
    "https://dashscope.aliyuncs.com/compatible-mode/v1",
)
QWEN_API_KEY = os.getenv("DASHSCOPE_API_KEY") or os.getenv("QWEN_API_KEY")
QWEN_MODEL = os.getenv("QWEN_MODEL", "qwen-plus")
FORCE_MOCK_LLM = os.getenv("FORCE_MOCK_LLM", "0") == "1"

APP_HOST = os.getenv("APP_HOST", "127.0.0.1")
APP_PORT = int(os.getenv("APP_PORT", "8000"))

MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "127.0.0.1:9000")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "")
MINIO_BUCKET = os.getenv("MINIO_BUCKET", "learning-bucket")
MINIO_SECURE = os.getenv("MINIO_SECURE", "0") == "1"

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg://postgres:postgres@127.0.0.1:5432/learning_agent",
)
EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", "128"))
USE_DATABASE = os.getenv("USE_DATABASE", "1") == "1"


def ensure_dirs() -> None:
    DATA_DIR.mkdir(exist_ok=True)
    KNOWLEDGE_DIR.mkdir(exist_ok=True)
