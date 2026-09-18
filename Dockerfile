# syntax=docker/dockerfile:1.7

FROM node:24-bookworm-slim AS frontend-builder

WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build


FROM python:3.12-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    DATA_DIR=/home/jobtracker/data

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && python -m playwright install --with-deps chromium \
    && chmod -R a+rX /ms-playwright \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --gid 10001 jobtracker \
    && useradd --uid 10001 --gid jobtracker --create-home jobtracker \
    && mkdir -p /home/jobtracker/data \
    && chown jobtracker:jobtracker /home/jobtracker/data

COPY --chown=jobtracker:jobtracker *.py ./
COPY --from=frontend-builder --chown=jobtracker:jobtracker /build/frontend/dist ./frontend/dist

USER 10001:10001
EXPOSE 8000

CMD ["python", "-m", "uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
