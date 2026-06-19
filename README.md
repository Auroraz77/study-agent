# LangGraph 个性化学习多智能体系统

这是一个用于赛题演示的 MVP：`Python + FastAPI + LangGraph + 通义千问 + RAG + 学生端页面`。

## 功能

- 对话式学生画像构建
- 本地课程知识库上传与检索
- LangGraph 多智能体协同
- 生成 6 类个性化资源：讲解文档、练习题、思维导图、拓展阅读材料、多模态教学动画、代码实操案例
- 资源智能体职责边界隔离：讲解不写完整代码，思维导图不混入 Python 案例，代码案例只做实操，阅读材料不夹带测验
- 多模态资源展示：前端可视化渲染思维导图，并以沙盒 iframe 展示可播放教学动画
- 生成个性化学习路径
- 完整学生端工作台页面

## 多智能体分工

当前 LangGraph 流程包含画像分析、RAG 检索、监督调度、讲解生成、题目生成、思维导图生成、拓展阅读、多模态教学、代码实操、学习路径规划和总结落库等智能体节点。

资源生成阶段由监督智能体按学生画像、课程内容、知识短板和学习需求并行分发任务；每个资源智能体都有独立职责边界和输出契约，避免不同资源之间内容串台。

多模态不只依赖“换一个多模态大模型”。本项目的 MVP 做法是：文本大模型负责分镜、旁白和教学意图，系统工具负责生成可展示的动画载体。后续可以把多模态教学智能体替换或增强为图像生成、TTS、数字人视频或视频生成模型调用。

## 启动

当前项目已创建 `.venv`，依赖已安装到 `.venv/Lib/site-packages`。

```powershell
$env:FORCE_MOCK_LLM='1'
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

浏览器访问：

```text
http://127.0.0.1:8000
```

## 使用通义千问

把 `.env.example` 复制为 `.env`，或在 PowerShell 中设置：

```powershell
$env:DASHSCOPE_API_KEY='你的 DashScope API Key'
$env:QWEN_MODEL='qwen-plus'
$env:FORCE_MOCK_LLM='0'
```

如果网络或代理不可用，系统会自动回退到 Mock 输出，保证演示流程不断。

## API

- `POST /api/learn`：运行多智能体学习流程
- `POST /api/db/init`：初始化 PostgreSQL 表结构和 pgvector 扩展
- `POST /api/knowledge/seed`：导入演示知识库
- `POST /api/knowledge/upload`：上传 UTF-8 文本知识库
- `POST /api/knowledge/search`：检索知识库
- `GET /api/health`：健康检查

## 数据库版本

当前版本已经接入 `PostgreSQL + pgvector + MinIO`：

- MinIO 保存 PDF/PPT/Word/TXT 等原始文件
- PostgreSQL 保存课程、文件元数据、学生画像、生成资源、学习路径、学习事件
- pgvector 保存知识切片向量，用于 RAG 检索

启动 PostgreSQL/pgvector：

```powershell
docker compose up -d postgres
```

初始化数据库：

```powershell
.\.venv\Scripts\python.exe -c "from app.db.database import init_db; init_db(); print('db initialized')"
```

或者启动后调用接口：

```text
POST http://127.0.0.1:8000/api/db/init
```

上传资料后的入库流程：

```text
前端上传文件
  ↓
原文件保存到 MinIO learning-bucket
  ↓
文件元数据写入 course_files
  ↓
UTF-8 文本解析为知识切片
  ↓
知识切片写入 knowledge_chunks
  ↓
切片向量写入 knowledge_embeddings
```
