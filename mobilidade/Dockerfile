# syntax=docker/dockerfile:1.7

FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# System dependencies required for psycopg2, GDAL and GeoDjango
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gdal-bin \
    libgdal-dev \
    libpq-dev \
    libproj-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt ./
RUN pip install --upgrade pip \
    && pip wheel --wheel-dir /wheels --no-cache-dir --no-deps -r requirements.txt


FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DJANGO_SETTINGS_MODULE=mobilidade.settings_prod \
    PORT=8080 \
    SECRET_KEY=dummy-secret-key \
    DATABASE_URL=postgis://postgres:postgres@localhost:5432/postgres

RUN apt-get update && apt-get install -y --no-install-recommends \
    gdal-bin \
    libgdal-dev \
    libproj-dev \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --system django \
    && useradd --system --gid django --home /home/django --create-home django

WORKDIR /app

COPY --from=builder /wheels /wheels
COPY requirements.txt ./
RUN pip install --no-cache-dir --find-links=/wheels -r requirements.txt \
    && rm -rf /wheels

COPY manage.py ./
COPY mobilidade ./mobilidade
COPY transporte ./transporte
COPY gunicorn.conf.py ./

ENV PYTHONPATH=/app

RUN python manage.py collectstatic --noinput \
    && chown -R django:django /app

EXPOSE 8080

USER django

CMD ["gunicorn", "-c", "gunicorn.conf.py", "mobilidade.wsgi:application"]
