---
name: fastapi-sqlalchemy-alembic
description: "搭建 FastAPI + SQLAlchemy + Alembic + JWT 认证的 REST API"
status: active
created_by: evolution
---

# FastAPI + SQLAlchemy + Alembic

## When to use
用 Python 搭建 REST API，需要 ORM + 数据库迁移 + JWT 认证时。

## Steps
1. requirements.txt: fastapi, uvicorn, sqlalchemy, alembic, python-jose, passlib
2. app/database.py: create_engine + SessionLocal
3. app/models.py: ORM 模型继承 Base
4. pip install 依赖
5. alembic init alembic
6. alembic/env.py: 导入 Base.metadata
7. alembic.ini: 设置 sqlalchemy.url
8. alembic revision --autogenerate
9. alembic upgrade head
10. app/auth.py: JWT 逻辑
11. app/schemas.py: Pydantic 模型

## Pitfalls
- alembic 报错 "Can't locate revision": 检查 alembic.ini 的 url
- target_metadata is None: env.py 需导入 Base.metadata
- JWT secret: 生产环境用环境变量
