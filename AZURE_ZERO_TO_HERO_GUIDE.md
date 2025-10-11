# Azure Zero-to-Hero Deployment Guide for RaioTransporte Back-end

This tutorial walks you (a cloud beginner) through migrating your existing PostgreSQL/PostGIS database to Microsoft Azure and deploying the RaioTransporte Django back-end so that it scales to zero and only consumes your Azure free credit when requests arrive. The guide is organised in the recommended order:

1. **Migrate the database** from your local machine to Azure Database for PostgreSQL Flexible Server.
2. **Build and publish the Docker image** defined in [`mobilidade/Dockerfile`](mobilidade/Dockerfile).
3. **Deploy the container** to Azure Container Apps with `minReplicas=0` (scale to zero) and wire it to the managed database.

Each major task lists both **Azure CLI** and **Azure Portal (web UI)** steps so you can choose whichever interface feels more comfortable. Keep the Azure Portal open in one browser tab and your terminal ready for CLI commands.

---

## 0. Prerequisites (Local Machine)

Before starting, ensure you have the following tools on your computer:

- **Azure subscription** with the $200 free credit activated.
- **Azure CLI v2.51+** with the Container Apps extension: `az extension add --name containerapp --upgrade`.
- **Docker** (Desktop or Engine) capable of building multi-stage images.
- **Git** to pull this repository and optionally use the provided GitHub Actions workflow.
- **PostgreSQL client tools** (`pg_dump`, `psql`) for exporting and importing your data.
- **Python 3.12** (only required if you plan to run Django commands locally).

Throughout the guide replace placeholders surrounded by `<angle-brackets>` with your own values.

---

## 1. Plan the Azure resource layout

| Resource | Purpose | Suggested Name | Notes |
| --- | --- | --- | --- |
| Resource Group | Container for all Azure assets | `rg-raio-demo` | Keeps billing isolated and easy to clean up. |
| Azure Database for PostgreSQL Flexible Server | Managed Postgres/PostGIS instance | `pg-raio-demo` | Choose **Burstable B1MS** compute + 32 GiB storage to remain within free credits. |
| Azure Container Registry (ACR) | Stores the Docker image built from [`mobilidade/Dockerfile`](mobilidade/Dockerfile) | `acrraiodemo` | Use the **Basic** SKU (≈ $5/month, billable after free credits). Delete later if not needed. |
| Log Analytics Workspace | Collects Container Apps logs | `law-raio-demo` | Required for Container Apps diagnostics. |
| Container Apps Environment | Hosts the scalable container | `cae-raio-demo` | Supports `minReplicas=0` for scale-to-zero. |
| Container App | Runs the Django/Gunicorn server | `raio-api` | Listens on TCP port **8080** (`PORT` env var). |
| Key Vault (optional) | Centralised secret store | `kv-raio-demo` | Optional; secrets can live directly inside the Container App. |

> 💡 *Cost tip:* Delete the resource group when you finish experiments to stop charges.

### Azure CLI planning commands

```bash
# Log in and set subscription
az login
az account set --subscription <your-subscription-id>

# Create a resource group in your preferred region
az group create \
  --name rg-raio-demo \
  --location <azure-region>
```

### Azure Portal equivalent

1. Go to [portal.azure.com](https://portal.azure.com/).
2. Search for **Resource groups** → **Create**.
3. Choose your subscription, enter `rg-raio-demo` (or any name), pick a region (e.g., `eastus`), and click **Review + create** → **Create**.

---

## 2. Migrate your local PostgreSQL/PostGIS database first

Your Django project reads the connection string from the `DATABASE_URL` environment variable (`postgis://` URI). Migrating this database ensures the cloud app connects to production data from day one.

### 2.1 Provision Azure Database for PostgreSQL Flexible Server

**CLI**
```bash
# Enable required providers once per subscription
az provider register --namespace Microsoft.DBforPostgreSQL

# Create the managed database (Burstable B1MS with 32 GiB storage)
az postgres flexible-server create \
  --resource-group rg-raio-demo \
  --name pg-raio-demo \
  --location <azure-region> \
  --admin-user pgadmin \
  --admin-password "<StrongPassword123>" \
  --sku-name B1MS \
  --storage-size 32 \
  --version 15 \
  --public-access 0.0.0.0-255.255.255.255
```
The `--public-access` option temporarily opens the firewall so you can import data. Later you can tighten it to your IP or integrate with a virtual network.

**Portal**
1. Search for **Azure Database for PostgreSQL flexible server** → **Create**.
2. Select subscription/resource group `rg-raio-demo`.
3. Choose **Flexible server** deployment, enter server name `pg-raio-demo`, set your admin username/password, and pick the same region as the Container App.
4. Under **Compute + storage**, choose **Burstable** tier → `B1MS` with 32 GiB storage.
5. On **Networking**, select **Public access (allowed IP addresses)** and add your local IP (or temporarily allow all addresses).
6. On **Additional settings**, pick **Create a new database** named `raiodb` and enable **PostgreSQL extensions** after creation.
7. Review + create.

### 2.2 Enable PostGIS extension

The Django project expects PostGIS support (see [`requirements.txt`](mobilidade/requirements.txt) for `psycopg2` and GIS packages).

**CLI**
```bash
az postgres flexible-server db create \
  --resource-group rg-raio-demo \
  --server-name pg-raio-demo \
  --database-name raiodb

psql "host=pg-raio-demo.postgres.database.azure.com user=pgadmin password=<StrongPassword123> dbname=raiodb sslmode=require" \
  -c "CREATE EXTENSION IF NOT EXISTS postgis;"
```

**Portal**
1. Open your server → **Databases** → ensure `raiodb` exists (create if necessary).
2. Use the **Query editor (preview)**, log in with admin credentials, and run `CREATE EXTENSION IF NOT EXISTS postgis;`.

### 2.3 Export your local database

Run these commands from your machine that hosts the current database.
```bash
pg_dump \
  --format=custom \
  --file=raio_local.backup \
  --dbname=postgresql://<local-user>:<local-password>@localhost:<local-port>/<local-dbname>
```
This creates a compressed backup file (`.backup`). Store it securely; it may contain sensitive data.

### 2.4 Import into Azure

Upload the backup file and restore it using `pg_restore`.

```bash
pg_restore \
  --no-owner \
  --role=pgadmin \
  --dbname="postgresql://pgadmin:<StrongPassword123>@pg-raio-demo.postgres.database.azure.com:5432/raiodb?sslmode=require" \
  raio_local.backup
```

> ✅ If your local roles differ from Azure, the `--no-owner --role=pgadmin` flags remap objects to the admin account.

**Portal alternative**
1. In **Query editor**, you can run SQL scripts manually, but large backups are easier with CLI. For small datasets you can copy/paste SQL statements.

### 2.5 Secure the database

After the import succeeds:

- **Restrict firewall** to trusted IPs or a VNet.
  ```bash
  az postgres flexible-server firewall-rule create \
    --resource-group rg-raio-demo \
    --name pg-raio-demo \
    --rule-name allow-cloud-shell \
    --start-ip-address <your-public-ip> \
    --end-ip-address <your-public-ip>

  az postgres flexible-server firewall-rule delete \
    --resource-group rg-raio-demo \
    --name pg-raio-demo \
    --rule-name allAzureIPs
  ```
- **Store the connection string** in a password manager: `postgresql://pgadmin:<StrongPassword123>@pg-raio-demo.postgres.database.azure.com:5432/raiodb?sslmode=require`.

---

## 3. Prepare application secrets & configuration

Your Django settings (`mobilidade/settings_prod.py`) require several environment variables:

| Variable | Purpose | Example |
| --- | --- | --- |
| `DJANGO_SETTINGS_MODULE` | Should stay `mobilidade.settings_prod` | Already defined in Dockerfile. |
| `PORT` | Gunicorn listen port | `8080` (do not change; Container App targets 8080). |
| `DATABASE_URL` | Postgres connection string | `postgis://pgadmin:...@pg-raio-demo.postgres.database.azure.com:5432/raiodb?sslmode=require` |
| `SECRET_KEY` | Django secret key | Generate via `python -c "import secrets; print(secrets.token_urlsafe(50))"`. |
| `API_SHARED_SECRET` | Shared key enforced by project middleware | Generate a strong random string. |
| `ALLOWED_HOSTS` | Comma-separated list of domains | `raio-api.<region>.azurecontainerapps.io` initially. |
| `CORS_ALLOWED_ORIGINS` | Allowed origins for browsers | Include your frontend domains. |
| `CSRF_TRUSTED_ORIGINS` | CSRF whitelist | Mirror public HTTPS domains. |

Keep these values ready for both CLI and portal steps.

---

## 4. Build and publish the Docker image

The repository already ships with a production-ready Dockerfile at [`mobilidade/Dockerfile`](mobilidade/Dockerfile). It uses multi-stage builds, installs GDAL/PROJ for GeoDjango, runs `collectstatic`, and exposes port **8080** through Gunicorn (`docker-entrypoint.sh`).

### 4.1 Create Azure Container Registry

**CLI**
```bash
az acr create \
  --resource-group rg-raio-demo \
  --name acrraiodemo \
  --sku Basic \
  --location <azure-region>
```

**Portal**
1. Search for **Container registries** → **Create**.
2. Choose resource group, name `acrraiodemo`, region, and **Basic** SKU → **Review + create**.

### 4.2 Log in and build the image locally (optional)

```bash
az acr login --name acrraiodemo

# From the repo root
docker build -f mobilidade/Dockerfile -t acrraiodemo.azurecr.io/raio-api:local mobilidade

docker push acrraiodemo.azurecr.io/raio-api:local
```
This path builds the same image used in production. Alternatively you can let Azure build it remotely.

### 4.3 Build using ACR Tasks (no local Docker push)

```bash
az acr build \
  --registry acrraiodemo \
  --image raio-api:latest \
  --file mobilidade/Dockerfile \
  mobilidade
```
Azure fetches the context from the current directory and stores the resulting image in the registry.

**Portal alternative**
1. Open your Container Registry → **Services → Tasks** → **Quick task**.
2. Point to your GitHub repo or upload source archive, set image name `raio-api:latest`, and run the build.

> 🔁 Whenever you push changes to `mobilidade/` or `transporte/`, rebuild the image so the Container App picks up the new code.

---

## 5. Deploy to Azure Container Apps with scale-to-zero

Azure Container Apps gives you Cloud Run–like behaviour. The deployment exposes an HTTPS endpoint, autoscaled between 0 and N replicas, and wakes on HTTP traffic.

### 5.1 Create the Container Apps environment

**CLI**
```bash
# Create Log Analytics workspace
aisid="$(az monitor log-analytics workspace create \
  --resource-group rg-raio-demo \
  --workspace-name law-raio-demo \
  --query id -o tsv)"

# Create the environment with workload profiles disabled for the simplest setup
az containerapp env create \
  --name cae-raio-demo \
  --resource-group rg-raio-demo \
  --location <azure-region> \
  --logs-workspace-id "$aisid"
```

**Portal**
1. Search for **Container Apps** → **Create**.
2. Under **Project details** pick your resource group and region.
3. Create a new **Container Apps environment** `cae-raio-demo`, linking it to a new Log Analytics workspace (`law-raio-demo`).

### 5.2 Create secrets for database and keys

**CLI**
```bash
az containerapp secret set \
  --name raio-api \
  --resource-group rg-raio-demo \
  --secrets \
    database-url="postgis://pgadmin:<StrongPassword123>@pg-raio-demo.postgres.database.azure.com:5432/raiodb?sslmode=require" \
    django-secret="<GeneratedDjangoSecret>" \
    api-shared-secret="<GeneratedApiSecret>"
```
> The command above will fail if the Container App does not exist yet—run it after you create the app in the next step, or pass `--no-wait` followed by `az containerapp update`.

**Portal**
1. When creating the Container App (next section), there is a **Secrets** tab where you can input these values.

### 5.3 Deploy the Container App

**CLI**
```bash
az containerapp create \
  --name raio-api \
  --resource-group rg-raio-demo \
  --environment cae-raio-demo \
  --image acrraiodemo.azurecr.io/raio-api:latest \
  --target-port 8080 \
  --ingress external \
  --registry-login-server acrraiodemo.azurecr.io \
  --registry-username "$(az acr credential show --name acrraiodemo --query username -o tsv)" \
  --registry-password "$(az acr credential show --name acrraiodemo --query passwords[0].value -o tsv)" \
  --min-replicas 0 \
  --max-replicas 2 \
  --cpu 0.25 \
  --memory 0.5Gi \
  --secrets \
      database-url="postgis://pgadmin:<StrongPassword123>@pg-raio-demo.postgres.database.azure.com:5432/raiodb?sslmode=require" \
      django-secret="<GeneratedDjangoSecret>" \
      api-shared-secret="<GeneratedApiSecret>" \
  --env-vars \
      DJANGO_SETTINGS_MODULE=mobilidade.settings_prod \
      PORT=8080 \
      WEB_CONCURRENCY=2 \
      GUNICORN_THREADS=2 \
      DATABASE_URL=secretref:database-url \
      SECRET_KEY=secretref:django-secret \
      API_SHARED_SECRET=secretref:api-shared-secret \
      ALLOWED_HOSTS="raio-api.<region>.azurecontainerapps.io" \
      CORS_ALLOWED_ORIGINS="https://your-frontend.example" \
      CSRF_TRUSTED_ORIGINS="https://your-frontend.example"
```

**Portal**
1. Create a Container App → Choose your environment `cae-raio-demo`.
2. On **Container** tab, select **Use existing container registry** and authenticate against `acrraiodemo`.
3. Set the image to `raio-api:latest`, target port `8080`, and enable **Ingress** → **External** with **Transport** = `Auto`.
4. In **Scale**, choose **Revision mode: multiple**, `Min replicas = 0`, `Max replicas = 2`. Leave the default HTTP scale rule (Container Apps wakes on HTTP requests by default).
5. In **Secrets**, add `database-url`, `django-secret`, `api-shared-secret`.
6. In **Environment variables**, create entries referencing the secrets as shown above (`secretref:`). Add `ALLOWED_HOSTS`, `CORS_ALLOWED_ORIGINS`, `CSRF_TRUSTED_ORIGINS` as comma-separated strings.
7. Review + create.

> ⚙️ The Dockerfile already runs `collectstatic` and uses Gunicorn with configuration from [`gunicorn.conf.py`](mobilidade/gunicorn.conf.py). No extra container command is required.

### 5.4 Verify deployment

```bash
az containerapp show \
  --name raio-api \
  --resource-group rg-raio-demo \
  --query properties.configuration.ingress.fqdn \
  -o tsv
```
Open the returned URL in your browser. The app may take a few seconds to warm up because `minReplicas=0` allows scale-to-zero. Subsequent requests wake the container automatically.

**Portal**: Open the Container App → copy the Application URL from the overview page.

### 5.5 Run database migrations in Azure

Run Django migrations against the managed database after deployment.

**CLI option A – Container App exec**
```bash
az containerapp exec \
  --name raio-api \
  --resource-group rg-raio-demo \
  --command "python manage.py migrate"
```

**CLI option B – One-off Container App job**
```bash
az containerapp job create \
  --name raio-migrate \
  --resource-group rg-raio-demo \
  --environment cae-raio-demo \
  --trigger-type Manual \
  --replica-timeout 1800 \
  --replica-retry-limit 3 \
  --image acrraiodemo.azurecr.io/raio-api:latest \
  --secrets-from-app raio-api \
  --env-vars-from-app raio-api \
  --command "python" "manage.py" "migrate"

az containerapp job start --name raio-migrate --resource-group rg-raio-demo
```

**Portal**: In the Container App → **Revisions and replicas** → **Console**, run `python manage.py migrate`.

---

## 6. Set up monitoring and scale rules

- Container Apps automatically emits logs to Log Analytics. View them with:
  ```bash
  az monitor log-analytics query \
    --workspace law-raio-demo \
    --analytics-query "ContainerAppConsoleLogs_CL | where ContainerAppName_s == 'raio-api' | take 50"
  ```
- In the Portal, open the Container App → **Logs** to tail stdout/stderr.
- Leave scale trigger as HTTP-based. To add CPU-based rules later:
  ```bash
  az containerapp revision set-mode --name raio-api --resource-group rg-raio-demo --mode multiple
  az containerapp update --name raio-api --resource-group rg-raio-demo \
    --scale-rule-name http \
    --scale-rule-type http \
    --min-replicas 0 --max-replicas 2
  ```
  The default HTTP rule already scales from 0–2 replicas based on concurrent requests.

---

## 7. Automate deployments (optional)

The repo includes [`AZURE_CONTAINER_APPS_DEPLOYMENT_GUIDE.md`](AZURE_CONTAINER_APPS_DEPLOYMENT_GUIDE.md) and a GitHub Actions workflow (`.github/workflows/azure-container-apps.yml`) that mirrors the CLI steps:

1. Store Azure credentials and secrets in GitHub Secrets.
2. Trigger the workflow on pushes to `main`.
3. The workflow builds the image from `mobilidade/Dockerfile`, pushes it to ACR, and updates the Container App with `minReplicas=0` and `maxReplicas=2`.

This automation is ideal once you validate the manual steps.

---

## 8. Clean-up checklist

To avoid charges after experimenting:

```bash
az group delete --name rg-raio-demo --yes --no-wait
```
Deleting the resource group removes the Container App, registry, database, and workspace together.

---

## 9. Troubleshooting tips

| Symptom | Resolution |
| --- | --- |
| `psql: error: connection timed out` | Ensure firewall rules allow your current IP or enable public access temporarily. |
| Container App returns 500 errors | Check `az containerapp logs show --name raio-api --resource-group rg-raio-demo --type stream` for stack traces. Confirm `DATABASE_URL`, `SECRET_KEY`, and `API_SHARED_SECRET` are set. |
| High cold-start latency | Increase `minReplicas` to 1 (incurs cost) or keep key endpoints warm via scheduled pings. |
| `ImproperlyConfigured` due to hosts/CORS | Set `ALLOWED_HOSTS`, `CORS_ALLOWED_ORIGINS`, and `CSRF_TRUSTED_ORIGINS` environment variables to include the Container App URL and your custom domain. |
| Database connection limit reached | Reduce `WEB_CONCURRENCY`/`GUNICORN_THREADS` or upgrade the database tier. |

---

With this step-by-step process you can migrate your data safely, deploy the containerised Django back-end, and run it on Azure Container Apps with scale-to-zero behaviour that preserves your free credit while you learn the platform.
