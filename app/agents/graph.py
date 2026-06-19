from __future__ import annotations

import json
from html import escape
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
        "type": "mindmap",
        "title": "知识点思维导图",
        "role": "思维导图智能体",
        "node": "mindmap_agent",
        "modality": "diagram",
        "boundary": "只负责输出 Mermaid mindmap 层级关系；不得包含 Python 案例、练习题或长段解释。",
    },
    {
        "type": "reading_pack",
        "title": "拓展阅读材料",
        "role": "拓展阅读智能体",
        "node": "reading_agent",
        "modality": "reading",
        "boundary": "只负责阅读路线、关键词、资料摘要和阅读任务；不得生成代码案例或测验题。",
    },
    {
        "type": "multimodal_animation",
        "title": "多模态教学动画",
        "role": "多模态教学智能体",
        "node": "multimodal_agent",
        "modality": "interactive_animation",
        "boundary": "负责生成教学分镜、旁白文案和可播放动画；不得替代讲解文档或代码实操。",
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
        builder.add_node("mindmap_agent", self._mindmap_agent)
        builder.add_node("reading_agent", self._reading_agent)
        builder.add_node("multimodal_agent", self._multimodal_agent)
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
                "mindmap_agent",
                "reading_agent",
                "multimodal_agent",
                "code_agent",
            ],
        )
        builder.add_edge("explanation_agent", "planner_agent")
        builder.add_edge("quiz_agent", "planner_agent")
        builder.add_edge("mindmap_agent", "planner_agent")
        builder.add_edge("reading_agent", "planner_agent")
        builder.add_edge("multimodal_agent", "planner_agent")
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

    def _mindmap_agent(self, state: dict[str, Any]) -> dict[str, Any]:
        return self._resource_worker(state)

    def _reading_agent(self, state: dict[str, Any]) -> dict[str, Any]:
        return self._resource_worker(state)

    def _multimodal_agent(self, state: dict[str, Any]) -> dict[str, Any]:
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
        if task["type"] == "multimodal_animation":
            resource["media"] = _build_animation_media(
                course=state.get("course", "课程"),
                profile=state.get("student_profile", {}),
            )
        return {
            "resources": [resource]
        }

    def _planner_agent(self, state: LearningState) -> dict[str, Any]:
        fallback = {
            "title": f"{state.get('course', '课程')}个性化学习路径",
            "stages": [
                {"name": "诊断", "goal": "明确基础与薄弱点", "resources": ["个性化讲解文档"]},
                {"name": "理解", "goal": "掌握核心概念", "resources": ["知识点思维导图"]},
                {"name": "练习", "goal": "通过题目巩固", "resources": ["个性化练习题"]},
                {"name": "拓展", "goal": "通过阅读建立知识外延", "resources": ["拓展阅读材料"]},
                {"name": "视听", "goal": "用动画建立直观理解", "resources": ["多模态教学动画"]},
                {"name": "实践", "goal": "完成代码案例", "resources": ["代码实操案例"]},
            ],
        }
        system = "你是学习路径规划智能体。请只输出 JSON，包含 title 和 stages。"
        user = (
            f"学生画像：{json.dumps(state.get('student_profile', {}), ensure_ascii=False)}\n"
            f"课程资料：{_format_context(state.get('course_context', []))}\n"
            f"已生成资源：{json.dumps(state.get('resources', []), ensure_ascii=False)}"
        )
        path = self.llm.chat_json(system, user, fallback=fallback)
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
            "资源由画像、检索、监督调度、讲解、题目、思维导图、拓展阅读、多模态教学、代码实操和路径规划等智能体协同完成。\n"
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


def _format_context(context: list[dict[str, Any]]) -> str:
    if not context:
        return "暂无课程知识库内容，请基于通用机器学习知识生成。"
    return "\n".join(
        f"[{item['filename']}#{item['chunk_index']}] {item['text']}"
        for item in context
    )


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
        "mindmap": (
            "只输出一个 Mermaid mindmap fenced code block。节点使用课程知识点短语，"
            "禁止出现 Python、sklearn、代码、题目、答案等内容。"
        ),
        "reading_pack": (
            "输出结构固定为：阅读路线、核心关键词、推荐阅读清单、每篇阅读目的、读后产出。"
            "不要生成练习题或代码。"
        ),
        "multimodal_animation": (
            "输出结构固定为：动画目标、分镜脚本、旁白文案、交互提示。"
            "动画本体由系统工具生成，不要输出 HTML 或 Python 代码。"
        ),
        "code_case": (
            "输出结构固定为：实操目标、运行环境、任务步骤、完整代码、预期输出、改造挑战。"
            "概念解释不超过三句话。"
        ),
    }
    return contracts.get(resource_type, "")


def _build_animation_media(course: str, profile: dict[str, Any]) -> dict[str, str]:
    weaknesses = "、".join(profile.get("weaknesses", ["核心概念"]))
    title = escape(f"{course} 动画演示")
    subtitle = escape(f"围绕薄弱点：{weaknesses}")
    html = f"""
<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8" />
<style>
  body {{
    margin: 0;
    min-height: 100vh;
    display: grid;
    place-items: center;
    background: #f8fafc;
    color: #172033;
    font-family: "Microsoft YaHei", Arial, sans-serif;
  }}
  .scene {{
    width: min(900px, 96vw);
    padding: 24px;
  }}
  h1 {{ margin: 0 0 6px; font-size: 24px; }}
  p {{ margin: 0 0 18px; color: #667085; }}
  .stage {{
    position: relative;
    height: 260px;
    border: 1px solid #d9dee7;
    border-radius: 8px;
    background:
      linear-gradient(90deg, transparent 49.5%, #94a3b8 49.5%, #94a3b8 50.5%, transparent 50.5%),
      linear-gradient(180deg, transparent 49.5%, #94a3b8 49.5%, #94a3b8 50.5%, transparent 50.5%),
      #fff;
    overflow: hidden;
  }}
  .curve {{
    position: absolute;
    left: 8%;
    right: 8%;
    top: 52%;
    height: 4px;
    border-radius: 999px;
    background: #2563eb;
    transform: rotate(-18deg);
  }}
  .point {{
    position: absolute;
    width: 18px;
    height: 18px;
    border-radius: 50%;
    animation: pulse 2.4s ease-in-out infinite;
  }}
  .positive {{ background: #0f766e; }}
  .negative {{ background: #be123c; }}
  .p1 {{ left: 22%; top: 66%; animation-delay: .1s; }}
  .p2 {{ left: 32%; top: 58%; animation-delay: .4s; }}
  .p3 {{ left: 43%; top: 50%; animation-delay: .7s; }}
  .p4 {{ left: 58%; top: 40%; animation-delay: 1s; }}
  .p5 {{ left: 70%; top: 32%; animation-delay: 1.3s; }}
  .p6 {{ left: 76%; top: 45%; animation-delay: 1.6s; }}
  .caption {{
    position: absolute;
    left: 24px;
    bottom: 20px;
    padding: 10px 12px;
    border-radius: 8px;
    background: rgba(255, 255, 255, .92);
    border: 1px solid #d9dee7;
    font-weight: 700;
  }}
  .formula {{
    position: absolute;
    right: 22px;
    top: 18px;
    padding: 10px 12px;
    border-radius: 8px;
    background: #eef2ff;
    color: #1d4ed8;
    font-weight: 800;
  }}
  @keyframes pulse {{
    0%, 100% {{ transform: scale(1); opacity: .62; }}
    50% {{ transform: scale(1.35); opacity: 1; }}
  }}
</style>
</head>
<body>
  <main class="scene">
    <h1>{title}</h1>
    <p>{subtitle}</p>
    <section class="stage" aria-label="分类边界动画">
      <div class="curve"></div>
      <span class="point negative p1"></span>
      <span class="point negative p2"></span>
      <span class="point negative p3"></span>
      <span class="point positive p4"></span>
      <span class="point positive p5"></span>
      <span class="point positive p6"></span>
      <div class="formula">P(y=1|x)=sigmoid(w·x+b)</div>
      <div class="caption">数据点被决策边界分开，模型输出属于正类的概率。</div>
    </section>
  </main>
</body>
</html>
""".strip()
    return {
        "kind": "html_animation",
        "label": "可播放教学动画",
        "html": html,
    }


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
            "先看思维导图建立框架，再看动画理解决策边界，最后用练习题检查概念。"
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
    if resource_type == "mindmap":
        return (
            "```mermaid\n"
            "mindmap\n"
            "  root((机器学习))\n"
            "    监督学习\n"
            "      分类\n"
            "        逻辑回归\n"
            "        决策边界\n"
            "      回归\n"
            "        线性回归\n"
            "    模型训练\n"
            "      损失函数\n"
            "      梯度下降\n"
            "    模型评估\n"
            "      准确率\n"
            "      召回率\n"
            "      F1值\n"
            "```"
        )
    if resource_type == "reading_pack":
        return (
            "# 拓展阅读材料\n\n"
            "## 阅读路线\n"
            "先读分类任务与概率解释，再读模型评估指标，最后读不平衡数据下的评价策略。\n\n"
            "## 核心关键词\n"
            "logistic regression、sigmoid、decision boundary、precision、recall、F1-score、class imbalance。\n\n"
            "| 材料 | 阅读目的 | 读后产出 |\n"
            "| --- | --- | --- |\n"
            "| 逻辑回归教材章节 | 建立概率分类视角 | 用自己的话解释 $P(y=1|x)$ |\n"
            "| 分类指标说明文档 | 区分准确率、精确率、召回率 | 写出三种指标适用场景 |\n"
            "| 类别不平衡案例文章 | 理解为什么准确率会误导 | 总结一个业务例子 |\n"
        )
    if resource_type == "multimodal_animation":
        return (
            "# 多模态教学动画\n\n"
            "## 动画目标\n"
            "用“数据点 + 决策边界 + 概率公式”的组合，帮助你直观看懂逻辑回归如何完成分类。\n\n"
            "## 分镜脚本\n"
            "1. 数据点按类别出现，形成两簇分布。\n"
            "2. 蓝色决策边界穿过特征空间，把两类样本分开。\n"
            "3. 右上角显示 sigmoid 概率公式，强调输出不是硬标签，而是概率。\n\n"
            "## 旁白文案\n"
            "当输入特征进入模型后，线性部分先得到一个分数；sigmoid 会把分数压缩成 0 到 1 之间的概率，再通过阈值判断类别。\n\n"
            "## 交互提示\n"
            "播放动画时观察边界两侧数据点的颜色变化，再回到练习题检查自己是否能解释 recall 与 F1。"
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
