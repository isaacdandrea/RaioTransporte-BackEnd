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
| `CORS_ALLOWED_ORIGIN_REGEXES` | Comma separated list of regex origins (e.g. `^https://.+\.a\.run\.app$`). | empty |
| `CORS_ALLOW_CREDENTIALS` | Enable CORS requests with cookies/authorization headers. | `false` |
| `CSRF_TRUSTED_ORIGINS` | Comma separated list of CSRF trusted origins. | derived from hosts |
| `DB_CONN_MAX_AGE` | Persistent DB connection age in seconds. | `60` |
| `PORT` | Port exposed by Gunicorn. | `8080` |
| `WEB_CONCURRENCY` | Gunicorn worker processes per instance. | CPU count |
| `GUNICORN_THREADS` | Threads per worker. | `4` |
| `GUNICORN_TIMEOUT` | Worker timeout in seconds. | `120` |
| `GUNICORN_WORKER_CLASS` | Gunicorn worker class. | `gthread` |

> ℹ️  When deploying to Cloud Run make sure to set `SECRET_KEY`, `ALLOWED_HOSTS`, and `DATABASE_URL`
> through Cloud Run service variables or a Secret Manager reference.

## Local Container Workflow

1. **Start a PostGIS database (once):**
   ```bash
   cd mobilidade
   docker compose up -d db
   ```
   This launches a reusable PostGIS container that listens on `localhost:5433`.

2. **Build the API image:**
   ```bash
   docker build -t raio-transporte:latest .
   ```
   Docker Compose creates a network named `mobilidade_default`; the next steps attach the API
   container to that network so it can reach the database at the hostname `db`.

3. **Run database migrations inside the container (first run or after model changes):**
   ```bash
   docker run --rm \
     --network mobilidade_default \
     -e SECRET_KEY="change-me" \
     -e DATABASE_URL="postgis://mobilidade:eId6DiJ3c8tFVK1AC0PQxlgSAZRpZT69iSTAJJjDpxm7VbDdvpCoMCXEudV2W37z@db:5432/mobilidade" \
     -e ALLOWED_HOSTS="localhost" \
     raio-transporte:latest \
     python manage.py migrate
   ```
   Replace the database URL if you change the credentials defined in `docker-compose.yml`.

4. **Run the API locally:**
   ```bash
   docker run --rm -p 8080:8080 \
     --network mobilidade_default \
     -e SECRET_KEY="change-me" \
     -e DATABASE_URL="postgis://mobilidade:eId6DiJ3c8tFVK1AC0PQxlgSAZRpZT69iSTAJJjDpxm7VbDdvpCoMCXEudV2W37z@db:5432/mobilidade" \
     -e ALLOWED_HOSTS="localhost" \
     -e CORS_ALLOWED_ORIGINS="http://localhost:8080,http://10.0.2.2:8080" \
     raio-transporte:latest
   ```
   The additional CORS origins allow Android emulators (`10.0.2.2`) and local browsers to reach the container.

5. **Point your Flutter app to `http://10.0.2.2:8080` (Android emulator) or `http://localhost:8080` (Flutter desktop/web)** to call the API.

Stop the database when finished with `docker compose down`.

## Configuring CORS for Cloud Run & Flutter

When deploying to Cloud Run, set the following service variables to follow least-privilege CORS
practices:

```text
CORS_ALLOWED_ORIGINS=https://your-flutter-web-domain.app
CORS_ALLOWED_ORIGIN_REGEXES=^https://.+\.a\.run\.app$
CORS_ALLOW_CREDENTIALS=true   # only if you rely on cookies/authorization headers
CSRF_TRUSTED_ORIGINS=https://your-flutter-web-domain.app
ALLOWED_HOSTS=your-service-uc.a.run.app,your-custom-domain.com
```

* Use exact origins for known Flutter web or mobile proxy domains whenever possible.
* Prefer regexes (`CORS_ALLOWED_ORIGIN_REGEXES`) to cover the auto-generated Cloud Run host while
  keeping the wildcard narrowly scoped to the `.a.run.app` domain.
* Leave `CORS_ALLOW_ALL_ORIGINS` unset so the service never falls back to `*`.

After updating variables, redeploy or trigger a new revision in Cloud Run for the settings to take
effect.

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
