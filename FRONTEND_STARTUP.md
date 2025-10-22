# Running the Real-Time Monitor Front End

This project ships a Django template-based front end for the real-time reach
monitor. Follow the steps below to launch it together with the API using the
same `runserver` process on port `18001`.

## 1. Prepare your environment

1. **Create/activate the existing Conda environment** (recommended):
   ```bash
   conda env create -f mobilidade/environment.yml  # first run only
   conda activate mobilidade
   ```
   Alternatively, create a virtualenv and install `mobilidade/requirements.txt`.

2. **Create a `.env` file** inside the `mobilidade/` folder so Django can load
   the development defaults:
   ```bash
   cd mobilidade
   copy NUL .env  # Windows
   # or: touch .env  # macOS/Linux
   ```

   Populate the file with the minimum configuration:
   ```ini
   DEBUG=True
   SECRET_KEY=dev-secret
   ALLOWED_HOSTS=localhost,127.0.0.1,0.0.0.0
   API_SHARED_SECRET=choose-a-strong-key
   ```

   The `API_SHARED_SECRET` is required so that the web UI can authenticate
   requests to the `/transporte/api/` endpoints by passing the value in the
   **Chave de API** field.

3. **Apply database migrations** (first run only):
   ```bash
   python manage.py migrate
   ```

## 2. Start the development server

Run the Django server bound to all interfaces on port `18001`:

```bash
python manage.py runserver 0.0.0.0:18001
```

With the defaults in `settings.py`, the host bindings `localhost`, `127.0.0.1`
and `0.0.0.0` are already trusted, so no extra configuration is needed when
using this port locally.

## 3. Access the real-time front end

- Navigate to <http://localhost:18001/> (the root URL now serves the monitor).
- Fill the latitude, longitude, desired time horizon, and optionally paste the
  same API key configured in `.env` into the **Chave de API** field.
- Click **Iniciar monitoramento** to start the streaming calculation.

### Helpful endpoints

- Front end: <http://localhost:18001/> (alias <http://localhost:18001/transporte/>)
- API (JSON): `POST http://localhost:18001/transporte/api/raio/`
- Streaming API: `POST http://localhost:18001/transporte/api/raio/stream/`

> **Tip:** If you plan to expose the server beyond localhost, adjust the
> `ALLOWED_HOSTS`, `CORS_ALLOWED_ORIGINS`, and `CSRF_TRUSTED_ORIGINS` values in
> `.env` to match the public hostname before running `runserver`.
