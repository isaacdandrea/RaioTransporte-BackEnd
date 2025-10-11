# Deploying the RaioTransporte Back-end on AWS (Beginner Friendly)

This tutorial walks you—step by step—from a local development setup to a production-ready deployment of the **RaioTransporte** Django/PostGIS back-end on AWS. The guide is intentionally verbose and assumes you have never deployed to AWS before. By the end you will have:

1. Migrated your local PostGIS database to **Amazon RDS for PostgreSQL** with the PostGIS extension enabled.
2. Packaged the Django API (found in `mobilidade/`) as a container image using the repository's `mobilidade/Dockerfile` and pushed it to **Amazon Elastic Container Registry (ECR)**.
3. Deployed that image to **AWS Lambda** using the **AWS Lambda Web Adapter**, fronted by **Amazon API Gateway** so the service scales down to zero between requests.

The process is broken into two major phases: **(A)** migrate the database, **(B)** deploy the application container. Complete the steps in order—the API depends on the database being online first.

> 💡 *Budget tip:* Everything below can run within the AWS Free Tier and the $100 AWS Educate/Student credits. Choose the smallest instance sizes, stay within a single region, and tear resources down when not in use.

---

## 0. Prerequisites

1. **AWS account with credits**
   - Sign in to <https://aws.amazon.com/console/>. If you're using AWS Educate credits, redeem them first.
2. **IAM user with admin rights for the project**
   - In the AWS console, open **IAM → Users → Create user**.
   - Give the user a name like `raio-admin`, check "Provide user access to the AWS Management Console", and set a password.
   - On the permissions step, attach the policy `AdministratorAccess` (you can tighten this later).
   - Save the **Access key ID** and **Secret access key** for CLI usage (Security credentials tab → Create access key → Command Line Interface).
3. **AWS CLI v2 installed locally**
   - macOS: `brew install awscli`
   - Windows: <https://awscli.amazonaws.com/AWSCLIV2.msi>
   - Linux: follow <https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html>
4. **Configure the CLI**
   ```bash
   aws configure
   ```
   - Enter your access key, secret key, default region (e.g. `us-east-1`), and output format (`json`).
5. **Docker installed** (required for building and pushing the container image).
6. **PostgreSQL client tools** on your machine (`psql`, `pg_dump`, `pg_restore`). On macOS: `brew install libpq && brew link --force libpq`. On Ubuntu: `sudo apt install postgresql-client`.

---

## A. Migrate the PostgreSQL/PostGIS database first

Your local development database is defined in `mobilidade/docker-compose.yml`. It runs Postgres 15 with PostGIS 3.3 and credentials:

- Database: `mobilidade`
- User: `mobilidade`
- Password: `eId6DiJ3c8tFVK1AC0PQxlgSAZRpZT69iSTAJJjDpxm7VbDdvpCoMCXEudV2W37z`
- Port: `5433` on your host (mapped to container `5432`)

The production `mobilidade/settings_prod.py` expects a PostGIS-compatible database via the `DATABASE_URL` environment variable. We will recreate this environment in AWS RDS.

### Step A1. Choose a region and create a VPC security group

1. Pick a region close to your users (e.g. `us-east-1`). Use this region for every service to avoid cross-region costs.
2. In the AWS console, go to **VPC → Security groups → Create security group**.
   - Name: `raio-postgres-sg`
   - Description: `Allow database access from Lambda and my IP`
   - VPC: leave the default.
3. Add **Inbound rules**:
   - Type: `PostgreSQL`, Protocol: `TCP`, Port: `5432`, Source: `My IP`. This allows admin access from your machine.
   - You will add Lambda access later via another security group.

### Step A2. Create an Amazon RDS for PostgreSQL instance with PostGIS support

1. Console → **RDS → Create database**.
2. Engine options:
   - Engine type: `PostgreSQL`
   - Version: choose `PostgreSQL 15.x-RX` (RDS versions 15+ include PostGIS 3+).
3. Templates: choose **Free tier**.
4. Settings:
   - DB instance identifier: `raio-postgres`
   - Master username: `mobilidade`
   - Master password: set a strong password (store it securely; you can reuse the local password to simplify credentials).
5. Instance configuration: `db.t4g.micro` (free tier eligible) or `db.t3.micro` if Graviton isn't available in your region.
6. Storage: keep `20 GiB` GP2 (free tier covers 20 GB). Disable storage autoscaling to control cost.
7. Connectivity:
   - VPC: default
   - Public access: **Yes** (required for initial migration from your laptop; you can switch to private later).
   - VPC security group: select `raio-postgres-sg` created earlier.
   - DB port: `5432`.
8. Additional configuration:
   - Initial database name: `mobilidade`
   - Backup: keep defaults (7 days).
   - Maintenance window: default.
   - Deletion protection: disable while testing (remember to enable in production).
9. Click **Create database**. Provisioning takes ~10 minutes.

### Step A3. Enable the PostGIS extension

After the instance status becomes **Available**:

1. Click the DB identifier → copy the **Endpoint** (e.g. `raio-postgres.c123xyz.us-east-1.rds.amazonaws.com`).
2. Connect using `psql`:
   ```bash
   export RDS_ENDPOINT=raio-postgres.c123xyz.us-east-1.rds.amazonaws.com
   PGPASSWORD="<RDS_MASTER_PASSWORD>" psql \
     --host "$RDS_ENDPOINT" \
     --port 5432 \
     --username mobilidade \
     --dbname mobilidade
   ```
3. Inside `psql`, run:
   ```sql
   CREATE EXTENSION IF NOT EXISTS postgis;
   CREATE EXTENSION IF NOT EXISTS postgis_topology;
   ```
4. Verify with `\dx` (PostGIS should appear in the list). Type `\q` to exit.

### Step A4. Dump your local database

Run this from your project root (where `mobilidade/docker-compose.yml` lives):

```bash
cd mobilidade
pg_dump \
  --host localhost \
  --port 5433 \
  --username mobilidade \
  --dbname mobilidade \
  --format custom \
  --file ../backups/mobilidade.backup
```

- Create the `backups/` directory first if it doesn't exist: `mkdir -p ../backups`.
- The `--format custom` option produces a compressed dump that preserves roles, extensions, and schema.

> ✅ If your local database is inside Docker, make sure it is running (`docker compose up -d db`). The `pg_dump` command prompts for the password once; press Enter after typing it.

### Step A5. Upload the dump to Amazon S3 (optional but recommended)

Storing the dump in S3 makes it easier to redo migrations:

```bash
aws s3 mb s3://raio-backups-<unique-suffix>
aws s3 cp ../backups/mobilidade.backup s3://raio-backups-<unique-suffix>/mobilidade.backup
```

Replace `<unique-suffix>` with something like your initials to keep the bucket name globally unique.

### Step A6. Restore the dump into RDS

You can restore either directly from your laptop or via an EC2/RDS Data Import. Direct restore is simpler for small databases:

```bash
PGPASSWORD="<RDS_MASTER_PASSWORD>" pg_restore \
  --host "$RDS_ENDPOINT" \
  --port 5432 \
  --username mobilidade \
  --dbname mobilidade \
  --clean \
  --if-exists \
  --no-owner \
  ../backups/mobilidade.backup
```

- `--clean --if-exists` ensures target tables are replaced.
- `--no-owner` rewrites objects to the `mobilidade` owner in RDS.
- If you uploaded the dump to S3, you can download it first (`aws s3 cp ... ./mobilidade.backup`).

### Step A7. Verify data and prepare security for Lambda

1. Connect again with `psql` and inspect a few tables to confirm the data migrated.
2. Create a **database user for the application** (optional but recommended):
   ```sql
   CREATE USER raio_api WITH PASSWORD '<strong-random-password>';
   GRANT CONNECT ON DATABASE mobilidade TO raio_api;
   GRANT USAGE ON SCHEMA public TO raio_api;
   GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO raio_api;
   GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO raio_api;
   ALTER DEFAULT PRIVILEGES IN SCHEMA public
     GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO raio_api;
   ALTER DEFAULT PRIVILEGES IN SCHEMA public
     GRANT USAGE, SELECT ON SEQUENCES TO raio_api;
   ```
3. Create a new security group for Lambda networking:
   - **VPC → Security groups → Create security group**
     - Name: `raio-lambda-sg`
     - Outbound: allow all (default)
   - Edit `raio-postgres-sg` inbound rules → add rule: Type `PostgreSQL`, Source `raio-lambda-sg` (select by name). This allows any Lambda attached to `raio-lambda-sg` to reach the database privately later.

### Step A8. Store credentials securely

Use AWS Secrets Manager or Systems Manager Parameter Store instead of hard-coding passwords:

```bash
aws secretsmanager create-secret \
  --name raio/mobilidade/database \
  --description "RDS credentials for RaioTransporte API" \
  --secret-string '{"ENGINE":"django.db.backends.postgresql","NAME":"mobilidade","USER":"raio_api","PASSWORD":"<password>","HOST":"raio-postgres.c123xyz.us-east-1.rds.amazonaws.com","PORT":"5432"}'
```

Remember the ARN; Lambda will read it later.

At this point the database is live on AWS. Proceed to the application deployment.

---

## B. Deploy the Django container to AWS Lambda + API Gateway

The repository already contains a production-ready Dockerfile (`mobilidade/Dockerfile`) with the AWS Lambda Web Adapter baked in. We will build the image, push it to ECR, and create a Lambda function that uses it.

### Step B1. Prepare environment variables and secrets

Review `README.md` to see the required production environment variables. At minimum you must set:

- `SECRET_KEY` – generate a long random string.
- `API_SHARED_SECRET` or `API_SHARED_SECRETS` – used by the Flutter client for `X-API-Key` authentication.
- `ALLOWED_HOSTS` – must include the API Gateway hostname or a custom domain.
- `CORS_ALLOWED_ORIGINS` – list the frontend origins (comma-separated URLs).
- `CSRF_TRUSTED_ORIGINS` – if you access the Django admin through a browser.
- `DATABASE_URL` – points to the RDS instance (e.g. `postgis://raio_api:<password>@raio-postgres.c123xyz.us-east-1.rds.amazonaws.com:5432/mobilidade`).

Store these values securely (AWS Secrets Manager is ideal). Later we will map them to Lambda environment variables.

### Step B2. Build the container image locally

From the repository root:

```bash
cd mobilidade
export AWS_REGION=us-east-1              # same region as RDS
export IMAGE_NAME=raio-backend
export IMAGE_TAG=v1

# Build using the provided Dockerfile
DOCKER_BUILDKIT=1 docker build \
  -t $IMAGE_NAME:$IMAGE_TAG \
  -f Dockerfile \
  .
```

The Dockerfile installs GDAL/PROJ/PostgreSQL client libraries, collects Django static files, and bundles the AWS Lambda Web Adapter.

> ✅ The build step runs `python manage.py collectstatic --noinput` using the production settings module. Ensure your local environment has internet access so `pip` can download Python dependencies listed in `requirements.txt`.

### Step B3. Test the container locally (optional but recommended)

Run the container pointing at your new RDS instance to confirm everything works before uploading:

```bash
docker run --rm -p 8080:8080 \
  --env SECRET_KEY="<secret>" \
  --env DJANGO_SETTINGS_MODULE="mobilidade.settings_prod" \
  --env API_SHARED_SECRET="<api-key>" \
  --env ALLOWED_HOSTS="localhost" \
  --env CORS_ALLOWED_ORIGINS="http://localhost:8080" \
  --env DATABASE_URL="postgis://raio_api:<password>@$RDS_ENDPOINT:5432/mobilidade" \
  $IMAGE_NAME:$IMAGE_TAG
```

Open <http://localhost:8080/admin/> to make sure static files load. Stop the container with `Ctrl+C` once satisfied.

### Step B4. Create an ECR repository and push the image

1. Create the repository:
   ```bash
   aws ecr create-repository \
     --repository-name raio-backend \
     --image-scanning-configuration scanOnPush=true
   ```
   Note the repository URI (e.g. `123456789012.dkr.ecr.us-east-1.amazonaws.com/raio-backend`).
2. Authenticate Docker to ECR:
   ```bash
   aws ecr get-login-password --region $AWS_REGION | \
     docker login --username AWS --password-stdin 123456789012.dkr.ecr.$AWS_REGION.amazonaws.com
   ```
3. Tag and push:
   ```bash
docker tag $IMAGE_NAME:$IMAGE_TAG 123456789012.dkr.ecr.$AWS_REGION.amazonaws.com/raio-backend:$IMAGE_TAG
   docker push 123456789012.dkr.ecr.$AWS_REGION.amazonaws.com/raio-backend:$IMAGE_TAG
   ```

### Step B5. Create the Lambda function from the container image

1. Console → **Lambda → Create function** → `Container image`.
2. Function name: `raio-backend`
3. Container image URI: select the image you just pushed (`raio-backend:v1`).
4. Architecture: `x86_64` (or `arm64` if your dependencies support it; GDAL works on both but x86_64 is safest).
5. Execution role: create a new role `raio-lambda-role` with the `AWSLambdaVPCAccessExecutionRole` managed policy. This lets the function connect to RDS inside the VPC.
6. Click **Create function**.

After creation:

1. Scroll to **Image configuration** → set `Command` to empty (the Dockerfile already defines the entrypoint) and add the environment variable `AWS_LAMBDA_EXEC_WRAPPER=/opt/aws-lambda-adapter`. This activates the AWS Lambda Web Adapter shipped in the Dockerfile.
2. In **Environment variables**, add the required Django variables:
   - `DJANGO_SETTINGS_MODULE=mobilidade.settings_prod`
   - `SECRET_KEY=<secret>`
   - `API_SHARED_SECRETS=<comma separated keys>`
   - `ALLOWED_HOSTS=<your-api-gateway-hostname>` (e.g. `abc123.execute-api.us-east-1.amazonaws.com`)
   - `CORS_ALLOWED_ORIGINS=https://<your-frontend-host>`
   - `DATABASE_URL=postgis://raio_api:<password>@raio-postgres.c123xyz.us-east-1.rds.amazonaws.com:5432/mobilidade`
   - Optionally: `DB_CONN_MAX_AGE=60`, `SERVICE_BASE_URL=https://<api-domain>`
3. Under **General configuration**, raise **Timeout** to `30 seconds` (default 3 seconds may be too short for cold starts).
4. To give Lambda network access to RDS:
   - Scroll to **VPC** → click **Edit** → select the default VPC, then choose at least two private subnets (e.g. `subnet-abc`, `subnet-def`).
   - Attach the security group `raio-lambda-sg` you created earlier.
   - Save changes. Lambda will now connect using private IPs and no longer needs the database to be publicly accessible. You can go back to the RDS console and switch **Public access** to `No` for better security.
5. If you stored secrets in Secrets Manager, attach the policy `SecretsManagerReadWrite` (or a scoped-down read policy) to the Lambda execution role and load secrets in your Django settings using environment variables or AWS SDK.

### Step B6. Create an API Gateway HTTP API to front the Lambda

1. Console → **API Gateway → Create API → HTTP API**.
2. Name: `RaioTransporte API`.
3. Integrations → **Add integration → Lambda function** → choose your region and function `raio-backend`.
4. Routes → add route `ANY /{proxy+}` with the Lambda integration. This sends all paths/methods to Django.
5. Deploy → create a stage `prod` (default stage works). Note the **Invoke URL** (e.g. `https://abc123.execute-api.us-east-1.amazonaws.com`).
6. Configure CORS (since Django enforces it too, align both):
   - API Gateway → your API → **CORS** → Enable CORS → Allow origins matching your frontend (`https://app.example.com`) and allow headers `Authorization,X-API-Key,Content-Type`.
7. Optionally attach a custom domain name and ACM certificate.

### Step B7. Test the live API

1. Visit the invoke URL in a browser: `https://abc123.execute-api.us-east-1.amazonaws.com/health/` (replace with an actual health endpoint if available).
2. Check **CloudWatch Logs** (Lambda → Monitor → Logs) for any errors.
3. If requests fail with 500 errors, double-check:
   - `ALLOWED_HOSTS` includes the API Gateway domain.
   - Database security groups allow the Lambda security group.
   - `AWS_LAMBDA_EXEC_WRAPPER` is set so the adapter runs.

### Step B8. Set up CI/CD (optional enhancement)

- Use **AWS CodeBuild** or GitHub Actions to automate image builds and pushes to ECR.
- Configure the pipeline to update the Lambda function via `aws lambda update-function-code --function-name raio-backend --image-uri ...` after pushing a new tag.

### Step B9. Observability and scaling tips

- Lambda automatically scales to zero when idle and scales up when requests arrive—no extra configuration needed.
- Monitor cold start time in CloudWatch. You can keep a provisioned concurrency of 1 if you need faster first-byte, but that costs extra.
- Set up **CloudWatch Alarms** for Lambda errors and RDS CPU/storage usage.
- Consider enabling RDS automatic minor version upgrades for patching.

---

## C. Connecting everything to the Flutter client

1. Update the Flutter app's API base URL to the API Gateway invoke URL or your custom domain.
2. Rotate the `X-API-Key` to match `API_SHARED_SECRET`/`API_SHARED_SECRETS` configured in Lambda.
3. Ensure the frontend origin is listed in both `CORS_ALLOWED_ORIGINS` (Django) and the API Gateway CORS settings.

---

## D. Cleaning up to save credits

When finished testing, delete resources to avoid charges:

1. API Gateway → Delete the API.
2. Lambda → Delete the function.
3. ECR → Delete unneeded images (you are charged for stored GB-months).
4. RDS → Delete the database (take a final snapshot first if needed).
5. S3 → Delete the backup bucket.
6. IAM → Remove unused users/roles/access keys.

---

## Appendix: Common troubleshooting

| Symptom | Possible cause | Fix |
| --- | --- | --- |
| Lambda logs show `ECONNREFUSED` to PostgreSQL | Security groups or subnet configuration incorrect | Ensure Lambda is in the same VPC/subnets as RDS and `raio-postgres-sg` allows inbound from `raio-lambda-sg`. |
| API Gateway returns 502 with message `Bad Gateway` | Lambda timed out or crashed before responding | Increase Lambda timeout to 30s+, verify `AWS_LAMBDA_EXEC_WRAPPER` env var, check CloudWatch logs for stack traces. |
| Django complains `ImproperlyConfigured: ALLOWED_HOSTS must include at least one host` | Missing environment variable | Set `ALLOWED_HOSTS` in Lambda env to include API Gateway domain and any custom domain. |
| Static files (admin CSS) 404 | `collectstatic` not run or storage misconfigured | The Dockerfile already runs `collectstatic`. Ensure `AWS_LAMBDA_EXEC_WRAPPER` is set so Gunicorn + WhiteNoise serve them. |
| CORS errors in browser | Origins not allowed | Align `CORS_ALLOWED_ORIGINS` in Lambda env and API Gateway CORS settings with your frontend origin. |

You now have a low-cost, scalable deployment path for the RaioTransporte back-end using AWS services. Iterate on automation as you grow—start with manual steps to learn the platform, then move to infrastructure-as-code once you're comfortable.
