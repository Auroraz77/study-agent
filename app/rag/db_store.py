from __future__ import annotations

from pathlib import Path
from typing import Any

from app.db.repository import LearningRepository


class DatabaseKnowledgeStore:
    def list_items(self) -> list[dict[str, Any]]:
        repo = LearningRepository()
        try:
            return repo.list_chunks()
        finally:
            repo.close()

    def add_file_record(
        self,
        course: str,
        filename: str,
        file_type: str | None,
        file_size: int | None,
        storage: dict[str, Any] | None,
        parse_status: str,
        uploader_id: str | None = None,
        parse_error: str | None = None,
    ) -> int:
        repo = LearningRepository()
        try:
            record = repo.create_course_file(
                course_name=course,
                filename=filename,
                file_type=file_type,
                file_size=file_size,
                storage=storage,
                parse_status=parse_status,
                uploader_id=uploader_id,
                parse_error=parse_error,
            )
            return record.id
        finally:
            repo.close()

    def update_file_status(
        self,
        file_id: int,
        parse_status: str,
        parse_error: str | None = None,
    ) -> None:
        repo = LearningRepository()
        try:
            repo.update_file_status(file_id, parse_status, parse_error)
        finally:
            repo.close()

    def get_file(self, file_id: int) -> dict[str, Any] | None:
        repo = LearningRepository()
        try:
            record = repo.get_course_file(file_id)
            if not record:
                return None
            return {
                "id": record.id,
                "course_id": record.course_id,
                "filename": record.filename,
                "file_type": record.file_type,
                "file_size": record.file_size,
                "bucket_name": record.bucket_name,
                "object_name": record.object_name,
                "storage_url": record.storage_url,
                "parse_status": record.parse_status,
                "parse_error": record.parse_error,
            }
        finally:
            repo.close()

    def add_text(
        self,
        filename: str,
        text: str,
        course: str = "机器学习",
        file_id: int | None = None,
    ) -> list[dict[str, Any]]:
        repo = LearningRepository()
        try:
            return repo.add_knowledge_text(
                course_name=course,
                filename=Path(filename).name,
                text=text,
                file_id=file_id,
            )
        finally:
            repo.close()

    def search(self, query: str, top_k: int = 5, course: str | None = None) -> list[dict[str, Any]]:
        repo = LearningRepository()
        try:
            return repo.search_chunks(query, top_k=top_k, course_name=course)
        finally:
            repo.close()

    def seed_demo_content(self) -> None:
        if self.list_items():
            return

        demo = """
机器学习是一类让计算机从数据中学习规律的方法。监督学习使用带标签的数据训练模型，
常见任务包括分类和回归。逻辑回归虽然名字中有回归，但常用于二分类任务，它通过
sigmoid 函数把线性组合映射为 0 到 1 之间的概率。

梯度下降是一种优化方法，用于最小化损失函数。学习率过大可能导致震荡，学习率过小
会导致收敛速度慢。模型评估常用准确率、精确率、召回率和 F1 值。

在机器学习实践中，通常需要完成数据读取、数据清洗、特征处理、模型训练、模型评估
和结果解释。对于初学者，建议先通过鸢尾花分类、房价预测等小项目理解完整流程。
"""
        self.add_text("machine_learning_demo.txt", demo.strip(), course="机器学习")

    def save_learning_result(
        self,
        student_id: str,
        course: str,
        profile: dict[str, Any],
        resources: list[dict[str, Any]],
        learning_path: dict[str, Any],
    ) -> None:
        repo = LearningRepository()
        try:
            repo.save_learning_result(
                student_id=student_id,
                course_name=course,
                profile=profile,
                resources=resources,
                learning_path=learning_path,
            )
        finally:
            repo.close()
