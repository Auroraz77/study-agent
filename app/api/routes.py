from __future__ import annotations

import base64
import hashlib
from difflib import SequenceMatcher
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.exc import IntegrityError

from app.agents.graph import LearningAgentGraph, _build_quiz_items
from app.auth import create_access_token, get_current_user, hash_password, user_to_dict, verify_password
from app.db.database import init_db
from app.db.models import User
from app.export_ppt import build_learning_pptx, suggested_filename
from app.db.repository import LearningRepository
from app.models import (
    AskQuestionRequest,
    AskQuestionResponse,
    AuthResponse,
    KnowledgeSearchRequest,
    LearningRequest,
    LearningResponse,
    LoginRequest,
    QuizNextRequest,
    QuizSubmitRequest,
    RegisterRequest,
    ResourceAudioRequest,
    ResourceAudioResponse,
    TTSRequest,
    TTSResponse,
    UserResponse,
)
from app.parsers.document_parser import ParseError, parse_document
from app.llm.qwen import QwenClient
from app.llm.qwen_tts import QwenTTSClient
from app.rag.db_store import DatabaseKnowledgeStore
from app.storage.minio_store import MinioStorage

router = APIRouter()
store = DatabaseKnowledgeStore()
storage = MinioStorage()
qa_llm = QwenClient()
tts_client = QwenTTSClient()
agent_graph = LearningAgentGraph(store=store)


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/db/init")
def initialize_database() -> dict[str, str]:
    init_db()
    return {"status": "ok", "message": "数据库表结构和 pgvector 扩展已初始化"}


@router.post("/auth/register", response_model=AuthResponse)
def register(payload: RegisterRequest) -> dict:
    username = payload.username.strip()
    student_id = (payload.student_id or username).strip()
    if not username or not student_id:
        raise HTTPException(status_code=400, detail="用户名和学生 ID 不能为空")

    repo = LearningRepository()
    try:
        if repo.get_user_by_username(username):
            raise HTTPException(status_code=409, detail="用户名已存在")
        if repo.get_user_by_student_id(student_id):
            raise HTTPException(status_code=409, detail="学生 ID 已存在")
        try:
            user = repo.create_user(
                username=username,
                password_hash=hash_password(payload.password),
                student_id=student_id,
                role="student",
            )
        except IntegrityError as exc:
            repo.session.rollback()
            raise HTTPException(status_code=409, detail="用户名或学生 ID 已存在") from exc
        return {
            "access_token": create_access_token(user),
            "token_type": "bearer",
            "user": user_to_dict(user),
        }
    finally:
        repo.close()


@router.post("/auth/login", response_model=AuthResponse)
def login(payload: LoginRequest) -> dict:
    repo = LearningRepository()
    try:
        user = repo.get_user_by_username(payload.username.strip())
        if not user or not verify_password(payload.password, user.password_hash):
            raise HTTPException(status_code=401, detail="用户名或密码错误")
        return {
            "access_token": create_access_token(user),
            "token_type": "bearer",
            "user": user_to_dict(user),
        }
    finally:
        repo.close()


@router.get("/auth/me", response_model=UserResponse)
def me(current_user: User = Depends(get_current_user)) -> dict:
    return user_to_dict(current_user)


@router.post("/learn", response_model=LearningResponse)
def learn(payload: LearningRequest, current_user: User = Depends(get_current_user)) -> dict:
    return agent_graph.invoke(
        student_id=current_user.student_id,
        course=payload.course,
        message=payload.message,
    )


@router.post("/export/pptx")
def export_pptx(payload: dict, current_user: User = Depends(get_current_user)) -> StreamingResponse:
    resources = payload.get("resources")
    if not isinstance(resources, list) or not resources:
        raise HTTPException(status_code=400, detail="请先生成学习资源，再导出 PPT")

    pptx = build_learning_pptx(payload, student_name=current_user.username)
    filename = suggested_filename(payload.get("course"))
    quoted = quote(filename)
    headers = {
        "Content-Disposition": f"attachment; filename*=UTF-8''{quoted}",
    }
    return StreamingResponse(
        pptx,
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        headers=headers,
    )


@router.post("/qa/ask", response_model=AskQuestionResponse)
def ask_question(payload: AskQuestionRequest, current_user: User = Depends(get_current_user)) -> dict:
    question = payload.question.strip()
    course = payload.course.strip() or "机器学习"
    if not question:
        raise HTTPException(status_code=400, detail="问题不能为空")

    mode = payload.mode if payload.mode in {"rag", "llm"} else "rag"
    context = []
    if mode == "rag":
        context = store.search(
            " ".join([course, question, payload.learning_context or ""]),
            top_k=5,
            course=course,
        )
    answer = _answer_student_question(
        course=course,
        question=question,
        learning_context=payload.learning_context or "",
        context=context,
        mode=mode,
    )
    repo = LearningRepository()
    try:
        repo.save_learning_event(
            student_id=current_user.student_id,
            course_name=course,
            event_type="ask_question",
            event_data={
                "question": question,
                "answer": answer,
                "mode": mode,
                "context_count": len(context),
            },
        )
    finally:
        repo.close()

    return {
        "answer": answer,
        "retrieved_context": context,
        "course": course,
        "mode": mode,
    }


@router.post("/quiz/submit")
def submit_quiz(payload: QuizSubmitRequest, current_user: User = Depends(get_current_user)) -> dict:
    result = _grade_quiz(payload.quiz, payload.answers)
    repo = LearningRepository()
    try:
        repo.save_quiz_attempt(
            student_id=current_user.student_id,
            course_name=payload.course,
            result=result,
        )
    finally:
        repo.close()
    return result


@router.post("/quiz/next")
def next_quiz(payload: QuizNextRequest, current_user: User = Depends(get_current_user)) -> dict:
    return _next_quiz_payload(course=payload.course, level=payload.level)


@router.get("/quiz/next")
def next_quiz_get(
    course: str = Query(default="机器学习"),
    level: int = Query(default=2, ge=1, le=5),
    current_user: User = Depends(get_current_user),
) -> dict:
    return _next_quiz_payload(course=course, level=level)


@router.post("/tts/speech", response_model=TTSResponse)
def tts_speech(payload: TTSRequest, current_user: User = Depends(get_current_user)) -> dict:
    text = payload.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="语音播报内容不能为空")
    try:
        audio = tts_client.synthesize(text=text, voice=payload.voice)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {
        "audio_base64": audio.audio_base64,
        "content_type": audio.content_type,
        "model": audio.model,
        "voice": audio.voice,
    }


@router.post("/resources/{resource_id}/audio", response_model=ResourceAudioResponse)
def create_resource_audio(
    resource_id: int,
    payload: ResourceAudioRequest,
    current_user: User = Depends(get_current_user),
) -> dict:
    repo = LearningRepository()
    try:
        resource = repo.get_generated_resource(resource_id=resource_id, student_id=current_user.student_id)
        if not resource:
            raise HTTPException(status_code=404, detail="Learning resource not found")

        text = _tts_text_for_resource(resource.content)
        if not text:
            raise HTTPException(status_code=400, detail="Resource has no text for AI audio")

        voice = (payload.voice or tts_client.voice).strip() or tts_client.voice
        text_hash = _tts_text_hash(text)
        cached = repo.get_resource_audio(
            resource_id=resource_id,
            student_id=current_user.student_id,
            model=tts_client.model,
            voice=voice,
            text_hash=text_hash,
        )
        if cached and cached.object_name:
            return _resource_audio_payload(cached, cached=True)

        try:
            audio = tts_client.synthesize(text=text, voice=voice)
            audio_bytes = base64.b64decode(audio.audio_base64)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

        storage_info = storage.upload_resource_audio(
            resource_id=resource.id,
            student_id=current_user.student_id,
            course=resource.course.name if resource.course else str(resource.course_id),
            text_hash=text_hash,
            data=audio_bytes,
            content_type=audio.content_type,
            extension=_audio_extension(audio.content_type),
        )
        saved = repo.save_resource_audio(
            resource=resource,
            model=audio.model,
            voice=audio.voice,
            text_hash=text_hash,
            storage=storage_info,
            metadata={"text_length": len(text), "source": "qwen_tts"},
        )
        return _resource_audio_payload(saved, cached=False)
    finally:
        repo.close()


@router.get("/resources/{resource_id}/audio")
def stream_resource_audio(resource_id: int, current_user: User = Depends(get_current_user)) -> StreamingResponse:
    repo = LearningRepository()
    try:
        audio = repo.get_latest_resource_audio(resource_id=resource_id, student_id=current_user.student_id)
        if not audio or not audio.object_name:
            raise HTTPException(status_code=404, detail="AI audio has not been generated for this resource")
        object_name = audio.object_name
        bucket = audio.bucket_name
        content_type = audio.content_type or "audio/mpeg"
        file_size = audio.file_size
    finally:
        repo.close()

    headers = {
        "Accept-Ranges": "bytes",
        "Cache-Control": "public, max-age=86400",
    }
    if file_size:
        headers["Content-Length"] = str(file_size)
    return StreamingResponse(
        storage.iter_object(object_name=object_name, bucket=bucket),
        media_type=content_type,
        headers=headers,
    )


def _tts_text_for_resource(text: str) -> str:
    return " ".join(str(text or "").split())[:6000]


def _tts_text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _resource_audio_payload(audio, cached: bool) -> dict:
    return {
        "cached": cached,
        "resource_id": audio.resource_id,
        "audio_url": f"/api/resources/{audio.resource_id}/audio",
        "content_type": audio.content_type or "audio/mpeg",
        "model": audio.model,
        "voice": audio.voice,
        "storage_url": audio.storage_url,
        "created_at": audio.created_at.isoformat(sep=" ", timespec="seconds") if audio.created_at else None,
    }


def _audio_extension(content_type: str | None) -> str:
    mapping = {
        "audio/mpeg": "mp3",
        "audio/mp3": "mp3",
        "audio/wav": "wav",
        "audio/opus": "opus",
        "audio/aac": "aac",
        "audio/flac": "flac",
    }
    return mapping.get((content_type or "").split(";", 1)[0].lower(), "mp3")


def _next_quiz_payload(course: str, level: int) -> dict:
    safe_level = max(1, min(level, 5))
    return {
        "level": safe_level,
        "quiz": _build_quiz_items(profile={}, user_input=course, level=safe_level),
    }


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


@router.get("/knowledge/chunks/{chunk_id}")
def get_knowledge_chunk(chunk_id: int) -> dict:
    repo = LearningRepository()
    try:
        item = repo.get_chunk_detail(chunk_id)
        if not item:
            raise HTTPException(status_code=404, detail="资料片段不存在")
        return item
    finally:
        repo.close()


@router.get("/knowledge/files/{file_id}/preview")
def preview_knowledge_file(file_id: int, request: Request) -> StreamingResponse:
    repo = LearningRepository()
    try:
        file_record = repo.get_course_file(file_id)
        if not file_record:
            raise HTTPException(status_code=404, detail="文件记录不存在")
        if not file_record.object_name:
            raise HTTPException(status_code=400, detail="文件没有可预览的存储对象")
        is_pdf = (file_record.file_type or "").lower() == "application/pdf" or file_record.filename.lower().endswith(".pdf")
        if not is_pdf:
            raise HTTPException(status_code=400, detail="当前仅支持 PDF 原文预览")
        file_size = storage.object_size(file_record.object_name, file_record.bucket_name)
        quoted = quote(file_record.filename or "preview.pdf")
        headers = {
            "Content-Disposition": f"inline; filename*=UTF-8''{quoted}",
            "Accept-Ranges": "bytes",
            "Cache-Control": "public, max-age=3600",
        }
        range_header = request.headers.get("range")
        if range_header:
            start, end = _parse_range_header(range_header, file_size)
            length = end - start + 1
            headers.update(
                {
                    "Content-Range": f"bytes {start}-{end}/{file_size}",
                    "Content-Length": str(length),
                }
            )
            return StreamingResponse(
                storage.iter_object(
                    object_name=file_record.object_name,
                    bucket=file_record.bucket_name,
                    offset=start,
                    length=length,
                ),
                media_type="application/pdf",
                headers=headers,
                status_code=206,
            )

        headers["Content-Length"] = str(file_size)
        return StreamingResponse(
            storage.iter_object(
                object_name=file_record.object_name,
                bucket=file_record.bucket_name,
            ),
            media_type="application/pdf",
            headers=headers,
        )
    finally:
        repo.close()


def _parse_range_header(range_header: str, file_size: int) -> tuple[int, int]:
    if not range_header.startswith("bytes="):
        raise HTTPException(status_code=416, detail="不支持的 Range 请求")

    range_value = range_header.removeprefix("bytes=").split(",", 1)[0].strip()
    start_text, _, end_text = range_value.partition("-")
    if not start_text and not end_text:
        raise HTTPException(status_code=416, detail="无效的 Range 请求")

    try:
        if start_text:
            start = int(start_text)
            end = int(end_text) if end_text else file_size - 1
        else:
            suffix_length = int(end_text)
            start = max(file_size - suffix_length, 0)
            end = file_size - 1
    except ValueError as exc:
        raise HTTPException(status_code=416, detail="无效的 Range 请求") from exc

    if start < 0 or end < start or start >= file_size:
        raise HTTPException(status_code=416, detail="Range 超出文件范围")
    return start, min(end, file_size - 1)


def _answer_student_question(
    course: str,
    question: str,
    learning_context: str,
    context: list[dict],
    mode: str = "rag",
) -> str:
    context_text = _format_qa_context(context)
    if qa_llm.is_mock:
        return _fallback_qa_answer(course, question, context, mode=mode)

    if mode == "llm":
        system = (
            "你是学习问答智能体，面向正在学习课程的学生答疑。"
            "当前是直接问 AI 模式。你只能根据通用知识和用户问题本身回答。"
            "严禁使用、假设、评价或提及任何课程知识库、上传资料、资料片段、课件、教材、用户提供的资料。"
            "回答中不要出现“资料”“片段”“知识库”“上传”“课件”“教材”“你提供”等词。"
            "不要做资料覆盖性判断，直接回答问题。"
            "回答必须精简，控制在 3 个小段以内；每段不超过 3 句。"
            "优先使用短标题、短列表和加粗关键词；除非用户明确要求对比，否则不要输出表格。"
            "可以使用 Markdown。"
        )
        user = (
            f"问题：{question}\n\n"
            "请按整洁格式输出："
            "1. 用 1-2 句话直接回答；"
            "2. 用 2-3 个要点解释关键原因；"
            "3. 最后给 1 个很短的学习建议或小例子。"
        )
    else:
        system = (
            "你是学习问答智能体，面向正在学习课程的学生答疑。"
            "回答要准确、分层、简洁，优先结合课程资料片段；如果资料不足，要明确说明并给出合理推断。"
            "不要编造资料来源。"
            "回答必须精简，控制在 3 个小段以内；每段不超过 3 句。"
            "优先使用短标题、短列表和加粗关键词；除非用户明确要求对比，否则不要输出表格。"
            "资料不足时只用一句话说明，不要展开长篇背景。"
            "可以使用 Markdown。"
        )
        user = (
            f"课程：{course}\n"
            f"学生当前学习描述：{learning_context or '未提供'}\n"
            f"学生问题：{question}\n"
            f"课程资料片段：{context_text}\n\n"
            "请按整洁格式输出："
            "1. 用 1-2 句话直接回答；"
            "2. 用 2-3 个要点解释关键原因；"
            "3. 最后给 1 个很短的学习建议或小例子。"
        )
    answer = qa_llm.chat(system, user, temperature=0.35).strip()
    if not answer or answer == "这是基于学生画像和课程知识库生成的个性化学习内容。":
        return _fallback_qa_answer(course, question, context, mode=mode)
    if mode == "llm":
        answer = _clean_direct_ai_answer(answer)
    return answer


def _format_qa_context(context: list[dict]) -> str:
    if not context:
        return "暂无命中的课程资料片段。"
    return "\n".join(
        f"[{item.get('filename', 'unknown')}#{item.get('chunk_index', '-')}] {item.get('text', '')}"
        for item in context
    )


def _clean_direct_ai_answer(answer: str) -> str:
    forbidden = [
        "资料提示",
        "资料说明",
        "资料片段",
        "知识库",
        "上传资料",
        "你提供的",
        "课程资料",
        "课件",
        "教材",
        "片段",
    ]
    blocks = [block.strip() for block in answer.split("\n\n") if block.strip()]
    kept = [
        block
        for block in blocks
        if not any(term in block for term in forbidden)
    ]
    cleaned = "\n\n".join(kept).strip()
    return cleaned or answer


def _fallback_qa_answer(course: str, question: str, context: list[dict], mode: str = "rag") -> str:
    if mode == "llm":
        return (
            f"你问的是《{course}》中的：{question}\n\n"
            "可以先抓住三个层次：概念本身是什么、它解决什么问题、在真实课程或项目流程中怎么用。"
            "如果是技术概念，建议再补充一个最小例子，帮助你把定义和应用场景对应起来。"
        )
    if context:
        return (
            f"你问的是《{course}》中的：{question}\n\n"
            "可以先按“概念含义、在架构中的位置、典型应用场景”三步理解。"
            f"结合当前知识库，最相关的资料片段来自 {context[0].get('filename', '课程资料')}："
            f"{context[0].get('text', '')[:220]}...\n\n"
            "建议你把这个问题再对应到当前生成的讲解文档或代码实操案例中，重点看它解决了哪一类数据处理问题。"
        )
    return (
        f"你问的是《{course}》中的：{question}\n\n"
        "当前没有检索到课程资料片段，我先给出通用学习建议：先明确概念定义，再看它在完整流程中的位置，"
        "最后用一个小例子验证。你也可以上传课程资料后再提问，回答会更贴合教材内容。"
    )


@router.post("/knowledge/seed")
def seed_knowledge() -> dict:
    before = len(store.list_items())
    store.seed_demo_content()
    after = len(store.list_items())
    return {"added": after - before, "total": after}


@router.get("/dashboard/summary")
def dashboard_summary(current_user: User = Depends(get_current_user)) -> dict:
    repo = LearningRepository()
    try:
        return repo.dashboard_summary(student_id=current_user.student_id)
    finally:
        repo.close()


@router.get("/dashboard/files")
def dashboard_files(limit: int = 50, current_user: User = Depends(get_current_user)) -> dict:
    repo = LearningRepository()
    try:
        return {"items": repo.dashboard_files(limit=limit)}
    finally:
        repo.close()


@router.delete("/dashboard/files/{file_id}")
def dashboard_delete_file(file_id: int, current_user: User = Depends(get_current_user)) -> dict:
    repo = LearningRepository()
    try:
        deleted = repo.delete_course_file(file_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="课程资料不存在")
        return {"deleted": True, "file_id": file_id}
    finally:
        repo.close()


@router.get("/dashboard/profiles")
def dashboard_profiles(limit: int = 50, current_user: User = Depends(get_current_user)) -> dict:
    repo = LearningRepository()
    try:
        return {"items": repo.dashboard_profiles(limit=limit, student_id=current_user.student_id)}
    finally:
        repo.close()


@router.get("/dashboard/resources")
def dashboard_resources(limit: int = 50, current_user: User = Depends(get_current_user)) -> dict:
    repo = LearningRepository()
    try:
        return {"items": repo.dashboard_resources(limit=limit, student_id=current_user.student_id)}
    finally:
        repo.close()


@router.get("/dashboard/paths")
def dashboard_paths(limit: int = 50, current_user: User = Depends(get_current_user)) -> dict:
    repo = LearningRepository()
    try:
        return {"items": repo.dashboard_paths(limit=limit, student_id=current_user.student_id)}
    finally:
        repo.close()


@router.get("/dashboard/sessions")
def dashboard_sessions(limit: int = 12, current_user: User = Depends(get_current_user)) -> dict:
    repo = LearningRepository()
    try:
        return {"items": repo.dashboard_sessions(limit=limit, student_id=current_user.student_id)}
    finally:
        repo.close()


@router.get("/dashboard/sessions/{session_id}")
def dashboard_session_detail(session_id: int, current_user: User = Depends(get_current_user)) -> dict:
    repo = LearningRepository()
    try:
        session = repo.dashboard_session_detail(path_id=session_id, student_id=current_user.student_id)
        if not session:
            raise HTTPException(status_code=404, detail="学习记录不存在")
        _backfill_legacy_quiz_resources(session)
        return session
    finally:
        repo.close()


@router.delete("/dashboard/sessions/{session_id}")
@router.post("/dashboard/sessions/{session_id}/delete")
def dashboard_delete_session(session_id: int, current_user: User = Depends(get_current_user)) -> dict:
    repo = LearningRepository()
    try:
        deleted = repo.delete_dashboard_session(path_id=session_id, student_id=current_user.student_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="学习记录不存在")
        return {"deleted": True, "session_id": session_id}
    finally:
        repo.close()


def _backfill_legacy_quiz_resources(session: dict) -> None:
    profile = session.get("profile") or {}
    course = session.get("course") or ""
    for resource in session.get("resources") or []:
        if resource.get("type") != "quiz":
            continue
        if isinstance(resource.get("quiz"), list) and resource["quiz"]:
            continue
        resource["quiz"] = _build_quiz_items(
            profile=profile,
            user_input=course,
            level=1,
        )
        resource["content"] = ""
        resource["legacy_backfilled"] = True


@router.get("/dashboard/events")
def dashboard_events(limit: int = 80, current_user: User = Depends(get_current_user)) -> dict:
    repo = LearningRepository()
    try:
        return {"items": repo.dashboard_events(limit=limit, student_id=current_user.student_id)}
    finally:
        repo.close()


def _grade_quiz(quiz: list[dict], answers: dict[str, str]) -> dict:
    total_score = sum(int(item.get("score", 0) or 0) for item in quiz) or len(quiz)
    earned_score = 0
    details = []
    wrong_items = []

    for index, item in enumerate(quiz, start=1):
        question_id = str(item.get("id") or f"q{index}")
        score = int(item.get("score", 0) or 0) or 1
        answer = _normalize_answer(answers.get(question_id, ""))
        expected = _normalize_answer(item.get("answer", ""))
        item_type = item.get("type", "")

        if item_type in {"short_answer", "application", "code_reading"}:
            ratio = _score_text_answer(answer, expected, item.get("keywords", []))
            item_score = round(score * ratio, 1)
            is_correct = item_score >= score * 0.8
        else:
            item_score = score if answer == expected else 0
            is_correct = item_score == score

        earned_score += item_score
        detail = {
            "id": question_id,
            "index": index,
            "type_label": item.get("type_label", "题目"),
            "question": item.get("question", ""),
            "student_answer": answers.get(question_id, ""),
            "correct_answer": item.get("answer", ""),
            "score": item_score,
            "full_score": score,
            "is_correct": is_correct,
            "knowledge_point": item.get("knowledge_point", ""),
            "explanation": item.get("explanation", ""),
        }
        details.append(detail)
        if not is_correct:
            wrong_items.append(detail)

    percent = round((earned_score / total_score) * 100, 1) if total_score else 0
    return {
        "score": round(earned_score, 1),
        "total_score": total_score,
        "percent": percent,
        "correct_count": len(details) - len(wrong_items),
        "total_count": len(details),
        "details": details,
        "wrong_items": wrong_items,
        "summary": _quiz_summary(percent, wrong_items),
    }


def _normalize_answer(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    compact = "".join(text.replace("，", ",").split()).upper()
    if "," in compact:
        return "".join(sorted(part for part in compact.split(",") if part))
    if len(compact) > 1 and all(char in "ABCDEFG" for char in compact):
        return "".join(sorted(compact))
    if compact in {"正确", "对", "TRUE", "T"}:
        return "A"
    if compact in {"错误", "错", "FALSE", "F"}:
        return "B"
    return text.strip()


def _score_text_answer(answer: str, expected: str, keywords: object) -> float:
    answer_text = _compact_text(answer)
    expected_text = _compact_text(expected)
    if not answer_text:
        return 0.0
    if answer_text == expected_text:
        return 1.0
    if expected_text and (expected_text in answer_text or answer_text in expected_text):
        return 1.0

    similarity = SequenceMatcher(None, answer_text, expected_text).ratio() if expected_text else 0.0
    if similarity >= 0.86:
        return 1.0

    keyword_list = keywords if isinstance(keywords, list) else []
    compact_keywords = [_compact_text(keyword) for keyword in keyword_list if str(keyword).strip()]
    if compact_keywords:
        hit_count = sum(1 for keyword in compact_keywords if keyword and keyword in answer_text)
        keyword_ratio = hit_count / len(compact_keywords)
        return max(keyword_ratio, similarity * 0.9)

    return similarity


def _compact_text(value: object) -> str:
    text = str(value or "").lower()
    remove_chars = " \t\r\n,.;:!?，。；：！？、（）()[]【】{}<>《》`'\"“”‘’|/\\-_=+*#"
    return "".join(char for char in text if char not in remove_chars)


def _quiz_summary(percent: float, wrong_items: list[dict]) -> str:
    if percent >= 85:
        return "掌握较好，可以进入代码实操或挑战题。"
    if percent >= 60:
        points = "、".join(item.get("knowledge_point") or item.get("type_label", "相关知识点") for item in wrong_items[:3])
        return f"基础已具备，建议重点复盘：{points}。"
    points = "、".join(item.get("knowledge_point") or item.get("type_label", "相关知识点") for item in wrong_items[:3])
    return f"本次测验暴露出较明显短板，建议先回看讲解文档，再重做这些知识点：{points}。"
