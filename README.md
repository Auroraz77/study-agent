# LangGraph 个性化学习多智能体系统

这是一个用于赛题演示的 MVP：`Python + FastAPI + LangGraph + 通义千问 + RAG + 学生端页面`。

## 功能

- 对话式学生画像构建
- 学生注册/登录，登录后使用当前学生身份生成和查看学习数据
- 本地课程知识库上传与检索
- LangGraph 多智能体协同
- 生成 3 类个性化资源：专业课程讲解文档、不同类型练习题目、代码类实操案例
- 支持练习题在线作答、提交评分、查看答案与错题分析，并写入学习行为日志
- 资源智能体职责边界隔离：讲解文档负责概念与公式，练习题负责测评与解析，代码案例负责可运行实践
- 生成个性化学习路径
- 完整学生端工作台页面

## 多智能体分工

当前 LangGraph 流程包含画像分析、RAG 检索、监督调度、讲解生成、题目生成、代码实操、学习路径规划和总结落库等智能体节点。

资源生成阶段由监督智能体按学生画像、课程内容、知识短板和学习需求并行分发任务；每个资源智能体都有独立职责边界和输出契约，避免不同资源之间内容串台。

## 学生账号与数据隔离

系统使用 PostgreSQL `users` 表保存学生账号，密码以 PBKDF2 哈希形式保存。注册/登录成功后，前端保存 Bearer Token；`POST /api/learn` 使用当前登录用户的 `student_id`，不再由前端传入任意学生 ID。

数据中心中的学生画像、生成资源历史、学习路径历史和学习行为日志会按当前登录学生过滤。课程资料和知识库检索仍作为课程级资源展示，后续可扩展教师/管理员角色查看全班或全系统数据。

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
$env:AUTH_SECRET_KEY='一段足够长的随机密钥'
$env:FORCE_MOCK_LLM='0'
```

如果网络或代理不可用，系统会自动回退到 Mock 输出，保证演示流程不断。

## API

- `POST /api/learn`：运行多智能体学习流程
- `POST /api/auth/register`：注册学生账号
- `POST /api/auth/login`：登录并获取 Bearer Token
- `GET /api/auth/me`：获取当前登录用户
- `POST /api/db/init`：初始化 PostgreSQL 表结构和 pgvector 扩展
- `POST /api/knowledge/seed`：导入演示知识库
- `POST /api/knowledge/upload`：上传 UTF-8 文本知识库
- `POST /api/knowledge/search`：检索知识库
- `GET /api/health`：健康检查

## 数据库版本

当前版本已经接入 `PostgreSQL + pgvector + MinIO`：

- MinIO 保存 PDF/PPT/Word/TXT 等原始文件
- PostgreSQL 保存用户账号、课程、文件元数据、学生画像、生成资源、学习路径、学习事件
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
