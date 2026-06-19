from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict


class LearningState(TypedDict, total=False):
    student_id: str
    course: str
    user_input: str
    student_profile: dict[str, Any]
    course_context: list[dict[str, Any]]
    tasks: list[dict[str, Any]]
    resources: Annotated[list[dict[str, Any]], operator.add]
    learning_path: dict[str, Any]
    final_answer: str
