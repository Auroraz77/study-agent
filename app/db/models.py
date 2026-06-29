from __future__ import annotations

from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app import config


class Base(DeclarativeBase):
    pass


class Course(Base):
    __tablename__ = "courses"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    major: Mapped[str | None] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(30), default="student", index=True)
    student_id: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        onupdate=func.now(),
    )


class CourseFile(Base):
    __tablename__ = "course_files"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"), index=True)
    uploader_id: Mapped[str | None] = mapped_column(String(100))
    filename: Mapped[str] = mapped_column(String(500), nullable=False)
    file_type: Mapped[str | None] = mapped_column(String(80))
    file_size: Mapped[int | None] = mapped_column(BigInteger)
    bucket_name: Mapped[str | None] = mapped_column(String(200))
    object_name: Mapped[str | None] = mapped_column(String(1000))
    storage_url: Mapped[str | None] = mapped_column(String(1200))
    parse_status: Mapped[str] = mapped_column(String(60), default="pending", index=True)
    parse_error: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    course: Mapped[Course] = relationship()


class KnowledgeChunk(Base):
    __tablename__ = "knowledge_chunks"
    __table_args__ = (
        UniqueConstraint("file_id", "chunk_index", name="uq_knowledge_chunk_file_index"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    file_id: Mapped[int | None] = mapped_column(ForeignKey("course_files.id"), index=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"), index=True)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    source_filename: Mapped[str] = mapped_column(String(500), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    page_number: Mapped[int | None] = mapped_column(Integer)
    token_count: Mapped[int | None] = mapped_column(Integer)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    course: Mapped[Course] = relationship()
    file: Mapped[CourseFile | None] = relationship()
    embedding: Mapped["KnowledgeEmbedding"] = relationship(back_populates="chunk")


class KnowledgeEmbedding(Base):
    __tablename__ = "knowledge_embeddings"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    chunk_id: Mapped[int] = mapped_column(ForeignKey("knowledge_chunks.id"), unique=True, index=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"), index=True)
    embedding: Mapped[list[float]] = mapped_column(Vector(config.EMBEDDING_DIM))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    chunk: Mapped[KnowledgeChunk] = relationship(back_populates="embedding")
    course: Mapped[Course] = relationship()


class StudentProfile(Base):
    __tablename__ = "student_profiles"
    __table_args__ = (
        UniqueConstraint("student_id", "course_id", name="uq_student_profile_course"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    student_id: Mapped[str] = mapped_column(String(100), index=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"), index=True)
    knowledge_base: Mapped[str | None] = mapped_column(Text)
    learning_goal: Mapped[str | None] = mapped_column(Text)
    weaknesses: Mapped[list[str]] = mapped_column(JSONB, default=list)
    learning_style: Mapped[list[str]] = mapped_column(JSONB, default=list)
    time_budget: Mapped[str | None] = mapped_column(String(200))
    difficulty_preference: Mapped[str | None] = mapped_column(String(200))
    profile_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        onupdate=func.now(),
    )

    course: Mapped[Course] = relationship()


class GeneratedResource(Base):
    __tablename__ = "generated_resources"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    student_id: Mapped[str] = mapped_column(String(100), index=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"), index=True)
    resource_type: Mapped[str] = mapped_column(String(100), index=True)
    title: Mapped[str] = mapped_column(String(500))
    agent: Mapped[str | None] = mapped_column(String(200))
    content: Mapped[str] = mapped_column(Text)
    storage_url: Mapped[str | None] = mapped_column(String(1200))
    generation_params: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    course: Mapped[Course] = relationship()


class ResourceAudio(Base):
    __tablename__ = "resource_audios"
    __table_args__ = (
        UniqueConstraint("resource_id", "model", "voice", "text_hash", name="uq_resource_audio_variant"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    resource_id: Mapped[int] = mapped_column(ForeignKey("generated_resources.id"), index=True)
    student_id: Mapped[str] = mapped_column(String(100), index=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"), index=True)
    model: Mapped[str] = mapped_column(String(120), index=True)
    voice: Mapped[str] = mapped_column(String(120), index=True)
    text_hash: Mapped[str] = mapped_column(String(64), index=True)
    content_type: Mapped[str] = mapped_column(String(100), default="audio/mpeg")
    bucket_name: Mapped[str | None] = mapped_column(String(200))
    object_name: Mapped[str | None] = mapped_column(String(1000))
    storage_url: Mapped[str | None] = mapped_column(String(1200))
    file_size: Mapped[int | None] = mapped_column(BigInteger)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    resource: Mapped[GeneratedResource] = relationship()
    course: Mapped[Course] = relationship()


class LearningPath(Base):
    __tablename__ = "learning_paths"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    student_id: Mapped[str] = mapped_column(String(100), index=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"), index=True)
    path_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(String(60), default="active", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        onupdate=func.now(),
    )

    course: Mapped[Course] = relationship()


class LearningEvent(Base):
    __tablename__ = "learning_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    student_id: Mapped[str] = mapped_column(String(100), index=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"), index=True)
    event_type: Mapped[str] = mapped_column(String(100), index=True)
    resource_id: Mapped[int | None] = mapped_column(ForeignKey("generated_resources.id"))
    event_data: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    course: Mapped[Course] = relationship()
