# syntax=docker/dockerfile:1.7

FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

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

ARG AWS_LAMBDA_ADAPTER_VERSION=0.9.1

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DJANGO_SETTINGS_MODULE=mobilidade.settings_prod \
    PORT=8080 \
    SECRET_KEY=dummy-secret-key \
    API_SHARED_SECRET=dummy-api-shared-secret \
    DATABASE_URL=postgis://postgres:postgres@localhost:5432/postgres \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    gdal-bin \
    libgdal-dev \
    libproj-dev \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --system django \
    && useradd --system --gid django --home /home/django --create-home django

WORKDIR /app

# Download the AWS Lambda Web Adapter so the same image can serve Lambda and HTTP workloads.
ADD https://github.com/awslabs/aws-lambda-web-adapter/releases/download/v${AWS_LAMBDA_ADAPTER_VERSION}/aws-lambda-adapter /opt/aws-lambda-adapter
RUN chmod +x /opt/aws-lambda-adapter

COPY --from=builder /wheels /wheels
COPY requirements.txt ./
RUN pip install --no-cache-dir --find-links=/wheels -r requirements.txt \
    && rm -rf /wheels

COPY manage.py ./
COPY mobilidade ./mobilidade
COPY transporte ./transporte
COPY gunicorn.conf.py ./
COPY docker-entrypoint.sh /entrypoint.sh

ENV PYTHONPATH=/app

RUN chmod +x /entrypoint.sh \
    && DJANGO_SETTINGS_MODULE=mobilidade.settings python manage.py collectstatic --noinput \
    && chown -R django:django /app

EXPOSE 8080

USER django

ENTRYPOINT ["/entrypoint.sh"]
CMD ["gunicorn", "-c", "gunicorn.conf.py", "mobilidade.wsgi:application"]
