# RaioTransporte Back-end (Cloud Run Ready)

This repository contains the production-ready container definition for the RaioTransporte back-end.
The application exposes Django REST APIs only (no Django templates/front-end) and is optimised for
running on Google Cloud Run with horizontal autoscaling.

## Runtime Environment Variables

| Variable | Description | Default (container) |
| --- | --- | --- |
| `SECRET_KEY` | Django secret key (must be overridden in production). | `dummy-secret-key` |
| `DJANGO_SETTINGS_MODULE` | Django settings module. | `mobilidade.settings_prod` |
| `DATABASE_URL` | Database connection string (PostGIS). | `postgis://postgres:postgres@localhost:5432/postgres` |
| `ALLOWED_HOSTS` | Comma separated list of allowed hosts. | _required in production_ |
| `CORS_ALLOWED_ORIGINS` | Comma separated list of CORS origins. | empty |
| `CSRF_TRUSTED_ORIGINS` | Comma separated list of CSRF trusted origins. | derived from hosts |
| `DB_CONN_MAX_AGE` | Persistent DB connection age in seconds. | `60` |
| `PORT` | Port exposed by Gunicorn. | `8080` |
| `WEB_CONCURRENCY` | Gunicorn worker processes per instance. | CPU count |
| `GUNICORN_THREADS` | Threads per worker. | `4` |
| `GUNICORN_TIMEOUT` | Worker timeout in seconds. | `120` |
| `GUNICORN_WORKER_CLASS` | Gunicorn worker class. | `gthread` |

> ℹ️  When deploying to Cloud Run make sure to set `SECRET_KEY`, `ALLOWED_HOSTS`, and `DATABASE_URL`
> through Cloud Run service variables or a Secret Manager reference.

## Local Development

```bash
# Build the production image locally
cd mobilidade
docker build -t raio-transporte:latest .

# Run the container (requires an accessible PostGIS instance)
docker run --rm -p 8080:8080 \
  -e SECRET_KEY="change-me" \
  -e DATABASE_URL="postgis://user:pass@host:5432/db" \
  -e ALLOWED_HOSTS="localhost" \
  raio-transporte:latest
```

## Cloud Build & Cloud Run Deployment

1. Create an Artifact Registry repository named `raio-transporte` in your chosen region.
2. Grant the Cloud Build service account permissions to push images and deploy Cloud Run services.
3. Trigger Cloud Build (manually or via GitHub triggers). The provided `cloudbuild.yaml` will:
   - Build the container using `mobilidade/Dockerfile`.
   - Push the image to Artifact Registry (`${_IMAGE}`).
   - Deploy to Cloud Run using the substitutions defined at the top of `cloudbuild.yaml`.
4. Configure required environment variables (`SECRET_KEY`, `DATABASE_URL`, `ALLOWED_HOSTS`, optional
   CORS/CSRF values) on the Cloud Run service. Enable the Cloud SQL Auth Proxy or VPC Connector if
   required for database connectivity.

## Horizontal Scalability

The container image is stateless, runs the Gunicorn process as an unprivileged `django` user, and
relies on managed services for persistence:

- Database connections rely on PostGIS via `DATABASE_URL` and can leverage connection pooling by
  adjusting `DB_CONN_MAX_AGE`.
- Request caching leverages the shared database (`GeoRequestCache` table) ensuring all instances share
  cached results without relying on local disk.
- Static assets are collected at build time and served by WhiteNoise within each instance, avoiding
  shared storage.

Cloud Run can automatically scale the service to multiple instances based on request load. Update
`_MAX_INSTANCES` in `cloudbuild.yaml` or override via deployment flags to cap scaling as needed.
