# RaioTransporte Back-end (Cloud Run & AWS Ready)

This repository contains the production-ready container definition for the RaioTransporte back-end.
The application exposes Django REST APIs only (no Django templates/front-end) and is optimised for
running on Google Cloud Run, AWS Lambda (via the Lambda Web Adapter), and AWS App Runner with
horizontal autoscaling.

## Runtime Environment Variables

| Variable | Description | Default (container) |
| --- | --- | --- |
| `SECRET_KEY` | Django secret key (must be overridden in production). | `dummy-secret-key` |
| `DJANGO_SETTINGS_MODULE` | Django settings module. | `mobilidade.settings_prod` |
| `DATABASE_URL` | Database connection string (PostGIS). | `postgis://postgres:postgres@localhost:5432/postgres` |
| `ALLOWED_HOSTS` | Comma separated list of allowed hosts. | _required in production_ |
| `SERVICE_BASE_URL`/`SERVICE_BASE_URLS` | Public origin(s) clients use to reach the API. Hosts are auto-added to `ALLOWED_HOSTS`. | empty |
| `API_SHARED_SECRET` | Primary API key shared with trusted clients. | `dummy-api-shared-secret` |
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

### Codex / Codespaces environment scripts

If you are using GitHub Codex/Codespaces, two helper scripts streamline provisioning and
maintenance without touching your database:

```bash
# Run inside a brand-new container after cloning the repository
./scripts/codex/setup.sh

# Run after resuming a cached container to refresh dependencies
./scripts/codex/maintain.sh
```

Both scripts install the GeoDjango system packages (`gdal`, `proj`, `libpq`), create or reuse a
`.venv`, install `mobilidade/requirements.txt`, and copy `.env.example` to `.env` when missing. No
database migrations or destructive operations are executed.

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

## Preparing the local PostGIS container for logical replication

When migrating the `mobilidadenew` database to Google Cloud SQL using Database
Migration Service, the source instance must expose the `pglogical` extension and
have `wal_level` set to `logical`. The helper script below performs the required
steps against the PostGIS container defined in `mobilidade/docker-compose.yml`:

```bash
./scripts/configure_pglogical.sh
```

The script will:

1. Install the `postgresql-15-pglogical` package inside the running
   `mobilidade_postgis` container.
2. Ensure the `mobilidadenew` database exists (creating it with owner
   `mobilidade` if missing).
3. Enable the `pglogical` extension inside `mobilidadenew`.
4. Switch `wal_level` to `logical` and restart the container so the change takes
   effect.

After the restart, the script prints the current `wal_level` as well as the
installed state of the `pglogical` extension so you can confirm the migration
prerequisites.

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

## AWS Deployment

The same container image can be promoted to AWS services without code changes thanks to the
multi-stage Dockerfile, the `.dockerignore` that trims development artefacts from the build context,
and the bundled AWS Lambda Web Adapter.

### Publish to Amazon ECR

1. Authenticate Docker with ECR:

   ```bash
   aws ecr get-login-password --region <region> | \
     docker login --username AWS --password-stdin <aws_account_id>.dkr.ecr.<region>.amazonaws.com
   ```

2. Build and tag the image (the Cloud Build pipeline already does this when running on GCP):

   ```bash
   docker build -t raio-transporte:latest mobilidade
   docker tag raio-transporte:latest <aws_account_id>.dkr.ecr.<region>.amazonaws.com/raio-transporte:latest
   ```

3. Push the image:

   ```bash
   docker push <aws_account_id>.dkr.ecr.<region>.amazonaws.com/raio-transporte:latest
   ```

### AWS App Runner

1. Create (or reuse) a connection to the ECR repository above.
2. Provision a new App Runner service pointing at the container image. Set the port to `8080` and
   copy the environment variables from the table above (remember to override `SECRET_KEY`,
   `API_SHARED_SECRET`/`API_SHARED_SECRETS`, and the CORS/host configuration).
3. App Runner keeps at least one provisioned instance but scales out automatically based on request
   volume. Increase the concurrency limits or request scaling policies as needed.

### AWS Lambda + API Gateway

The runtime image embeds the [AWS Lambda Web Adapter](https://github.com/awslabs/aws-lambda-web-adapter)
and an entrypoint that activates it automatically when the Lambda runtime injects the
`AWS_LAMBDA_RUNTIME_API` environment variable. Build a Lambda function from the same container image
and expose it through API Gateway to obtain true scale-to-zero behaviour.

- Set the handler to `unused` (the adapter takes over the bootstrap process).
- Configure the `PORT` environment variable if you change Gunicorn's default (`8080`).
- Provision the same secrets and CORS/host variables as in Cloud Run/App Runner.

## Horizontal Scalability

The container image is stateless, runs the Gunicorn process as an unprivileged `django` user, and
relies on managed services for persistence:

- Database connections rely on PostGIS via `DATABASE_URL` and can leverage connection pooling by
  adjusting `DB_CONN_MAX_AGE`.
- Request caching leverages the shared database (`GeoRequestCache` table) ensuring all instances share
  cached results without relying on local disk.
- Static assets are collected at build time and served by WhiteNoise within each instance, avoiding
  shared storage.

Cloud Run automatically scales the service to multiple instances based on request load. Update
`_MAX_INSTANCES` in `cloudbuild.yaml` or override via deployment flags to cap scaling as needed.
AWS App Runner performs similar HTTP-based autoscaling (maintaining at least one warm instance),
while AWS Lambda + API Gateway scales to zero and provisions instances per request through the web
adapter bundled in the image.
