---
name: docker-compose-python
description: Docker Compose setup for Python web apps with PostgreSQL, Redis, and health checks.
status: active
created_by: evolution
---

# Docker Compose for Python Web Apps

## When to use
When user needs Docker Compose for a Python web app (Flask/Django/FastAPI) with database and cache.

## Steps
1. Dockerfile: python:3.12-slim, venv, --no-cache-dir
2. docker-compose.yml: web, db (postgres), redis
3. healthcheck: curl -f http://localhost:5000/health
4. depends_on with condition: service_healthy

## Gotchas
- pip install fails: always use venv in Docker
- DB not ready: healthcheck + condition: service_healthy
