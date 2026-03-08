FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends supervisor tzdata \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements.txt
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY alembic.ini alembic.ini
COPY alembic ./alembic
COPY app ./app
COPY deploy ./deploy

RUN chmod +x /app/deploy/entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["/app/deploy/entrypoint.sh"]
