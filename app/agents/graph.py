from __future__ import annotations

import json
from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from app.agents.state import LearningState
from app.llm.qwen import QwenClient
from app.rag.store import KnowledgeStore


RESOURCE_TASKS = [
    {
        "type": "explanation_doc",
        "title": "个性化讲解文档",
        "role": "课程讲解智能体",
        "node": "explanation_agent",
        "modality": "text",
        "boundary": "只负责概念讲解、公式推导、误区澄清和学习建议；不得输出完整代码案例或练习题清单。",
    },
    {
        "type": "quiz",
        "title": "个性化练习题",
        "role": "题目生成智能体",
        "node": "quiz_agent",
        "modality": "assessment",
        "boundary": "只负责生成分层练习、答案和解析；不得展开课程长文讲解或给出完整项目代码。",
    },
    {
        "type": "code_case",
        "title": "代码实操案例",
        "role": "实操案例智能体",
        "node": "code_agent",
        "modality": "code",
        "boundary": "只负责可运行代码、实验步骤、预期输出和改造任务；概念解释保持简短。",
    },
]


class LearningAgentGraph:
    def __init__(self, llm: QwenClient | None = None, store: KnowledgeStore | None = None) -> None:
        self.llm = llm or QwenClient()
        self.store = store or KnowledgeStore()
        self.graph = self._build_graph()

    def invoke(self, student_id: str, course: str, message: str) -> dict[str, Any]:
        state = self.graph.invoke(
            {
                "student_id": student_id,
                "course": course,
                "user_input": message,
                "resources": [],
            }
        )
        return {
            "profile": state.get("student_profile", {}),
            "retrieved_context": state.get("course_context", []),
            "resources": state.get("resources", []),
            "learning_path": state.get("learning_path", {}),
            "final_answer": state.get("final_answer", ""),
        }

    def _build_graph(self):
        builder = StateGraph(LearningState)
        builder.add_node("profile_agent", self._profile_agent)
        builder.add_node("retriever_agent", self._retriever_agent)
        builder.add_node("supervisor_agent", self._supervisor_agent)
        builder.add_node("explanation_agent", self._explanation_agent)
        builder.add_node("quiz_agent", self._quiz_agent)
        builder.add_node("code_agent", self._code_agent)
        builder.add_node("planner_agent", self._planner_agent)
        builder.add_node("summary_agent", self._summary_agent)

        builder.add_edge(START, "profile_agent")
        builder.add_edge("profile_agent", "retriever_agent")
        builder.add_edge("retriever_agent", "supervisor_agent")
        builder.add_conditional_edges(
            "supervisor_agent",
            self._assign_resource_workers,
            [
                "explanation_agent",
                "quiz_agent",
                "code_agent",
            ],
        )
        builder.add_edge("explanation_agent", "planner_agent")
        builder.add_edge("quiz_agent", "planner_agent")
        builder.add_edge("code_agent", "planner_agent")
        builder.add_edge("planner_agent", "summary_agent")
        builder.add_edge("summary_agent", END)
        return builder.compile()

    def _profile_agent(self, state: LearningState) -> dict[str, Any]:
        fallback = {
            "major": "人工智能",
            "course": state.get("course", "机器学习"),
            "goal": "系统学习课程并完成实践任务",
            "knowledge_base": "待进一步评估",
            "weaknesses": ["待诊断"],
            "learning_style": ["图文结合", "代码案例"],
            "time_budget": "未说明",
            "difficulty_preference": "由浅入深",
        }
        system = (
            "你是学生画像分析智能体。请从学生自然语言中抽取学生画像，"
            "只输出 JSON，字段包含 major, course, goal, knowledge_base, "
            "weaknesses, learning_style, time_budget, difficulty_preference。"
        )
        user = f"课程：{state.get('course')}\n学生输入：{state.get('user_input')}"
        profile = self.llm.chat_json(system, user, fallback=fallback)
        return {"student_profile": profile}

    def _retriever_agent(self, state: LearningState) -> dict[str, Any]:
        query = " ".join(
            [
                state.get("course", ""),
                state.get("user_input", ""),
                json.dumps(state.get("student_profile", {}), ensure_ascii=False),
            ]
        )
        try:
            context = self.store.search(query, top_k=5, course=state.get("course"))
        except TypeError:
            context = self.store.search(query, top_k=5)
        return {"course_context": context}

    def _supervisor_agent(self, state: LearningState) -> dict[str, Any]:
        tasks = [
            {
                **task,
                "course": state.get("course"),
                "student_profile": state.get("student_profile", {}),
            }
            for task in RESOURCE_TASKS
        ]
        return {"tasks": tasks}

    def _assign_resource_workers(self, state: LearningState) -> list[Send]:
        return [
            Send(
                task["node"],
                {
                    "task": task,
                    "course": state.get("course"),
                    "user_input": state.get("user_input"),
                    "student_profile": state.get("student_profile", {}),
                    "course_context": state.get("course_context", []),
                },
            )
            for task in state.get("tasks", [])
        ]

    def _explanation_agent(self, state: dict[str, Any]) -> dict[str, Any]:
        return self._resource_worker(state)

    def _quiz_agent(self, state: dict[str, Any]) -> dict[str, Any]:
        return self._resource_worker(state)

    def _code_agent(self, state: dict[str, Any]) -> dict[str, Any]:
        return self._resource_worker(state)

    def _resource_worker(self, state: dict[str, Any]) -> dict[str, Any]:
        task = state["task"]
        content = self._generate_resource(
            task=task,
            profile=state.get("student_profile", {}),
            context=state.get("course_context", []),
            user_input=state.get("user_input", ""),
        )
        resource: dict[str, Any] = {
            "type": task["type"],
            "title": task["title"],
            "agent": task["role"],
            "modality": task.get("modality"),
            "content": content,
        }
        if task["type"] == "quiz":
            resource["quiz"] = self._generate_quiz_items(
                course=state.get("course", ""),
                profile=state.get("student_profile", {}),
                context=state.get("course_context", []),
                user_input=state.get("user_input", ""),
            )
        return {
            "resources": [resource]
        }

    def _planner_agent(self, state: LearningState) -> dict[str, Any]:
        fallback = _fallback_learning_path(
            course=state.get("course", "课程"),
            profile=state.get("student_profile", {}),
            resources=state.get("resources", []),
        )
        system = (
            "你是学习路径规划智能体。请只输出 JSON，不要输出 Markdown。"
            "JSON 必须包含 title 和 stages。stages 必须是 4 个阶段。"
            "每个阶段必须包含 name, goal, action, resources, time。"
            "name 必须是具体学习任务名，禁止使用“学习阶段”“阶段一”“阶段二”“诊断”“练习”“实践”等模板词。"
            "goal 必须结合学生薄弱点、课程主题和已生成资源，写成可执行目标。"
            "action 写学生下一步具体做什么。resources 只能从已生成资源标题中选择。time 给出建议时长。"
        )
        user = (
            f"学生画像：{json.dumps(state.get('student_profile', {}), ensure_ascii=False)}\n"
            f"课程资料：{_format_context(state.get('course_context', []))}\n"
            f"已生成资源：{json.dumps(_resource_brief(state.get('resources', [])), ensure_ascii=False)}\n"
            "请生成适合该学生的学习顺序：先理解，再练习，再实操，再复盘。"
        )
        path = self.llm.chat_json(system, user, fallback=fallback)
        path = _normalize_learning_path(
            path=path,
            course=state.get("course", "课程"),
            profile=state.get("student_profile", {}),
            resources=state.get("resources", []),
        )
        return {"learning_path": path}

    def _summary_agent(self, state: LearningState) -> dict[str, Any]:
        profile = state.get("student_profile", {})
        resources = state.get("resources", [])
        path = state.get("learning_path", {})
        if hasattr(self.store, "save_learning_result"):
            self.store.save_learning_result(
                student_id=state.get("student_id", "demo-student"),
                course=state.get("course", "机器学习"),
                profile=profile,
                resources=resources,
                learning_path=path,
            )
        answer = (
            f"已为你生成《{state.get('course')}》个性化学习方案。\n\n"
            f"画像摘要：{profile.get('knowledge_base', '待评估')}；"
            f"薄弱点：{', '.join(profile.get('weaknesses', [])) or '待诊断'}。\n\n"
            f"本次生成 {len(resources)} 类资源："
            f"{'、'.join(resource['title'] for resource in resources)}。\n"
            "资源由画像、检索、监督调度、讲解、题目、代码实操和路径规划等智能体协同完成。\n"
            f"学习路径：{path.get('title', '个性化学习路径')}。"
        )
        return {"final_answer": answer}

    def _generate_resource(
        self,
        task: dict[str, Any],
        profile: dict[str, Any],
        context: list[dict[str, Any]],
        user_input: str,
    ) -> str:
        system = (
            f"你是{task['role']}。请基于学生画像和课程知识库生成“{task['title']}”。"
            "内容要个性化、结构清晰、可直接给学生使用。"
            f"智能体职责边界：{task.get('boundary')} "
            "请使用规范 Markdown 输出：表格必须使用 Markdown 表格语法；"
            "公式必须使用 LaTeX，行内公式用 $...$，独立公式用 $$...$$；"
            "如需代码，必须放在带语言标识的 fenced code block 中。"
            f"{_resource_contract(task['type'])}"
        )
        user = (
            f"资源类型：{task['type']}\n"
            f"学生输入：{user_input}\n"
            f"学生画像：{json.dumps(profile, ensure_ascii=False)}\n"
            f"课程知识库片段：{_format_context(context)}"
        )
        if self.llm.is_mock:
            return _mock_resource(task["type"], task["title"], profile, context)
        return self.llm.chat(system, user, temperature=0.5)

    def _generate_quiz_items(
        self,
        course: str,
        profile: dict[str, Any],
        context: list[dict[str, Any]],
        user_input: str,
        level: int = 1,
    ) -> list[dict[str, Any]]:
        fallback = {
            "quiz": _build_quiz_items(
                profile=profile,
                user_input=f"{course}\n{user_input}",
                level=level,
            )
        }
        if self.llm.is_mock:
            return fallback["quiz"]

        system = (
            "你是题目生成智能体，只负责生成可在线作答、可自动评分的结构化练习题。"
            "请严格输出 JSON，不要输出 Markdown。JSON 格式为："
            "{\"quiz\":[{\"id\":\"q1\",\"type\":\"single_choice|multiple_choice|true_false|short_answer\","
            "\"type_label\":\"单选题\",\"difficulty\":\"入门|基础|进阶|挑战\","
            "\"question\":\"题干\",\"options\":[\"选项1\"],\"answer\":\"A 或 ABC 或文本答案\","
            "\"keywords\":[\"关键词\"],\"explanation\":\"解析\",\"knowledge_point\":\"知识点\",\"score\":15}]}"
            "必须生成 6 题，题型包含单选、多选、判断、简答、应用分析、代码/SQL阅读。"
            "题目必须紧扣课程名、学生需求和课程资料，不得沿用其他课程题目。"
        )
        user = (
            f"课程：{course}\n"
            f"难度轮次：第 {level} 套\n"
            f"学生画像：{json.dumps(profile, ensure_ascii=False)}\n"
            f"学生需求：{user_input}\n"
            f"课程资料片段：{_format_context(context)}"
        )
        data = self.llm.chat_json(system, user, fallback=fallback, temperature=0.35)
        quiz = data.get("quiz") if isinstance(data, dict) else None
        normalized = _normalize_quiz_items(quiz)
        return normalized or fallback["quiz"]


def _format_context(context: list[dict[str, Any]]) -> str:
    if not context:
        return "暂无课程知识库内容，请基于通用机器学习知识生成。"
    return "\n".join(
        f"[{item['filename']}#{item['chunk_index']}] {item['text']}"
        for item in context
    )


def _resource_brief(resources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "type": resource.get("type"),
            "title": resource.get("title"),
            "agent": resource.get("agent"),
            "modality": resource.get("modality"),
        }
        for resource in resources
    ]


def _fallback_learning_path(course: str, profile: dict[str, Any], resources: list[dict[str, Any]]) -> dict[str, Any]:
    resource_titles = [resource.get("title", "") for resource in resources if resource.get("title")]
    weaknesses = _join_profile_items(profile.get("weaknesses")) or "当前薄弱知识点"
    style = _join_profile_items(profile.get("learning_style")) or "适合自己的学习方式"
    time_budget = profile.get("time_budget") or "本周学习时间"
    return {
        "title": f"{course}个性化学习路径",
        "stages": [
            {
                "name": f"建立{course}核心概念框架",
                "goal": f"围绕{weaknesses}先搭建概念地图，避免直接进入题目造成理解断层。",
                "action": f"先阅读讲解文档的学习目标、先修补洞和核心概念部分，用{style}记录关键公式或流程。",
                "resources": _pick_resources(resource_titles, ["讲解", "文档"], fallback=resource_titles[:1]),
                "time": _stage_time(time_budget, 0),
            },
            {
                "name": "完成分层练习并定位错因",
                "goal": "用选择题、判断题和简答题检查概念理解，找出仍然混淆的考点。",
                "action": "完成个性化练习题，提交后重点查看错题分析，把错因归类为概念不清、公式不会用或场景判断错误。",
                "resources": _pick_resources(resource_titles, ["练习", "题"], fallback=resource_titles[1:2]),
                "time": _stage_time(time_budget, 1),
            },
            {
                "name": "用代码案例验证模型流程",
                "goal": "把讲解中的概念迁移到可运行代码，观察输入、训练、评估输出之间的关系。",
                "action": "运行代码实操案例，修改一个参数或数据字段，比较指标变化并记录现象。",
                "resources": _pick_resources(resource_titles, ["代码", "案例", "实操"], fallback=resource_titles[2:3]),
                "time": _stage_time(time_budget, 2),
            },
            {
                "name": "复盘薄弱点并安排下一轮提升",
                "goal": "把错题、代码现象和讲解文档重新对应，形成下一次学习的重点清单。",
                "action": "回看错题分析和代码输出，总结 3 个已掌握点、2 个未掌握点，并继续追问学习问答。",
                "resources": resource_titles[:3],
                "time": _stage_time(time_budget, 3),
            },
        ],
    }


def _normalize_learning_path(
    path: dict[str, Any],
    course: str,
    profile: dict[str, Any],
    resources: list[dict[str, Any]],
) -> dict[str, Any]:
    fallback = _fallback_learning_path(course, profile, resources)
    stages = path.get("stages") if isinstance(path, dict) else None
    if not isinstance(stages, list) or not stages:
        return fallback

    normalized = []
    for index in range(4):
        fallback_stage = fallback["stages"][index]
        stage = stages[index] if index < len(stages) and isinstance(stages[index], dict) else {}
        name = str(stage.get("name") or "").strip()
        if _is_generic_stage_name(name):
            name = fallback_stage["name"]
        normalized.append(
            {
                "name": name,
                "goal": str(stage.get("goal") or fallback_stage["goal"]).strip(),
                "action": str(stage.get("action") or fallback_stage["action"]).strip(),
                "resources": stage.get("resources") if isinstance(stage.get("resources"), list) else fallback_stage["resources"],
                "time": str(stage.get("time") or fallback_stage["time"]).strip(),
            }
        )
    return {
        "title": str(path.get("title") or fallback["title"]).strip(),
        "stages": normalized,
    }


def _is_generic_stage_name(name: str) -> bool:
    cleaned = name.replace(" ", "")
    return not cleaned or cleaned in {"学习阶段", "阶段", "阶段一", "阶段二", "阶段三", "阶段四", "诊断", "练习", "实践"}


def _pick_resources(titles: list[str], keywords: list[str], fallback: list[str]) -> list[str]:
    picked = [title for title in titles if any(keyword in title for keyword in keywords)]
    return picked or fallback or titles[:1]


def _join_profile_items(value: Any) -> str:
    if isinstance(value, list):
        return "、".join(str(item) for item in value if item)
    return str(value or "")


def _stage_time(time_budget: Any, index: int) -> str:
    text = str(time_budget or "")
    match = re.search(r"(\d+(?:\.\d+)?)", text)
    if not match:
        return ["约 30 分钟", "约 40 分钟", "约 60 分钟", "约 30 分钟"][index]
    total = float(match.group(1))
    ratios = [0.25, 0.25, 0.35, 0.15]
    hours = max(0.5, round(total * ratios[index], 1))
    return f"约 {hours:g} 小时"


def _resource_contract(resource_type: str) -> str:
    contracts = {
        "explanation_doc": (
            "输出结构固定为：学习目标、先修补洞、核心概念、关键公式、常见误区、5分钟复盘。"
            "不要输出完整代码块。"
        ),
        "quiz": (
            "输出至少包含单选题、多选题、判断题、简答题、应用题和代码阅读题；"
            "每题标注难度、考查点、答案和解析。"
        ),
        "code_case": (
            "输出结构固定为：实操目标、运行环境、任务步骤、完整代码、预期输出、改造挑战。"
            "概念解释不超过三句话。"
        ),
    }
    return contracts.get(resource_type, "")


def _normalize_quiz_items(raw_items: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_items, list):
        return []
    allowed_types = {"single_choice", "multiple_choice", "true_false", "short_answer"}
    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(raw_items[:6], start=1):
        if not isinstance(item, dict):
            continue
        item_type = item.get("type") if item.get("type") in allowed_types else "short_answer"
        options = item.get("options") if isinstance(item.get("options"), list) else []
        if item_type in {"single_choice", "multiple_choice", "true_false"} and not options:
            continue
        normalized.append(
            {
                "id": str(item.get("id") or f"q{index}"),
                "type": item_type,
                "type_label": str(item.get("type_label") or _quiz_type_label(item_type)),
                "difficulty": str(item.get("difficulty") or "基础"),
                "question": str(item.get("question") or ""),
                "options": [str(option) for option in options],
                "answer": str(item.get("answer") or ""),
                "keywords": [str(keyword) for keyword in item.get("keywords", [])]
                if isinstance(item.get("keywords"), list)
                else [],
                "explanation": str(item.get("explanation") or ""),
                "knowledge_point": str(item.get("knowledge_point") or ""),
                "score": int(item.get("score") or 15),
            }
        )
    return normalized if len(normalized) >= 4 else []


def _quiz_type_label(item_type: str) -> str:
    labels = {
        "single_choice": "单选题",
        "multiple_choice": "多选题",
        "true_false": "判断题",
        "short_answer": "简答题",
    }
    return labels.get(item_type, "简答题")


def _big_data_quiz_items(level: int = 1) -> list[dict[str, Any]]:
    label = "入门" if level == 1 else ("挑战" if level == 2 else "高阶挑战")
    return [
        {
            "id": f"bd_l{level}_q1",
            "type": "single_choice",
            "type_label": "单选题",
            "difficulty": label,
            "question": "在 Hadoop 生态中，HDFS 最核心的作用是什么？",
            "options": ["分布式文件存储", "关系型事务处理", "前端页面渲染", "模型参数训练"],
            "answer": "A",
            "explanation": "HDFS 负责把大文件切分为块并分布式存储在集群节点上，适合高吞吐批处理场景。",
            "knowledge_point": "HDFS 分布式存储",
            "score": 15,
        },
        {
            "id": f"bd_l{level}_q2",
            "type": "multiple_choice",
            "type_label": "多选题",
            "difficulty": "基础" if level == 1 else label,
            "question": "设计离线大数据处理链路时，以下哪些组件或环节常见？",
            "options": ["数据采集", "HDFS/对象存储", "Spark/Hive 计算", "浏览器 CSS 动画"],
            "answer": "ABC",
            "explanation": "典型离线链路包含采集、存储、计算和结果服务；CSS 动画不属于大数据处理链路核心环节。",
            "knowledge_point": "离线数据处理架构",
            "score": 20,
        },
        {
            "id": f"bd_l{level}_q3",
            "type": "true_false",
            "type_label": "判断题",
            "difficulty": "基础",
            "question": "YARN 的主要职责是进行集群资源管理和任务调度。",
            "options": ["正确", "错误"],
            "answer": "A",
            "explanation": "YARN 负责统一管理 CPU、内存等资源，并为 MapReduce、Spark 等计算任务分配资源。",
            "knowledge_point": "YARN 资源调度",
            "score": 15,
        },
        {
            "id": f"bd_l{level}_q4",
            "type": "short_answer",
            "type_label": "简答题",
            "difficulty": "进阶",
            "question": "请简要说明 ODS、DWD、DWS、ADS 四层数仓分层各自的作用。",
            "answer": "ODS 保留原始数据，DWD 做明细清洗和规范化，DWS 面向主题进行汇总，ADS 面向报表和应用输出指标结果。",
            "keywords": ["ODS", "DWD", "DWS", "ADS", "原始", "明细", "汇总", "应用"],
            "explanation": "这道题考查数仓分层的边界，重点是能说清每一层的数据粒度和服务对象。",
            "knowledge_point": "数据仓库分层",
            "score": 20,
        },
        {
            "id": f"bd_l{level}_q5",
            "type": "short_answer",
            "type_label": "应用分析题",
            "difficulty": "进阶" if level == 1 else label,
            "question": "如果要统计电商网站每天的用户访问量、下单量和支付转化率，你会如何设计从日志采集到报表输出的链路？",
            "answer": "可按采集日志、写入 HDFS 或消息队列、清洗到 ODS/DWD、用 Spark 或 Hive 聚合到 DWS、最终生成 ADS 指标表供报表查询的流程设计。",
            "keywords": ["采集", "HDFS", "清洗", "ODS", "DWD", "Spark", "Hive", "DWS", "ADS", "报表"],
            "explanation": "应用题重点看是否能把业务指标拆成采集、存储、计算、分层建模和服务输出几个步骤。",
            "knowledge_point": "业务场景架构设计",
            "score": 15,
        },
        {
            "id": f"bd_l{level}_q6",
            "type": "short_answer",
            "type_label": "代码/SQL阅读题",
            "difficulty": "挑战",
            "question": "阅读 SQL：`SELECT dt, count(distinct user_id) AS uv FROM dwd_log GROUP BY dt;` 这段 SQL 计算的是什么指标？它通常适合落在哪一层结果表？",
            "answer": "它按日期统计去重用户数 UV，通常可作为 DWS 汇总指标或进一步加工到 ADS 报表指标表。",
            "keywords": ["dt", "count distinct", "user_id", "UV", "DWS", "ADS"],
            "explanation": "这道题把 SQL 聚合逻辑和数仓分层结合起来，考查能否从代码读出业务指标。",
            "knowledge_point": "SQL 聚合与指标层",
            "score": 15,
        },
    ]


def _build_quiz_items(profile: dict[str, Any], user_input: str, level: int = 1) -> list[dict[str, Any]]:
    topic_text = f"{profile.get('course', '')} {user_input}".lower()
    if any(keyword in topic_text for keyword in ["大数据", "hadoop", "hdfs", "spark", "yarn", "数仓"]):
        return _big_data_quiz_items(level=level)
    weakness = "、".join(profile.get("weaknesses", ["模型评估"]))
    if level >= 2:
        label = "挑战" if level == 2 else "高阶挑战"
        return [
            {
                "id": f"l{level}_q1",
                "type": "single_choice",
                "type_label": "单选题",
                "difficulty": label,
                "question": "在类别极不平衡的二分类任务中，单看 Accuracy 可能产生什么问题？",
                "options": ["无法训练模型", "掩盖少数类识别差的问题", "一定导致过拟合", "让召回率恒等于 1"],
                "answer": "B",
                "explanation": "类别不平衡时，模型即使总预测多数类也可能有较高 Accuracy，但少数类召回很差。",
                "knowledge_point": "类别不平衡与指标选择",
                "score": 15,
            },
            {
                "id": f"l{level}_q2",
                "type": "multiple_choice",
                "type_label": "多选题",
                "difficulty": label,
                "question": "想提升少数类召回率时，可以考虑哪些方向？",
                "options": ["调整分类阈值", "重采样或类别权重", "增加相关特征", "删除所有少数类样本"],
                "answer": "ABC",
                "explanation": "阈值、样本分布和特征质量都会影响少数类召回；删除少数类会让问题更严重。",
                "knowledge_point": "召回率优化",
                "score": 20,
            },
            {
                "id": f"l{level}_q3",
                "type": "true_false",
                "type_label": "判断题",
                "difficulty": label,
                "question": "F1-score 是 Precision 和 Recall 的调和平均，因此适合在二者都重要时使用。",
                "options": ["正确", "错误"],
                "answer": "A",
                "explanation": "F1 同时考虑查准和查全，适合 Precision 与 Recall 都需要关注的场景。",
                "knowledge_point": "F1-score",
                "score": 15,
            },
            {
                "id": f"l{level}_q4",
                "type": "short_answer",
                "type_label": "简答题",
                "difficulty": label,
                "question": "为什么降低分类阈值可能提高 Recall，但可能降低 Precision？",
                "answer": "降低阈值会让更多样本被判为正类，找回更多真实正类，但也可能带来更多误报。",
                "keywords": ["阈值", "正类", "找回", "误报", "Precision"],
                "explanation": "核心是理解阈值移动会改变正类判定数量，从而影响 FP 和 FN。",
                "knowledge_point": "阈值与指标权衡",
                "score": 20,
            },
            {
                "id": f"l{level}_q5",
                "type": "short_answer",
                "type_label": "应用分析题",
                "difficulty": label,
                "question": f"针对“{weakness}”这个短板，请设计一个复盘步骤，说明先看哪个指标、再检查什么数据问题。",
                "answer": "先看混淆矩阵和 Recall/Precision，再检查类别分布、错分样本、阈值和特征质量。",
                "keywords": ["混淆矩阵", "Recall", "Precision", "类别分布", "错分样本", "阈值", "特征"],
                "explanation": "高阶题更关注排查路径，而不是单个指标定义。",
                "knowledge_point": "模型诊断流程",
                "score": 15,
            },
            {
                "id": f"l{level}_q6",
                "type": "short_answer",
                "type_label": "代码阅读题",
                "difficulty": label,
                "question": "如果你把 `predict_proba` 的正类阈值从 0.5 改为 0.3，分类报告中哪些指标最可能发生变化？",
                "answer": "Precision、Recall、F1 和混淆矩阵都会变化，因为正类预测数量发生改变。",
                "keywords": ["Precision", "Recall", "F1", "混淆矩阵", "正类", "阈值"],
                "explanation": "阈值影响预测标签，因此会改变 TP、FP、FN、TN。",
                "knowledge_point": "predict_proba 阈值调整",
                "score": 15,
            },
        ]
    return [
        {
            "id": "q1",
            "type": "single_choice",
            "type_label": "单选题",
            "difficulty": "入门",
            "question": "逻辑回归通常用于哪类机器学习任务？",
            "options": ["聚类", "分类", "排序", "降维"],
            "answer": "B",
            "explanation": "逻辑回归通过 sigmoid 输出正类概率，常用于二分类或多分类任务。",
            "knowledge_point": "逻辑回归任务类型",
            "score": 15,
        },
        {
            "id": "q2",
            "type": "multiple_choice",
            "type_label": "多选题",
            "difficulty": "基础",
            "question": "评价分类模型时，以下哪些指标常用？",
            "options": ["Accuracy", "Recall", "F1-score", "HTML"],
            "answer": "ABC",
            "explanation": "Accuracy、Recall、F1-score 都是分类评估指标，HTML 不是模型评价指标。",
            "knowledge_point": "分类评估指标",
            "score": 20,
        },
        {
            "id": "q3",
            "type": "true_false",
            "type_label": "判断题",
            "difficulty": "基础",
            "question": "学习率越大，梯度下降训练一定越快且越稳定。",
            "options": ["正确", "错误"],
            "answer": "B",
            "explanation": "学习率过大可能导致震荡甚至不收敛；学习率过小则收敛较慢。",
            "knowledge_point": "学习率与收敛",
            "score": 15,
        },
        {
            "id": "q4",
            "type": "short_answer",
            "type_label": "简答题",
            "difficulty": "进阶",
            "question": "请用一句话解释准确率和召回率的区别。",
            "answer": "准确率关注整体预测正确比例，召回率关注真实正类被找回的比例。",
            "keywords": ["准确率", "整体", "召回率", "正类", "找回"],
            "explanation": "简答题按关键词给分，重点是能区分整体正确率和正类覆盖能力。",
            "knowledge_point": "Accuracy 与 Recall",
            "score": 20,
        },
        {
            "id": "q5",
            "type": "short_answer",
            "type_label": "应用分析题",
            "difficulty": "进阶",
            "question": f"如果你的薄弱点是“{weakness}”，你会优先观察分类报告中的哪个指标？为什么？",
            "answer": "若关注漏判，应优先看召回率；若关注误报，应看精确率；综合比较可看 F1-score。",
            "keywords": ["召回率", "精确率", "F1", "漏判", "误报"],
            "explanation": "这题考查能否根据业务代价选择合适指标，而不是死记指标名称。",
            "knowledge_point": "指标选择",
            "score": 15,
        },
        {
            "id": "q6",
            "type": "short_answer",
            "type_label": "代码阅读题",
            "difficulty": "挑战",
            "question": "`classification_report(y_test, pred)` 输出某一类 recall 很低，可能说明什么？",
            "answer": "说明该类真实样本中被模型正确找回的比例低，可能存在类别不平衡、阈值不合适或特征不足。",
            "keywords": ["recall", "找回", "类别不平衡", "阈值", "特征"],
            "explanation": "代码阅读题关注你能否把指标输出解释成模型问题定位线索。",
            "knowledge_point": "分类报告解读",
            "score": 15,
        },
    ]


def _mock_resource(
    resource_type: str,
    title: str,
    profile: dict[str, Any],
    context: list[dict[str, Any]],
) -> str:
    weakness = "、".join(profile.get("weaknesses", ["基础概念"]))
    if resource_type == "explanation_doc":
        return (
            f"# {title}\n\n"
            f"你的当前薄弱点是：{weakness}。建议先把机器学习理解为“从数据中总结规律”。\n\n"
            "## 学习目标\n"
            "理解逻辑回归如何把特征转成分类概率，并能说清准确率、召回率和 F1 值的适用场景。\n\n"
            "## 先修补洞\n"
            "- 概率：$P(y=1|x)$ 表示样本属于正类的可能性。\n"
            "- 线性函数：$w\\cdot x+b$ 把多个特征合成一个分数。\n\n"
            "## 核心概念\n"
            "1. 监督学习：使用带标签样本训练模型。\n"
            "2. 分类任务：预测样本属于哪个类别。\n"
            "3. 逻辑回归：用 sigmoid 函数输出属于正类的概率。\n\n"
            "## 常见误区\n"
            "逻辑回归名字里有“回归”，但常用于分类；准确率高也不代表少数类识别一定好。\n\n"
            "## 学习建议\n"
            "先阅读讲解文档建立框架，再用练习题检查概念，最后通过代码实操验证理解。"
        )
    if resource_type == "quiz":
        return (
            "# 个性化练习题\n\n"
            "| 类型 | 难度 | 题目 | 答案 | 解析 |\n"
            "| --- | --- | --- | --- | --- |\n"
            "| 单选题 | 入门 | 逻辑回归通常用于哪类任务？A. 聚类 B. 分类 C. 排序 D. 压缩 | B | sigmoid 输出正类概率，常配合阈值做分类。 |\n"
            "| 多选题 | 基础 | 评价分类模型可使用哪些指标？A. Accuracy B. Recall C. F1 D. SQL | A/B/C | 三者都可衡量分类表现，侧重点不同。 |\n"
            "| 判断题 | 基础 | 学习率越大，模型训练一定越快且越稳定。 | 错误 | 学习率过大可能震荡甚至不收敛。 |\n"
            "| 简答题 | 进阶 | 解释准确率和召回率的区别。 | 略 | 准确率看整体预测正确比例，召回率关注正类被找回的比例。 |\n"
            "| 应用题 | 进阶 | 医疗筛查中漏诊代价很高，应优先关注哪个指标？ | 召回率 | 漏诊对应假阴性，应提高正类召回。 |\n"
            "| 代码阅读题 | 挑战 | 看到 `classification_report` 中某类 recall 很低，应如何排查？ | 检查类别不平衡、阈值、特征和样本质量 | 这类题考查指标解释，不要求写完整项目代码。 |"
        )
    if resource_type == "code_case":
        return (
            "# 代码实操案例：鸢尾花分类\n\n"
            "## 实操目标\n"
            "完成一个可运行的逻辑回归二分类实验，并输出分类评估报告。\n\n"
            "## 运行环境\n"
            "`python >= 3.10`，安装 `scikit-learn`。\n\n"
            "## 完整代码\n"
            "```python\n"
            "from sklearn.datasets import load_iris\n"
            "from sklearn.model_selection import train_test_split\n"
            "from sklearn.linear_model import LogisticRegression\n"
            "from sklearn.metrics import classification_report\n\n"
            "iris = load_iris()\n"
            "X = iris.data\n"
            "y = (iris.target == 0).astype(int)\n"
            "X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)\n"
            "model = LogisticRegression(max_iter=200)\n"
            "model.fit(X_train, y_train)\n"
            "pred = model.predict(X_test)\n"
            "print(classification_report(y_test, pred))\n"
            "```\n\n"
            "## 预期输出\n"
            "终端会打印 precision、recall、f1-score 和 support。\n\n"
            "## 改造挑战\n"
            "把 `test_size` 改成 0.3，再比较评估结果是否稳定。"
        )
    return f"# {title}\n\n基于知识库片段数量 {len(context)} 生成的个性化资源。"
