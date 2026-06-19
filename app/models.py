from typing import Any

from pydantic import BaseModel, Field


class LearningRequest(BaseModel):
    student_id: str = Field(default="demo-student")
    course: str = Field(default="机器学习")
    message: str


class LearningResponse(BaseModel):
    profile: dict[str, Any]
    retrieved_context: list[dict[str, Any]]
    resources: list[dict[str, Any]]
    learning_path: dict[str, Any]
    final_answer: str


class KnowledgeItem(BaseModel):
    id: str
    filename: str
    chunk_index: int
    text: str


class KnowledgeSearchRequest(BaseModel):
    query: str
    top_k: int = 5
