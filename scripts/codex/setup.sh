#!/usr/bin/env bash
# Provision a fresh Codespaces/Codex container for the Django backend.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/common.sh"

cd "$REPO_ROOT"

echo "[codex] Ensuring system packages for GeoDjango are present..."
ensure_apt_packages

echo "[codex] Creating/upgrading Python virtual environment..."
create_or_update_venv

echo "[codex] Installing Python dependencies from mobilidade/requirements.txt..."
install_python_dependencies

echo "[codex] Bootstrapping local .env file (if missing)..."
bootstrap_dotenv

cat <<'MSG'

Codex environment is ready.
Activate it with:
  source .venv/bin/activate

Database configuration is left untouched. Update .env if you need custom connection details.
MSG
