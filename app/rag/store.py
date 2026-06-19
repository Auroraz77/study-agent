from __future__ import annotations

import json
import re
import uuid
from pathlib import Path
from typing import Any

from app import config


class KnowledgeStore:
    """Simple local RAG store.

    This MVP uses chunking plus lexical scoring so it works without an
    embedding service. It can later be replaced by Chroma, Milvus, or pgvector.
    """

    def __init__(self) -> None:
        config.ensure_dirs()
        self.index_file = config.INDEX_FILE
        self.knowledge_dir = config.KNOWLEDGE_DIR
        self.items = self._load()

    def _load(self) -> list[dict[str, Any]]:
        if not self.index_file.exists():
            return []
        return json.loads(self.index_file.read_text(encoding="utf-8"))

    def _save(self) -> None:
        self.index_file.write_text(
            json.dumps(self.items, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def list_items(self) -> list[dict[str, Any]]:
        return self.items

    def add_text(self, filename: str, text: str) -> list[dict[str, Any]]:
        safe_name = Path(filename).name
        raw_path = self.knowledge_dir / safe_name
        raw_path.write_text(text, encoding="utf-8")

        chunks = _chunk_text(text)
        added: list[dict[str, Any]] = []
        for index, chunk in enumerate(chunks):
            item = {
                "id": str(uuid.uuid4()),
                "filename": safe_name,
                "chunk_index": index,
                "text": chunk,
            }
            self.items.append(item)
            added.append(item)

        self._save()
        return added

    def search(self, query: str, top_k: int = 5) -> list[dict[str, Any]]:
        if not self.items:
            return []

        query_terms = _tokenize(query)
        scored: list[tuple[float, dict[str, Any]]] = []
        for item in self.items:
            text = item["text"]
            terms = _tokenize(text)
            overlap = len(query_terms & terms)
            contains_bonus = 1.5 if query and query in text else 0
            score = overlap + contains_bonus
            if score > 0:
                scored.append((score, item))

        scored.sort(key=lambda row: row[0], reverse=True)
        return [
            {**item, "score": round(score, 3)}
            for score, item in scored[:top_k]
        ]

    def seed_demo_content(self) -> None:
        if self.items:
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
        self.add_text("machine_learning_demo.txt", demo.strip())


def _chunk_text(text: str, size: int = 450, overlap: int = 80) -> list[str]:
    normalized = re.sub(r"\s+", " ", text).strip()
    if not normalized:
        return []

    chunks: list[str] = []
    start = 0
    while start < len(normalized):
        end = min(start + size, len(normalized))
        chunks.append(normalized[start:end])
        if end == len(normalized):
            break
        start = max(0, end - overlap)
    return chunks


def _tokenize(text: str) -> set[str]:
    lower = text.lower()
    english = re.findall(r"[a-zA-Z0-9_]+", lower)
    chinese = re.findall(r"[\u4e00-\u9fff]", lower)
    return set(english + chinese)
