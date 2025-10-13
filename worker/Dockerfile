FROM python:3.11-slim

WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

COPY . /app
ENV PYTHONPATH=/app

# 啟動 RQ worker，監聽 "edits" 佇列
CMD ["rq", "worker", "-u", "redis://redis:6379/0", "edits"]
