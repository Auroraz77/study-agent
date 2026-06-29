from __future__ import annotations

import hashlib
import math
import re
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import config
from app.db.database import SessionLocal
from app.db.models import (
    Course,
    CourseFile,
    GeneratedResource,
    KnowledgeChunk,
    KnowledgeEmbedding,
    LearningEvent,
    LearningPath,
    ResourceAudio,
    StudentProfile,
    User,
)


class LearningRepository:
    def __init__(self, session: Session | None = None) -> None:
        self.session = session or SessionLocal()
        self._owns_session = session is None

    def close(self) -> None:
        if self._owns_session:
            self.session.close()

    def get_or_create_course(self, name: str) -> Course:
        course_name = name or "机器学习"
        course = self.session.scalar(select(Course).where(Course.name == course_name))
        if course:
            return course
        course = Course(name=course_name)
        self.session.add(course)
        self.session.flush()
        return course

    def create_user(
        self,
        username: str,
        password_hash: str,
        student_id: str,
        role: str = "student",
    ) -> User:
        user = User(
            username=username,
            password_hash=password_hash,
            student_id=student_id,
            role=role or "student",
        )
        self.session.add(user)
        self.session.commit()
        self.session.refresh(user)
        return user

    def get_user_by_id(self, user_id: int) -> User | None:
        return self.session.get(User, user_id)

    def get_user_by_username(self, username: str) -> User | None:
        return self.session.scalar(select(User).where(User.username == username))

    def get_user_by_student_id(self, student_id: str) -> User | None:
        return self.session.scalar(select(User).where(User.student_id == student_id))

    def create_course_file(
        self,
        course_name: str,
        filename: str,
        file_type: str | None,
        file_size: int | None,
        storage: dict[str, Any] | None,
        parse_status: str,
        uploader_id: str | None = None,
        parse_error: str | None = None,
    ) -> CourseFile:
        course = self.get_or_create_course(course_name)
        record = CourseFile(
            course_id=course.id,
            uploader_id=uploader_id,
            filename=Path(filename or "uploaded-file").name,
            file_type=file_type,
            file_size=file_size,
            bucket_name=(storage or {}).get("bucket"),
            object_name=(storage or {}).get("object_name"),
            storage_url=(storage or {}).get("storage_url"),
            parse_status=parse_status,
            parse_error=parse_error,
            metadata_json=storage or {},
        )
        self.session.add(record)
        self.session.commit()
        self.session.refresh(record)
        return record

    def update_file_status(
        self,
        file_id: int,
        parse_status: str,
        parse_error: str | None = None,
    ) -> None:
        record = self.session.get(CourseFile, file_id)
        if not record:
            return
        record.parse_status = parse_status
        record.parse_error = parse_error
        self.session.commit()

    def get_course_file(self, file_id: int) -> CourseFile | None:
        return self.session.get(CourseFile, file_id)

    def delete_course_file(self, file_id: int) -> bool:
        record = self.session.get(CourseFile, file_id)
        if not record:
            return False

        chunks = self.session.scalars(
            select(KnowledgeChunk).where(KnowledgeChunk.file_id == file_id)
        ).all()
        for chunk in chunks:
            if chunk.embedding:
                self.session.delete(chunk.embedding)
            self.session.delete(chunk)

        self.session.delete(record)
        self.session.commit()
        return True

    def add_knowledge_text(
        self,
        course_name: str,
        filename: str,
        text: str,
        file_id: int | None = None,
    ) -> list[dict[str, Any]]:
        course = self.get_or_create_course(course_name)
        chunks = _chunk_text_with_page_numbers(text)
        added: list[dict[str, Any]] = []
        safe_name = Path(filename or "uploaded.txt").name

        if file_id is not None:
            existing_chunks = self.session.scalars(
                select(KnowledgeChunk).where(KnowledgeChunk.file_id == file_id)
            ).all()
            for chunk in existing_chunks:
                if chunk.embedding:
                    self.session.delete(chunk.embedding)
                self.session.delete(chunk)
            self.session.flush()

        for index, (chunk_text, page_number) in enumerate(chunks):
            chunk = KnowledgeChunk(
                file_id=file_id,
                course_id=course.id,
                chunk_index=index,
                source_filename=safe_name,
                content=chunk_text,
                token_count=len(chunk_text),
                page_number=page_number,
                metadata_json={},
            )
            self.session.add(chunk)
            self.session.flush()

            embedding = KnowledgeEmbedding(
                chunk_id=chunk.id,
                course_id=course.id,
                embedding=make_embedding(chunk_text),
            )
            self.session.add(embedding)
            added.append(_chunk_to_item(chunk, score=1.0))

        self.session.commit()
        return added

    def list_chunks(self, limit: int = 200) -> list[dict[str, Any]]:
        stmt = select(KnowledgeChunk).order_by(KnowledgeChunk.created_at.desc()).limit(limit)
        chunks = self.session.scalars(stmt).all()
        return [_chunk_to_item(chunk) for chunk in chunks]

    def search_chunks(
        self,
        query: str,
        top_k: int = 5,
        course_name: str | None = None,
    ) -> list[dict[str, Any]]:
        if not query.strip():
            return []

        query_vector = make_embedding(query)
        distance = KnowledgeEmbedding.embedding.cosine_distance(query_vector)
        stmt = (
            select(KnowledgeChunk, distance.label("distance"))
            .join(KnowledgeEmbedding, KnowledgeEmbedding.chunk_id == KnowledgeChunk.id)
            .order_by(distance)
            .limit(top_k)
        )

        if course_name:
            stmt = stmt.join(Course, Course.id == KnowledgeChunk.course_id).where(Course.name == course_name)

        rows = self.session.execute(stmt).all()
        if rows:
            return [
                _chunk_to_item(chunk, score=round(max(0.0, 1.0 - float(dist or 0)), 4))
                for chunk, dist in rows
            ]

        return self._lexical_search(query, top_k=top_k, course_name=course_name)

    def get_chunk_detail(self, chunk_id: int) -> dict[str, Any] | None:
        chunk = self.session.get(KnowledgeChunk, chunk_id)
        if not chunk:
            return None

        previous_chunk = self.session.scalar(
            select(KnowledgeChunk)
            .where(
                KnowledgeChunk.file_id == chunk.file_id,
                KnowledgeChunk.chunk_index < chunk.chunk_index,
            )
            .order_by(KnowledgeChunk.chunk_index.desc())
            .limit(1)
        )
        next_chunk = self.session.scalar(
            select(KnowledgeChunk)
            .where(
                KnowledgeChunk.file_id == chunk.file_id,
                KnowledgeChunk.chunk_index > chunk.chunk_index,
            )
            .order_by(KnowledgeChunk.chunk_index.asc())
            .limit(1)
        )
        file_record = chunk.file
        item = _chunk_to_item(chunk)
        item.update(
            {
                "previous_chunk_id": previous_chunk.id if previous_chunk else None,
                "next_chunk_id": next_chunk.id if next_chunk else None,
                "file": _course_file_to_payload(file_record) if file_record else None,
            }
        )
        return item

    def save_learning_result(
        self,
        student_id: str,
        course_name: str,
        profile: dict[str, Any],
        resources: list[dict[str, Any]],
        learning_path: dict[str, Any],
    ) -> None:
        course = self.get_or_create_course(course_name)
        existing = self.session.scalar(
            select(StudentProfile).where(
                StudentProfile.student_id == student_id,
                StudentProfile.course_id == course.id,
            )
        )
        if existing:
            profile_record = existing
        else:
            profile_record = StudentProfile(student_id=student_id, course_id=course.id)
            self.session.add(profile_record)

        profile_record.knowledge_base = profile.get("knowledge_base")
        profile_record.learning_goal = profile.get("goal")
        profile_record.weaknesses = _as_list(profile.get("weaknesses"))
        profile_record.learning_style = _as_list(profile.get("learning_style"))
        profile_record.time_budget = profile.get("time_budget")
        profile_record.difficulty_preference = profile.get("difficulty_preference")
        profile_record.profile_json = profile

        for resource in resources:
            resource_record = GeneratedResource(
                student_id=student_id,
                course_id=course.id,
                resource_type=resource.get("type", "unknown"),
                title=resource.get("title", "Untitled resource"),
                agent=resource.get("agent"),
                content=resource.get("content", ""),
                generation_params={
                    "source": "langgraph",
                    "modality": resource.get("modality"),
                    "quiz": resource.get("quiz"),
                },
            )
            self.session.add(resource_record)
            self.session.flush()
            resource["id"] = resource_record.id
            resource["has_audio"] = False

        self.session.add(
            LearningPath(
                student_id=student_id,
                course_id=course.id,
                path_json=learning_path or {},
                status="active",
            )
        )
        self.session.add(
            LearningEvent(
                student_id=student_id,
                course_id=course.id,
                event_type="generate_learning_plan",
                event_data={
                    "resource_count": len(resources),
                    "profile": profile,
                },
            )
        )
        self.session.commit()

    def save_quiz_attempt(
        self,
        student_id: str,
        course_name: str,
        result: dict[str, Any],
    ) -> None:
        course = self.get_or_create_course(course_name)
        self.session.add(
            LearningEvent(
                student_id=student_id,
                course_id=course.id,
                event_type="submit_quiz",
                event_data=result,
            )
        )
        self.session.commit()

    def get_generated_resource(self, resource_id: int, student_id: str) -> GeneratedResource | None:
        return self.session.scalar(
            select(GeneratedResource).where(
                GeneratedResource.id == resource_id,
                GeneratedResource.student_id == student_id,
            )
        )

    def get_resource_audio(
        self,
        resource_id: int,
        student_id: str,
        model: str,
        voice: str,
        text_hash: str,
    ) -> ResourceAudio | None:
        return self.session.scalar(
            select(ResourceAudio)
            .where(
                ResourceAudio.resource_id == resource_id,
                ResourceAudio.student_id == student_id,
                ResourceAudio.model == model,
                ResourceAudio.voice == voice,
                ResourceAudio.text_hash == text_hash,
            )
            .order_by(ResourceAudio.created_at.desc())
            .limit(1)
        )

    def get_latest_resource_audio(self, resource_id: int, student_id: str) -> ResourceAudio | None:
        return self.session.scalar(
            select(ResourceAudio)
            .where(
                ResourceAudio.resource_id == resource_id,
                ResourceAudio.student_id == student_id,
            )
            .order_by(ResourceAudio.created_at.desc())
            .limit(1)
        )

    def save_resource_audio(
        self,
        resource: GeneratedResource,
        model: str,
        voice: str,
        text_hash: str,
        storage: dict[str, Any],
        metadata: dict[str, Any] | None = None,
    ) -> ResourceAudio:
        audio = ResourceAudio(
            resource_id=resource.id,
            student_id=resource.student_id,
            course_id=resource.course_id,
            model=model,
            voice=voice,
            text_hash=text_hash,
            content_type=storage.get("content_type") or "audio/mpeg",
            bucket_name=storage.get("bucket"),
            object_name=storage.get("object_name"),
            storage_url=storage.get("storage_url"),
            file_size=storage.get("size"),
            metadata_json=metadata or {},
        )
        self.session.add(audio)
        self.session.commit()
        self.session.refresh(audio)
        return audio

    def save_learning_event(
        self,
        student_id: str,
        course_name: str,
        event_type: str,
        event_data: dict[str, Any],
    ) -> None:
        course = self.get_or_create_course(course_name)
        self.session.add(
            LearningEvent(
                student_id=student_id,
                course_id=course.id,
                event_type=event_type,
                event_data=event_data,
            )
        )
        self.session.commit()

    def _lexical_search(
        self,
        query: str,
        top_k: int,
        course_name: str | None,
    ) -> list[dict[str, Any]]:
        stmt = select(KnowledgeChunk)
        if course_name:
            stmt = stmt.join(Course, Course.id == KnowledgeChunk.course_id).where(Course.name == course_name)
        chunks = self.session.scalars(stmt.limit(1000)).all()
        query_terms = _tokenize(query)
        scored: list[tuple[float, KnowledgeChunk]] = []
        for chunk in chunks:
            terms = _tokenize(chunk.content)
            score = len(query_terms & terms)
            if score > 0:
                scored.append((float(score), chunk))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [_chunk_to_item(chunk, score=score) for score, chunk in scored[:top_k]]

    def dashboard_summary(self, student_id: str | None = None) -> dict[str, Any]:
        file_status_rows = self.session.execute(
            select(CourseFile.parse_status, func.count(CourseFile.id)).group_by(CourseFile.parse_status)
        ).all()
        resource_type_stmt = select(GeneratedResource.resource_type, func.count(GeneratedResource.id))
        if student_id:
            resource_type_stmt = resource_type_stmt.where(GeneratedResource.student_id == student_id)
        resource_type_rows = self.session.execute(
            resource_type_stmt.group_by(GeneratedResource.resource_type)
        ).all()
        course_chunk_rows = self.session.execute(
            select(Course.name, func.count(KnowledgeChunk.id))
            .join(KnowledgeChunk, KnowledgeChunk.course_id == Course.id, isouter=True)
            .group_by(Course.name)
            .order_by(func.count(KnowledgeChunk.id).desc())
            .limit(8)
        ).all()

        return {
            "counts": {
                "courses": self.session.scalar(select(func.count(Course.id))) or 0,
                "files": self.session.scalar(select(func.count(CourseFile.id))) or 0,
                "parsed_files": self.session.scalar(
                    select(func.count(CourseFile.id)).where(CourseFile.parse_status == "parsed")
                )
                or 0,
                "knowledge_chunks": self.session.scalar(select(func.count(KnowledgeChunk.id))) or 0,
                "knowledge_embeddings": self.session.scalar(select(func.count(KnowledgeEmbedding.id))) or 0,
                "student_profiles": self._count_for_student(StudentProfile, student_id),
                "generated_resources": self._count_for_student(GeneratedResource, student_id),
                "learning_paths": self._count_for_student(LearningPath, student_id),
                "learning_events": self._count_for_student(LearningEvent, student_id),
            },
            "file_status": [
                {"status": status or "unknown", "count": count}
                for status, count in file_status_rows
            ],
            "resource_types": [
                {"type": resource_type or "unknown", "count": count}
                for resource_type, count in resource_type_rows
            ],
            "course_chunks": [
                {"course": course or "unknown", "count": count}
                for course, count in course_chunk_rows
            ],
        }

    def dashboard_files(self, limit: int = 50) -> list[dict[str, Any]]:
        chunk_count = func.count(KnowledgeChunk.id).label("chunk_count")
        stmt = (
            select(CourseFile, Course.name, chunk_count)
            .join(Course, Course.id == CourseFile.course_id)
            .join(KnowledgeChunk, KnowledgeChunk.file_id == CourseFile.id, isouter=True)
            .group_by(CourseFile.id, Course.name)
            .order_by(CourseFile.created_at.desc())
            .limit(limit)
        )
        return [
            {
                "id": file.id,
                "course": course,
                "filename": file.filename,
                "file_type": file.file_type,
                "file_size": file.file_size,
                "bucket_name": file.bucket_name,
                "object_name": file.object_name,
                "storage_url": file.storage_url,
                "parse_status": file.parse_status,
                "parse_error": file.parse_error,
                "chunk_count": chunks,
                "created_at": _iso(file.created_at),
            }
            for file, course, chunks in self.session.execute(stmt).all()
        ]

    def dashboard_profiles(self, limit: int = 50, student_id: str | None = None) -> list[dict[str, Any]]:
        stmt = (
            select(StudentProfile, Course.name)
            .join(Course, Course.id == StudentProfile.course_id)
            .order_by(StudentProfile.updated_at.desc())
        )
        if student_id:
            stmt = stmt.where(StudentProfile.student_id == student_id)
        stmt = stmt.limit(limit)
        return [
            {
                "id": profile.id,
                "student_id": profile.student_id,
                "course": course,
                "knowledge_base": profile.knowledge_base,
                "learning_goal": profile.learning_goal,
                "weaknesses": profile.weaknesses or [],
                "learning_style": profile.learning_style or [],
                "time_budget": profile.time_budget,
                "difficulty_preference": profile.difficulty_preference,
                "profile_json": profile.profile_json or {},
                "updated_at": _iso(profile.updated_at),
            }
            for profile, course in self.session.execute(stmt).all()
        ]

    def dashboard_resources(self, limit: int = 50, student_id: str | None = None) -> list[dict[str, Any]]:
        stmt = (
            select(GeneratedResource, Course.name)
            .join(Course, Course.id == GeneratedResource.course_id)
            .order_by(GeneratedResource.created_at.desc())
        )
        if student_id:
            stmt = stmt.where(GeneratedResource.student_id == student_id)
        stmt = stmt.limit(limit)
        return [
            {
                "id": resource.id,
                "student_id": resource.student_id,
                "course": course,
                "resource_type": resource.resource_type,
                "title": resource.title,
                "agent": resource.agent,
                "content_preview": (resource.content or "")[:180],
                "created_at": _iso(resource.created_at),
            }
            for resource, course in self.session.execute(stmt).all()
        ]

    def dashboard_paths(self, limit: int = 50, student_id: str | None = None) -> list[dict[str, Any]]:
        stmt = (
            select(LearningPath, Course.name)
            .join(Course, Course.id == LearningPath.course_id)
            .order_by(LearningPath.created_at.desc())
        )
        if student_id:
            stmt = stmt.where(LearningPath.student_id == student_id)
        stmt = stmt.limit(limit)
        paths = []
        for path, course in self.session.execute(stmt).all():
            stages = (path.path_json or {}).get("stages", [])
            paths.append(
                {
                    "id": path.id,
                    "student_id": path.student_id,
                    "course": course,
                    "title": (path.path_json or {}).get("title", "个性化学习路径"),
                    "stage_count": len(stages) if isinstance(stages, list) else 0,
                    "status": path.status,
                    "path_json": path.path_json or {},
                    "created_at": _iso(path.created_at),
                    "updated_at": _iso(path.updated_at),
                }
            )
        return paths

    def dashboard_sessions(self, limit: int = 12, student_id: str | None = None) -> list[dict[str, Any]]:
        stmt = (
            select(LearningPath, Course.name)
            .join(Course, Course.id == LearningPath.course_id)
            .order_by(LearningPath.created_at.desc())
        )
        if student_id:
            stmt = stmt.where(LearningPath.student_id == student_id)
        stmt = stmt.limit(limit)

        sessions = []
        for path, course in self.session.execute(stmt).all():
            resources = self._resources_for_path_session(path)
            audio_resource_ids = self._resource_ids_with_audio(resources)
            stages = (path.path_json or {}).get("stages", [])
            sessions.append(
                {
                    "id": path.id,
                    "student_id": path.student_id,
                    "course": course,
                    "title": (path.path_json or {}).get("title") or course,
                    "created_at": _iso(path.created_at),
                    "updated_at": _iso(path.updated_at),
                    "stage_count": len(stages) if isinstance(stages, list) else 0,
                    "resource_count": len(resources),
                    "resource_titles": [resource.title for resource in resources],
                    "preview": _session_preview(resources, path.path_json or {}),
                    "has_audio": bool(audio_resource_ids),
                }
            )
        return sessions

    def dashboard_session_detail(self, path_id: int, student_id: str) -> dict[str, Any] | None:
        row = self.session.execute(
            select(LearningPath, Course.name)
            .join(Course, Course.id == LearningPath.course_id)
            .where(LearningPath.id == path_id, LearningPath.student_id == student_id)
        ).first()
        if not row:
            return None

        path, course = row
        resources = self._resources_for_path_session(path)
        profile = self.session.scalar(
            select(StudentProfile).where(
                StudentProfile.student_id == student_id,
                StudentProfile.course_id == path.course_id,
            )
        )
        audio_resource_ids = self._resource_ids_with_audio(resources)
        resource_payload = [_resource_to_payload(resource) for resource in resources]
        for resource in resource_payload:
            resource["has_audio"] = resource.get("id") in audio_resource_ids
        return {
            "session_id": path.id,
            "course": course,
            "profile": (profile.profile_json if profile else {}) or {},
            "learning_path": path.path_json or {},
            "resources": resource_payload,
            "retrieved_context": [],
            "final_answer": _session_final_answer(course, resource_payload, path.path_json or {}),
            "created_at": _iso(path.created_at),
        }

    def delete_dashboard_session(self, path_id: int, student_id: str) -> bool:
        path = self.session.scalar(
            select(LearningPath).where(LearningPath.id == path_id, LearningPath.student_id == student_id)
        )
        if not path:
            return False

        for resource in self._resources_for_path_session(path):
            for audio in self.session.scalars(
                select(ResourceAudio).where(ResourceAudio.resource_id == resource.id)
            ).all():
                self.session.delete(audio)
            self.session.delete(resource)
        self.session.delete(path)
        self.session.commit()
        return True

    def _resources_for_path_session(self, path: LearningPath) -> list[GeneratedResource]:
        stmt = (
            select(GeneratedResource)
            .where(
                GeneratedResource.student_id == path.student_id,
                GeneratedResource.course_id == path.course_id,
            )
            .order_by(GeneratedResource.created_at.asc())
        )
        resources = []
        for resource in self.session.scalars(stmt).all():
            if resource.created_at and path.created_at:
                distance = abs((resource.created_at - path.created_at).total_seconds())
                if distance <= 300:
                    resources.append(resource)
        return resources

    def _resource_ids_with_audio(self, resources: list[GeneratedResource]) -> set[int]:
        resource_ids = [resource.id for resource in resources]
        if not resource_ids:
            return set()
        rows = self.session.scalars(
            select(ResourceAudio.resource_id).where(ResourceAudio.resource_id.in_(resource_ids))
        ).all()
        return {int(resource_id) for resource_id in rows}

    def dashboard_events(self, limit: int = 80, student_id: str | None = None) -> list[dict[str, Any]]:
        stmt = (
            select(LearningEvent, Course.name)
            .join(Course, Course.id == LearningEvent.course_id)
            .order_by(LearningEvent.created_at.desc())
        )
        if student_id:
            stmt = stmt.where(LearningEvent.student_id == student_id)
        stmt = stmt.limit(limit)
        return [
            {
                "id": event.id,
                "student_id": event.student_id,
                "course": course,
                "event_type": event.event_type,
                "resource_id": event.resource_id,
                "event_data": event.event_data or {},
                "created_at": _iso(event.created_at),
            }
            for event, course in self.session.execute(stmt).all()
        ]

    def _count_for_student(self, model: Any, student_id: str | None) -> int:
        stmt = select(func.count(model.id))
        if student_id:
            stmt = stmt.where(model.student_id == student_id)
        return self.session.scalar(stmt) or 0


def _chunk_text_with_page_numbers(text: str, size: int = 450, overlap: int = 80) -> list[tuple[str, int | None]]:
    normalized = re.sub(r"\s+", " ", text).strip()
    if not normalized:
        return []

    page_markers = [
        (match.start(), int(match.group(1)))
        for match in re.finditer(r"第\s*(\d+)\s*页", normalized)
    ]
    if page_markers:
        chunks: list[tuple[str, int | None]] = []
        for index, (marker_start, page_number) in enumerate(page_markers):
            next_start = page_markers[index + 1][0] if index + 1 < len(page_markers) else len(normalized)
            page_text = normalized[marker_start:next_start].strip()
            for chunk_text in _chunk_normalized_text(page_text, size=size, overlap=overlap):
                chunks.append((chunk_text, page_number))
        return chunks

    return [(chunk_text, None) for chunk_text in _chunk_normalized_text(normalized, size=size, overlap=overlap)]


def _chunk_normalized_text(normalized: str, size: int = 450, overlap: int = 80) -> list[str]:
    chunks: list[str] = []
    start = 0
    while start < len(normalized):
        end = min(start + size, len(normalized))
        chunks.append(normalized[start:end])
        if end == len(normalized):
            break
        start = max(0, end - overlap)
    return chunks


def _chunk_text(text: str, size: int = 450, overlap: int = 80) -> list[str]:
    return [chunk for chunk, _page_number in _chunk_text_with_page_numbers(text, size=size, overlap=overlap)]


def _tokenize(text: str) -> set[str]:
    lower = text.lower()
    english = re.findall(r"[a-zA-Z0-9_]+", lower)
    chinese = re.findall(r"[\u4e00-\u9fff]", lower)
    return set(english + chinese)


def make_embedding(text: str) -> list[float]:
    vector = [0.0] * config.EMBEDDING_DIM
    tokens = list(_tokenize(text)) or [text[:32] or "empty"]
    for token in tokens:
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        bucket = int.from_bytes(digest[:4], "big") % config.EMBEDDING_DIM
        vector[bucket] += 1.0

    norm = math.sqrt(sum(value * value for value in vector)) or 1.0
    return [value / norm for value in vector]


def _chunk_to_item(chunk: KnowledgeChunk, score: float | None = None) -> dict[str, Any]:
    file_record = chunk.file
    file_type = file_record.file_type if file_record else None
    filename = chunk.source_filename or (file_record.filename if file_record else "")
    is_pdf = (file_type or "").lower() == "application/pdf" or filename.lower().endswith(".pdf")
    item = {
        "id": str(chunk.id),
        "filename": filename,
        "chunk_index": chunk.chunk_index,
        "text": chunk.content,
        "course_id": chunk.course_id,
        "file_id": chunk.file_id,
        "page_number": chunk.page_number,
        "file_type": file_type,
        "is_pdf": is_pdf,
    }
    if score is not None:
        item["score"] = score
    return item


def _course_file_to_payload(record: CourseFile) -> dict[str, Any]:
    return {
        "id": record.id,
        "filename": record.filename,
        "file_type": record.file_type,
        "file_size": record.file_size,
        "bucket_name": record.bucket_name,
        "object_name": record.object_name,
        "parse_status": record.parse_status,
        "created_at": _iso(record.created_at),
    }


def _as_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    if value is None:
        return []
    return [str(value)]


def _iso(value: Any) -> str | None:
    return value.isoformat(sep=" ", timespec="seconds") if value else None


def _resource_to_payload(resource: GeneratedResource) -> dict[str, Any]:
    params = resource.generation_params or {}
    payload = {
        "id": resource.id,
        "type": resource.resource_type,
        "title": resource.title,
        "agent": resource.agent,
        "modality": params.get("modality") or _infer_modality(resource.resource_type),
        "content": resource.content or "",
        "created_at": _iso(resource.created_at),
    }
    quiz = params.get("quiz")
    if isinstance(quiz, list):
        payload["quiz"] = quiz
    return payload


def _infer_modality(resource_type: str | None) -> str:
    mapping = {
        "explanation_doc": "text",
        "quiz": "assessment",
        "code_case": "code",
    }
    return mapping.get(resource_type or "", "text")


def _session_preview(resources: list[GeneratedResource], path_json: dict[str, Any]) -> str:
    if resources:
        text = resources[0].content or ""
        return re.sub(r"\s+", " ", text).strip()[:160]
    stages = path_json.get("stages", [])
    if isinstance(stages, list) and stages:
        return " / ".join(str(stage.get("name", "")) for stage in stages[:3] if isinstance(stage, dict))
    return "历史学习记录"


def _session_final_answer(course: str, resources: list[dict[str, Any]], path_json: dict[str, Any]) -> str:
    titles = "、".join(resource.get("title", "") for resource in resources if resource.get("title")) or "暂无资源"
    path_title = path_json.get("title") or "个性化学习路径"
    return (
        f"已打开《{course}》历史学习记录。\n\n"
        f"本次记录包含资源：{titles}。\n"
        f"学习路径：{path_title}。\n\n"
        "你可以继续查看讲解文档、完成练习题或导出 PPT。"
    )
