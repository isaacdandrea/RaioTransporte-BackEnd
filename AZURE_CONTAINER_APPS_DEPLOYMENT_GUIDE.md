# Deploying the RaioTransporte Back-end on Azure Container Apps

This guide shows how to deploy the existing production container (`mobilidade/Dockerfile`) to
[Azure Container Apps](https://learn.microsoft.com/azure/container-apps/overview). The same image is
already optimised for Google Cloud Run and AWS Lambda (via the AWS Lambda Web Adapter); no source
changes are required to run on Azure. Azure Container Apps provides autoscaling HTTP revisions with
support for `minReplicas: 0`, so you only pay when requests arrive—similar to Google Cloud Run.

---

## 1. Prerequisites

1. **Azure subscription with Container Apps enabled.**
2. **Azure CLI v2.51+** (`az version`) with the *containerapp* extension installed:
   ```bash
   az extension add --name containerapp --upgrade
   ```
3. **Azure Container Registry (ACR)** to store the image.
4. **Azure Database for PostgreSQL Flexible Server** (or any managed PostGIS instance) reachable
   from Container Apps. Provision a server with the PostGIS extension enabled and collect the
   connection string (username, password, host, database).
5. **GitHub repository secrets** (for the provided workflow):
   - `AZURE_CREDENTIALS` – Service principal JSON with `Contributor` access to the resource group.
   - `AZURE_SUBSCRIPTION_ID`
   - `AZURE_RESOURCE_GROUP`
   - `AZURE_CONTAINERAPP_NAME`
   - `AZURE_CONTAINERAPPS_ENVIRONMENT`
   - `AZURE_DATABASE_URL_SECRET_NAME` – Desired Container App secret name for the database URL
     (e.g. `database-url`).
   - `AZURE_DATABASE_URL` – Full `postgis://` connection string pointing at the managed database.
   - `AZURE_SECRET_KEY_NAME` – Secret name for the Django secret key (e.g. `django-secret`).
   - `DJANGO_SECRET_KEY` – Strong random string. Never reuse the development key.
   - `AZURE_API_SHARED_SECRET_NAME` – Secret name for the API shared key (e.g. `api-shared-secret`).
   - `API_SHARED_SECRET` – Shared API token consumed by your clients.
   - `ACR_LOGIN_SERVER`, `ACR_USERNAME`, `ACR_PASSWORD` – Credentials for the Container Registry.

   Store less sensitive configuration (e.g. `ALLOWED_HOSTS`, `CORS_ALLOWED_ORIGIN_REGEXES`) as
   Container App environment variables later.

---

## 2. Build & push the image with GitHub Actions

The repository now includes `.github/workflows/azure-container-apps.yml`. When triggered (on pushes
to `main` or manually via *workflow_dispatch*), the workflow:

1. Builds the container from `mobilidade/Dockerfile` using Docker Buildx and the `.dockerignore`
   that strips development-only files from the context.
2. Pushes the image to Azure Container Registry with content cache layers for faster rebuilds.
3. Creates or updates the Azure Container App:
   - Configures **external ingress on port 8080** with HTTP/2 and revision-based deployments.
   - Applies CPU/memory requests (`0.25 CPU`, `0.5 GiB` by default to stay within the free tier—override via repository variables).
   - Sets **`minReplicas=0`** (scale to zero) and **`maxReplicas=2`** (override via variables).
   - Injects the Django configuration via environment variables and secret references.
   - Uploads secrets (`SECRET_KEY`, `API_SHARED_SECRET`, `DATABASE_URL`) securely to the Container App.
   - Ensures Gunicorn concurrency is configurable (`WEB_CONCURRENCY`, `GUNICORN_THREADS`).

All configuration values can be overridden without editing the workflow by defining repository or
environment variables (for resource sizing) and secrets (for sensitive data).

> ℹ️  The workflow is idempotent: if the Container App does not exist it will be created; otherwise a
> new revision is published with the updated image and configuration. Each run attaches a distinct
> revision suffix based on the GitHub run number so you can roll back if needed.

> 💰  The defaults above stay within the Azure Container Apps **free monthly grant** (180,000 vCPU-seconds
> and 360,000 GiB-seconds) when the service only scales out briefly. Keep `maxReplicas` at `1` or `2`
> while operating on credits or the free tier, and raise the limit once steady traffic justifies the
> additional spend.

To run manually, open **Actions → Build and Deploy to Azure Container Apps → Run workflow** and
optionally provide a custom image tag. The default tag is the short commit SHA.

---

## 3. Configure networking & observability

1. **Database access** – Ensure your Azure Database for PostgreSQL server allows inbound traffic from
   the Container Apps environment (via a VNet integration or firewall rule). For production traffic,
   prefer a VNet-injected Container App environment with private networking.
2. **TLS** – Container Apps provisions HTTPS automatically on the external endpoint. Add your custom
   domains through Azure Front Door or Container Apps managed certificates as required.
3. **Logging** – Enable Log Analytics for the Container App environment to view Gunicorn stdout/stderr
   logs and HTTP access logs in Azure Monitor. Gunicorn is configured to emit structured logs to stdout.
4. **Health checks** – Azure Container Apps honours Kubernetes-style probes if configured. Django
   exposes a `/_ah/health/` endpoint (via `mobilidade.urls`) suitable for readiness probes; configure a
   probe if you need faster failure detection under heavy load.

---

## 4. Horizontal scalability verification

The Django application is stateless: sessions and API authentication rely on headers rather than local
storage, static assets are served from immutable `collectstatic` output bundled in the image, and the
PostGIS database runs externally. Gunicorn workers read configuration from environment variables and
share no filesystem state. As a result:

- **Azure Container Apps** can safely scale out to multiple replicas. Begin with `maxReplicas=2` to
  stay within the free allowance, then raise the limit as traffic and available credits increase while
  monitoring CPU/memory usage through Log Analytics.
- **Request concurrency** is controlled via the `WEB_CONCURRENCY` and `GUNICORN_THREADS` environment
  variables. Tune these values according to CPU and memory allocations per replica. Start with the
  low-cost defaults (2 workers × 2 threads) and adjust after observing p95 response times.
- **Database connections** reuse a connection pool thanks to Django's `CONN_MAX_AGE` setting. Ensure
  your managed database allows enough connections for the number of replicas (`workers × threads ×
  replicas`). Azure Database for PostgreSQL Flexible Server supports autoscale storage and connection
  limits on General Purpose SKUs.

Because the container image already uses a non-root user (`django`), handles static files locally, and
reads secrets from environment variables, it satisfies Azure Container Apps security best practices.
No additional code changes are necessary for horizontal scaling.

---

## 5. Post-deployment configuration

After the first successful deployment:

1. **Set public hostnames** – Update `ALLOWED_HOSTS`, `CORS_ALLOWED_ORIGINS`, and
   `CSRF_TRUSTED_ORIGINS` on the Container App to list the final domains. You can manage these values
   via the Azure Portal or with `az containerapp update --set-env-vars`.
2. **Rotate secrets** – To rotate the API key or secret key, update the respective GitHub secrets and
   re-run the workflow. Container Apps will create a new revision with the rotated secrets.
3. **Database migrations** – Run Django migrations either by executing `python manage.py migrate`
   inside a one-off Container App job (`az containerapp job start`) or by running the command locally
   against the managed database before switching traffic.
4. **Backups** – Configure automated backups on Azure Database for PostgreSQL and enable Application
   Insights or Log Analytics alerts for elevated error rates.

---

## 6. Manual deployment alternative (optional)

If you prefer deploying without GitHub Actions:

```bash
# Log in
az login
az account set --subscription <subscription-id>

# Build & push
az acr build \
  --registry <acr-name> \
  --image raio-transporte-api:manual \
  --file mobilidade/Dockerfile \
  mobilidade

# Deploy (assumes the Container App environment already exists)
az containerapp up \
  --name <container-app-name> \
  --resource-group <resource-group> \
  --environment <container-app-env> \
  --image <acr-login-server>/raio-transporte-api:manual \
  --target-port 8080 \
  --ingress external \
  --min-replicas 0 \
  --max-replicas 2 \
  --cpu 0.25 \
  --memory 0.5Gi \
  --env-vars \
    DJANGO_SETTINGS_MODULE=mobilidade.settings_prod \
    PORT=8080 \
    WEB_CONCURRENCY=2 \
    GUNICORN_THREADS=2 \
    DATABASE_URL=secretref:database-url \
    SECRET_KEY=secretref:django-secret \
    API_SHARED_SECRET=secretref:api-shared-secret \
  --secrets \
    database-url="<postgis-url>" \
    django-secret="<strong-secret>" \
    api-shared-secret="<shared-api-key>"
```

Replace the placeholders with your environment-specific values. The command above mirrors the GitHub
Actions workflow and enables zero-to-peak autoscaling.

---

## 7. Next steps

- Integrate Azure Key Vault with Container Apps secrets for centralised secret management.
- Configure Dapr sidecars if you need distributed tracing or event-driven scale rules (e.g. Azure
  Service Bus triggers) alongside the HTTP-based autoscaling already provided.
- Use Azure Monitor alerts to notify your team when replicas scale out or if error rates exceed the
  baseline.

With these steps you have a cost-efficient, horizontally scalable deployment of the RaioTransporte
API running on Azure alongside the existing Google Cloud and AWS workflows.
