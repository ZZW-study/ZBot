FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV UV_LINK_MODE=copy

WORKDIR /app

RUN pip install --no-cache-dir uv

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen

COPY . .

# 默认启动后端服务（uvicorn）
# 前端可通过 start.py 或 docker-compose 单独启动
# 使用 start.py 启动完整服务（后端 + 前端）:
#   docker run -p 8000:8000 -p 5173:5173 zbot python start.py
EXPOSE 8000

CMD ["uv", "run", "uvicorn", "ZBot.backend.app:app", "--host", "0.0.0.0", "--port", "8000"]