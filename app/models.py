from typing import Any

from pydantic import BaseModel, Field


class LearningRequest(BaseModel):
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


class AskQuestionRequest(BaseModel):
    course: str = Field(default="机器学习")
    question: str = Field(min_length=1, max_length=2000)
    learning_context: str | None = Field(default=None, max_length=4000)
    mode: str = Field(default="rag", pattern="^(rag|llm)$")


class AskQuestionResponse(BaseModel):
    answer: str
    retrieved_context: list[dict[str, Any]]
    course: str
    mode: str


class RegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=100)
    password: str = Field(min_length=6, max_length=128)
    student_id: str | None = Field(default=None, max_length=100)


class LoginRequest(BaseModel):
    username: str
    password: str


class UserResponse(BaseModel):
    id: int
    username: str
    student_id: str
    role: str


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse


class QuizSubmitRequest(BaseModel):
    course: str = Field(default="机器学习")
    quiz: list[dict[str, Any]]
    answers: dict[str, str]


class QuizNextRequest(BaseModel):
    course: str = Field(default="机器学习")
    level: int = Field(default=2, ge=1, le=5)
