#!/usr/bin/env bash
# Refresh a cached Codex/Codespaces container before running the backend.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/common.sh"

cd "$REPO_ROOT"

echo "[codex] Verifying system dependencies..."
ensure_apt_packages

if [ -d "$VENV_PATH" ]; then
  # shellcheck disable=SC1090
  source "$VENV_PATH/bin/activate"
else
  echo "[codex] Virtual environment missing. Recreating..."
  create_or_update_venv
fi

# Ensure base tooling is always current.
python -m pip install --upgrade pip setuptools wheel

echo "[codex] Syncing Python dependencies..."
install_python_dependencies

echo "[codex] Ensuring .env exists for local overrides..."
bootstrap_dotenv

echo "Codex maintenance complete. Activate the environment with: source .venv/bin/activate"
