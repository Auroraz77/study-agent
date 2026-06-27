from __future__ import annotations

from difflib import SequenceMatcher

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy.exc import IntegrityError

from app.agents.graph import LearningAgentGraph, _build_quiz_items
from app.auth import create_access_token, get_current_user, hash_password, user_to_dict, verify_password
from app.db.database import init_db
from app.db.models import User
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
            "不要做资料覆盖性判断，直接回答问题。可以使用 Markdown。"
        )
        user = (
            f"问题：{question}\n\n"
            "请输出：1. 直接回答；2. 分步骤解释；3. 一个学习建议或小例子。"
        )
    else:
        system = (
            "你是学习问答智能体，面向正在学习课程的学生答疑。"
            "回答要准确、分层、简洁，优先结合课程资料片段；如果资料不足，要明确说明并给出合理推断。"
            "不要编造资料来源。可以使用 Markdown。"
        )
        user = (
            f"课程：{course}\n"
            f"学生当前学习描述：{learning_context or '未提供'}\n"
            f"学生问题：{question}\n"
            f"课程资料片段：{context_text}\n\n"
            "请输出：1. 直接回答；2. 分步骤解释；3. 一个学习建议或小例子。"
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
