#!/usr/bin/env bash
# Shared helpers for Codex/Codespaces environment management.

# shellcheck shell=bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PYTHON_BIN="python3"
VENV_PATH="$REPO_ROOT/.venv"
REQUIREMENTS_FILE="$REPO_ROOT/mobilidade/requirements.txt"
ENV_TEMPLATE="$REPO_ROOT/.env.example"
ENV_FILE="$REPO_ROOT/.env"
APT_PACKAGES=(
  build-essential
  gdal-bin
  libgdal-dev
  libproj-dev
  libpq-dev
  python3-dev
  python3-venv
)

command_exists() {
  command -v "$1" >/dev/null 2>&1
}

run_with_sudo() {
  if command_exists sudo; then
    sudo "$@"
  else
    "$@"
  fi
}

ensure_apt_packages() {
  local missing=()
  for pkg in "${APT_PACKAGES[@]}"; do
    if ! dpkg -s "$pkg" >/dev/null 2>&1; then
      missing+=("$pkg")
    fi
  done

  if [ "${#missing[@]}" -gt 0 ]; then
    run_with_sudo apt-get update
    run_with_sudo apt-get install -y --no-install-recommends "${missing[@]}"
  fi
}

create_or_update_venv() {
  if [ ! -d "$VENV_PATH" ]; then
    "$PYTHON_BIN" -m venv "$VENV_PATH"
  fi

  # shellcheck disable=SC1090
  source "$VENV_PATH/bin/activate"
  python -m pip install --upgrade pip setuptools wheel
}

install_python_dependencies() {
  if [ ! -f "$REQUIREMENTS_FILE" ]; then
    echo "Requirements file not found: $REQUIREMENTS_FILE" >&2
    exit 1
  fi
  python -m pip install --upgrade --requirement "$REQUIREMENTS_FILE"
}

bootstrap_dotenv() {
  if [ -f "$ENV_TEMPLATE" ] && [ ! -f "$ENV_FILE" ]; then
    cp "$ENV_TEMPLATE" "$ENV_FILE"
  fi
}
