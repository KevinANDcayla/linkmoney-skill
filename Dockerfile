FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY api/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY api/ .
# 数据目录必须放在 /data，因为 server.py 用 parent.parent 解析到 /
COPY data/ /data/

EXPOSE 8765

# 多 worker 进程：双倍 CPU 利用率 + 突破 Python GIL 单进程限制
# SQLite 用 WAL 模式，多进程并发读写安全
# WEB_CONCURRENCY 环境变量可覆盖（生产环境可设 4）
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8765", "--workers", "2", "--proxy-headers", "--forwarded-allow-ips", "*"]