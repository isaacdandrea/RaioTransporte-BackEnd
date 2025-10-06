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
| `SERVICE_BASE_URL`/`SERVICE_BASE_URLS` | Public origin(s) clients use to reach the API. Hosts are auto-added to `ALLOWED_HOSTS`. | empty |
| `API_SHARED_SECRET` | Primary API key shared with trusted clients. | empty |
| `API_SHARED_SECRETS` | Optional comma separated list of API keys (for key rotation). | empty |
| `CORS_ALLOWED_ORIGINS` | Comma separated list of CORS origins. | empty |
| `CSRF_TRUSTED_ORIGINS` | Comma separated list of CSRF trusted origins. | derived from hosts |
| `DB_CONN_MAX_AGE` | Persistent DB connection age in seconds. | `60` |
| `PORT` | Port exposed by Gunicorn. | `8080` |
| `WEB_CONCURRENCY` | Gunicorn worker processes per instance. | CPU count |
| `GUNICORN_THREADS` | Threads per worker. | `4` |
| `GUNICORN_TIMEOUT` | Worker timeout in seconds. | `120` |
| `GUNICORN_WORKER_CLASS` | Gunicorn worker class. | `gthread` |

> ℹ️  When deploying to Cloud Run make sure to set `SECRET_KEY`, `API_SHARED_SECRET` (or
> `API_SHARED_SECRETS`), and either populate `ALLOWED_HOSTS` directly or provide
> `SERVICE_BASE_URL`/`SERVICE_BASE_URLS` with the public URL. Any hostnames listed in
> `CORS_ALLOWED_ORIGINS` or `CSRF_TRUSTED_ORIGINS` are also merged into `ALLOWED_HOSTS`, which helps
> when you only have the public URL handy. Leave `DATABASE_URL` blank if you prefer configuring the
> connection via the individual `DB_*` variables.

### API authentication

The Flutter client authenticates every request by sending the `X-API-Key` header. Django validates
this header using the values configured in `API_SHARED_SECRET`/`API_SHARED_SECRETS`:

- Set a **long, random** secret for production. The example Cloud Build pipeline (below) expects the
  value to come from Secret Manager.
- Provide multiple comma separated values via `API_SHARED_SECRETS` when rotating keys. The backend
  accepts any configured value, while the Flutter app can be updated to a new key at build time.
- Requests without the header still fall back to standard Django authentication (sessions/basic), so
  the Django admin remains accessible during local development.

## Local Development

The production image can be run locally to replicate the Cloud Run deployment. The Django
container expects a PostGIS database and a handful of environment variables.

1. **Start PostGIS (once):**

   ```bash
   cd mobilidade
   docker compose up -d db
   ```

   The database will be exposed on `localhost:5433` with the credentials defined in
   `docker-compose.yml`.

2. **Build the application image:**

   ```bash
   docker build -t raio-transporte:latest .
   ```

3. **Run the container:**

   ```bash
   docker run --rm -p 8080:8080 \
     --name raio-transporte-api \
     --env DEBUG=1 \
     --env SECRET_KEY="change-me" \
     --env DJANGO_SETTINGS_MODULE="mobilidade.settings" \
     --env DATABASE_URL="postgis://mobilidade:eId6DiJ3c8tFVK1AC0PQxlgSAZRpZT69iSTAJJjDpxm7VbDdvpCoMCXEudV2W37z@host.docker.internal:5433/mobilidade" \
     --env ALLOWED_HOSTS="localhost,127.0.0.1" \
     raio-transporte:latest
   ```

   On macOS/Windows Docker Desktop, `host.docker.internal` resolves to the host machine. On Linux
   you can export the gateway IP once (e.g. `DB_HOST=$(ip route | awk 'NR==1 {print $3}')`) and use
   it instead of `host.docker.internal`.

4. **Point the Flutter app to the API:**

   - Android emulator: use `http://10.0.2.2:8080`.
   - Physical device on the same network: use the host IP address (e.g. `http://192.168.x.x:8080`).
   - Web build: `http://localhost:8080`.

   The default development CORS configuration allows the origins above, so no extra Django changes
   are required.

5. **Shut everything down:**

   ```bash
   docker stop raio-transporte-api
   docker compose down
   ```

   The `pgdata` volume is preserved between runs. Remove it with
   `docker volume rm mobilidade_pgdata` when you need a fresh database.

## Configuring CORS for Flutter & Cloud Run

`django-cors-headers` is pre-configured with security-conscious defaults:

- **Development:** when `DEBUG=True`, the API automatically allows requests from
  `localhost`, `127.0.0.1`, and `10.0.2.2` on ports `8000` and `8080`, which covers Flutter web
  previews, Android emulators, and most local testing setups.
- **Production / Cloud Run:** define one (or more) of the following environment variables on the
  Cloud Run service:
  - `CORS_ALLOWED_ORIGINS=https://api.example.com,https://app.example.com`
  - `CORS_ALLOWED_ORIGIN_REGEXES=^https://[\w-]+-a\.run\.app$` (useful while using the default Cloud
    Run domain before a custom domain is ready)
  - `CORS_ALLOW_ALL_ORIGINS=true` (only if you intentionally want to expose the API publicly)

The production settings enforce that at least one of the variables above is configured, following
Google's recommendation to explicitly list trusted origins. Align your Flutter app's base URL with
the domain(s) you configure here. If the app sends authenticated requests, keep
`CORS_ALLOW_ALL_ORIGINS=false` and list each trusted domain explicitly.

## Cloud Build & Cloud Run Deployment

1. Create an Artifact Registry repository named `raio-transporte` in your chosen region.
2. Grant the Cloud Build service account permissions to push images and deploy Cloud Run services.
3. Trigger Cloud Build (manually or via GitHub triggers). The provided `cloudbuild.yaml` will:
   - Build the container using `mobilidade/Dockerfile`.
   - Push the image to Artifact Registry (`${_IMAGE}`).
   - Deploy to Cloud Run using the substitutions defined at the top of `cloudbuild.yaml`, injecting
     the Django secret key and API shared secret from Secret Manager.
4. Configure remaining environment variables (`DATABASE_URL`, optional CORS/CSRF values) on the
   Cloud Run service. Enable the Cloud SQL Auth Proxy or VPC Connector if required for database
   connectivity.

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
