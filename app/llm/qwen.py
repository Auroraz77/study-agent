from __future__ import annotations

import json
from typing import Any

import requests

from app import config


class QwenClient:
    """Small OpenAI-compatible client for Tongyi Qianwen.

    If no API key is configured, the client returns deterministic mock content
    so the whole demo can run offline during development.
    """

    def __init__(self) -> None:
        self.api_key = config.QWEN_API_KEY
        self.model = config.QWEN_MODEL
        self.base_url = config.QWEN_BASE_URL.rstrip("/")

    @property
    def is_mock(self) -> bool:
        return config.FORCE_MOCK_LLM or not bool(self.api_key)

    def chat(self, system: str, user: str, temperature: float = 0.4) -> str:
        if self.is_mock:
            return self._mock_response(system, user)

        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
        }

        try:
            response = requests.post(url, headers=headers, json=payload, timeout=60)
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"]
        except requests.RequestException:
            return self._mock_response(system, user)

    def chat_json(
        self,
        system: str,
        user: str,
        fallback: dict[str, Any],
        temperature: float = 0.2,
    ) -> dict[str, Any]:
        text = self.chat(system, user, temperature=temperature)
        try:
            return json.loads(_strip_json_fence(text))
        except json.JSONDecodeError:
            return fallback

    def _mock_response(self, system: str, user: str) -> str:
        if "学生画像" in system:
            return json.dumps(
                {
                    "major": "人工智能",
                    "course": "机器学习",
                    "goal": "理解核心算法并完成实践项目",
                    "knowledge_base": "Python 基础较好，数学基础一般",
                    "weaknesses": ["梯度下降", "模型评估", "概率基础"],
                    "learning_style": ["图解", "代码案例", "分步骤讲解"],
                    "time_budget": "每周 6 小时",
                    "difficulty_preference": "由浅入深",
                },
                ensure_ascii=False,
            )

        if "学习路径" in system:
            return json.dumps(
                {
                    "title": "机器学习个性化学习路径",
                    "stages": [
                        {
                            "name": "基础补强",
                            "goal": "补齐概率、线性代数和分类任务基础",
                            "resources": ["讲解文档"],
                        },
                        {
                            "name": "核心概念",
                            "goal": "理解逻辑回归、损失函数和梯度下降",
                            "resources": ["讲解文档", "练习题"],
                        },
                        {
                            "name": "代码实践",
                            "goal": "完成鸢尾花分类实验",
                            "resources": ["代码实操案例"],
                        },
                        {
                            "name": "测评反馈",
                            "goal": "通过题目定位薄弱点并调整后续学习",
                            "resources": ["练习题"],
                        },
                    ],
                },
                ensure_ascii=False,
            )

        return "这是基于学生画像和课程知识库生成的个性化学习内容。"


def _strip_json_fence(text: str) -> str:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.startswith("json"):
            cleaned = cleaned[4:]
    return cleaned.strip()
