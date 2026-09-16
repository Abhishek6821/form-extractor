FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN apt-get update && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 && rm -rf /var/lib/apt/lists/*
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY eval/fixtures/forms ./eval/fixtures/forms
COPY pyproject.toml .
ENV FORM_DB_PATH=/data/store.db FORM_UPLOAD_DIR=/data/uploads
VOLUME ["/data"]
EXPOSE 8000
# Two workers: while one runs a CPU-heavy pipeline, the other keeps answering health checks.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers ${WEB_CONCURRENCY:-2}"]
