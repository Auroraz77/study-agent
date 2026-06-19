CREATE EXTENSION IF NOT EXISTS vector;

-- SQLAlchemy 会自动创建完整表结构；本文件用于答辩说明数据库设计。

-- 课程表：courses
-- 文件元数据表：course_files
-- 知识切片表：knowledge_chunks
-- 向量表：knowledge_embeddings
-- 学生画像表：student_profiles
-- 生成资源表：generated_resources
-- 学习路径表：learning_paths
-- 学习行为表：learning_events
