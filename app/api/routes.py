from __future__ import annotations

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.agents.graph import LearningAgentGraph
from app.db.database import init_db
from app.db.repository import LearningRepository
from app.models import KnowledgeSearchRequest, LearningRequest, LearningResponse
from app.parsers.document_parser import ParseError, parse_document
from app.rag.db_store import DatabaseKnowledgeStore
from app.storage.minio_store import MinioStorage

router = APIRouter()
store = DatabaseKnowledgeStore()
storage = MinioStorage()
agent_graph = LearningAgentGraph(store=store)


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/db/init")
def initialize_database() -> dict[str, str]:
    init_db()
    return {"status": "ok", "message": "数据库表结构和 pgvector 扩展已初始化"}


@router.post("/learn", response_model=LearningResponse)
def learn(payload: LearningRequest) -> dict:
    return agent_graph.invoke(
        student_id=payload.student_id,
        course=payload.course,
        message=payload.message,
    )


@router.post("/knowledge/upload")
async def upload_knowledge(
    file: UploadFile = File(...),
    course: str = Form(default="机器学习"),
) -> dict:
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="文件内容为空")

    storage_info = storage.upload_course_file(
        filename=file.filename or "uploaded-file",
        data=raw,
        content_type=file.content_type,
        course=course,
    )

    file_id = store.add_file_record(
        course=course,
        filename=file.filename or "uploaded-file",
        file_type=file.content_type,
        file_size=len(raw),
        storage=storage_info,
        parse_status="uploaded",
    )

    try:
        text = parse_document(file.filename or "uploaded-file", raw)
    except ParseError as exc:
        store.update_file_status(
            file_id=file_id,
            parse_status="parse_failed",
            parse_error=str(exc),
        )
        return {
            "filename": file.filename,
            "chunks": 0,
            "parse_status": "parse_failed",
            "message": f"文件已上传到 MinIO，文件元数据已写入 PostgreSQL，但解析失败：{exc}",
            "storage": storage_info,
            "file_id": file_id,
        }

    if not text.strip():
        store.update_file_status(file_id=file_id, parse_status="parse_failed", parse_error="文件内容为空")
        raise HTTPException(status_code=400, detail="文件内容为空")

    added = store.add_text(
        filename=file.filename or "uploaded.txt",
        text=text,
        course=course,
        file_id=file_id,
    )
    store.update_file_status(file_id=file_id, parse_status="parsed")
    return {
        "filename": file.filename,
        "chunks": len(added),
        "parse_status": "parsed",
        "message": "文件已上传到 MinIO，元数据和知识切片已写入 PostgreSQL/pgvector。",
        "storage": storage_info,
        "file_id": file_id,
    }


@router.post("/knowledge/files/{file_id}/parse")
def parse_existing_file(file_id: int, course: str = "机器学习") -> dict:
    file_record = store.get_file(file_id)
    if not file_record:
        raise HTTPException(status_code=404, detail="文件记录不存在")
    if not file_record.get("object_name"):
        raise HTTPException(status_code=400, detail="文件记录缺少 MinIO object_name")

    raw = storage.read_object(
        object_name=file_record["object_name"],
        bucket=file_record.get("bucket_name"),
    )
    try:
        text = parse_document(file_record["filename"], raw)
    except ParseError as exc:
        store.update_file_status(file_id=file_id, parse_status="parse_failed", parse_error=str(exc))
        return {
            "file_id": file_id,
            "filename": file_record["filename"],
            "chunks": 0,
            "parse_status": "parse_failed",
            "message": f"解析失败：{exc}",
        }

    added = store.add_text(
        filename=file_record["filename"],
        text=text,
        course=course,
        file_id=file_id,
    )
    store.update_file_status(file_id=file_id, parse_status="parsed")
    return {
        "file_id": file_id,
        "filename": file_record["filename"],
        "chunks": len(added),
        "parse_status": "parsed",
        "message": "已有文件已从 MinIO 读取并解析入 PostgreSQL/pgvector。",
    }


@router.get("/knowledge")
def list_knowledge() -> dict:
    return {"items": store.list_items()}


@router.post("/knowledge/search")
def search_knowledge(payload: KnowledgeSearchRequest) -> dict:
    return {"items": store.search(payload.query, payload.top_k)}


@router.post("/knowledge/seed")
def seed_knowledge() -> dict:
    before = len(store.list_items())
    store.seed_demo_content()
    after = len(store.list_items())
    return {"added": after - before, "total": after}


@router.get("/dashboard/summary")
def dashboard_summary() -> dict:
    repo = LearningRepository()
    try:
        return repo.dashboard_summary()
    finally:
        repo.close()


@router.get("/dashboard/files")
def dashboard_files(limit: int = 50) -> dict:
    repo = LearningRepository()
    try:
        return {"items": repo.dashboard_files(limit=limit)}
    finally:
        repo.close()


@router.get("/dashboard/profiles")
def dashboard_profiles(limit: int = 50) -> dict:
    repo = LearningRepository()
    try:
        return {"items": repo.dashboard_profiles(limit=limit)}
    finally:
        repo.close()


@router.get("/dashboard/resources")
def dashboard_resources(limit: int = 50) -> dict:
    repo = LearningRepository()
    try:
        return {"items": repo.dashboard_resources(limit=limit)}
    finally:
        repo.close()


@router.get("/dashboard/paths")
def dashboard_paths(limit: int = 50) -> dict:
    repo = LearningRepository()
    try:
        return {"items": repo.dashboard_paths(limit=limit)}
    finally:
        repo.close()


@router.get("/dashboard/events")
def dashboard_events(limit: int = 80) -> dict:
    repo = LearningRepository()
    try:
        return {"items": repo.dashboard_events(limit=limit)}
    finally:
        repo.close()
