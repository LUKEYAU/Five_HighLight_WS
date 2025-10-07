FROM python:3.11-slim
WORKDIR /app
COPY pyproject.toml poetry.lock* /app/
RUN pip install --no-cache-dir fastapi uvicorn[standard] boto3 psycopg[binary] sqlalchemy alembic python-jose[cryptography] redis rq pydantic[email]
COPY . /app
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
