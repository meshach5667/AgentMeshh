#!/usr/bin/env bash
# AgentMesh worker installer (Linux and macOS). Installs for the current user only; never needs root.
#
#   ./install.sh --control-plane https://agentmesh.example.com --token am_enroll_... \
#       [--max-ram-mb 8192] [--max-cpu 4] [--max-disk-mb 30000] [--schedule "mon-fri 18:00-08:00"] \
#       [--outside-schedule pause|drain] [--wheel path/to/agentmesh_worker-*.whl] [--name agentmesh-worker] \
#       [--prefix ~/.local/share/agentmesh] [--update-public-key KEY] [--no-service] [--linger] [--yes]
#
# What it does: checks prerequisites, creates a private Python environment under --prefix, writes
# ~/.config/agentmesh/<name>.env (0600), enrolls this machine with the one-time token, and installs a
# per-user background service. It does NOT install, configure, or touch Ollama, and does not change system
# settings. Remove everything with uninstall.sh.
set -euo pipefail

CONTROL_PLANE="" TOKEN="" WHEEL="" NAME="agentmesh-worker" PREFIX="${HOME}/.local/share/agentmesh"
MAX_CPU="" MAX_RAM="" MAX_DISK="" SCHEDULE="" OUTSIDE="pause" OLLAMA_BIN="" UPDATE_KEY=""
SERVICE=1 LINGER="" ASSUME_YES=0 INSECURE="false"

die() { echo "error: $*" >&2; exit 1; }
say() { echo "==> $*"; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --control-plane) CONTROL_PLANE="$2"; shift 2 ;;
    --token) TOKEN="$2"; shift 2 ;;
    --wheel) WHEEL="$2"; shift 2 ;;
    --name) NAME="$2"; shift 2 ;;
    --prefix) PREFIX="$2"; shift 2 ;;
    --max-cpu) MAX_CPU="$2"; shift 2 ;;
    --max-ram-mb) MAX_RAM="$2"; shift 2 ;;
    --max-disk-mb) MAX_DISK="$2"; shift 2 ;;
    --schedule) SCHEDULE="$2"; shift 2 ;;
    --outside-schedule) OUTSIDE="$2"; shift 2 ;;
    --ollama) OLLAMA_BIN="$2"; shift 2 ;;
    --update-public-key) UPDATE_KEY="$2"; shift 2 ;;
    --allow-insecure-http) INSECURE="true"; shift ;;
    --no-service) SERVICE=0; shift ;;
    --linger) LINGER="--linger"; shift ;;
    --yes|-y) ASSUME_YES=1; shift ;;
    -h|--help) sed -n '2,15p' "$0"; exit 0 ;;
    *) die "unknown option $1 (see --help)" ;;
  esac
done

[[ "$(id -u)" != "0" ]] || die "do not run as root; the worker installs for your user"
[[ -n "$CONTROL_PLANE" ]] || die "--control-plane is required"
[[ "$NAME" =~ ^[A-Za-z0-9._-]{1,64}$ ]] || die "--name may only contain letters, digits, '.', '_' and '-'"
case "$(uname -s)" in Linux|Darwin) ;; *) die "unsupported OS $(uname -s); use the Docker worker" ;; esac

PY="${PYTHON:-python3}"
command -v "$PY" >/dev/null || die "python3 not found (3.11+ required)"
"$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' \
  || die "Python 3.11+ required, found $("$PY" -V 2>&1)"
"$PY" -c 'import venv' 2>/dev/null || die "python3 venv module missing (Debian/Ubuntu: apt install python3-venv)"

if [[ -z "$OLLAMA_BIN" ]]; then OLLAMA_BIN="$(command -v ollama || true)"; fi
[[ -n "$OLLAMA_BIN" && -x "$OLLAMA_BIN" ]] || die "Ollama not found. Install it from https://ollama.com/download first.
AgentMesh never installs or modifies Ollama; it runs its own isolated instances using your installed binary."

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -z "$WHEEL" ]]; then
  WHEEL="$(ls -t "$HERE"/../dist/agentmesh_worker-*.whl "$HERE"/agentmesh_worker-*.whl 2>/dev/null | head -1 || true)"
fi
[[ -n "$WHEEL" && -f "$WHEEL" ]] || die "worker wheel not found; pass --wheel or run scripts/build_worker_wheel.py"

CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/agentmesh"
CONFIG="$CONFIG_DIR/$NAME.env"
DATA_DIR="$PREFIX/$NAME"
VENV="$PREFIX/venv-$NAME"

say "Installing AgentMesh worker '$NAME'"
echo "    control plane: $CONTROL_PLANE"
echo "    environment:   $VENV"
echo "    config:        $CONFIG"
echo "    data:          $DATA_DIR"
echo "    ollama:        $OLLAMA_BIN (used read-only; your own Ollama service is not touched)"
if [[ $ASSUME_YES -eq 0 && -t 0 ]]; then
  read -r -p "Continue? [y/N] " answer; [[ "$answer" =~ ^[Yy] ]] || die "aborted"
fi

[[ ! -e "$CONFIG" ]] || die "$CONFIG already exists; run uninstall.sh --name $NAME first"

say "Creating Python environment"
mkdir -p "$PREFIX" && chmod 700 "$PREFIX"
"$PY" -m venv "$VENV"
"$VENV/bin/pip" install --quiet --disable-pip-version-check "$WHEEL"

say "Writing configuration"
mkdir -p "$CONFIG_DIR" && chmod 700 "$CONFIG_DIR"
umask 077
{
  echo "# AgentMesh worker '$NAME' - written by install.sh. Edit, then: agentmesh-worker service install --name $NAME"
  echo "AGENTMESH_CONTROL_PLANE_URL=$CONTROL_PLANE"
  echo "AGENTMESH_ALLOW_INSECURE_CONTROL_PLANE=$INSECURE"
  echo "AGENTMESH_MODE=agent"
  echo "AGENTMESH_NODE_NAME=$NAME"
  echo "AGENTMESH_DATA_DIR=$DATA_DIR"
  echo "AGENTMESH_OLLAMA_BINARY=$OLLAMA_BIN"
  [[ -n "$MAX_CPU" ]] && echo "AGENTMESH_MAX_CPU_CORES=$MAX_CPU"
  [[ -n "$MAX_RAM" ]] && echo "AGENTMESH_MAX_RAM_MB=$MAX_RAM"
  [[ -n "$MAX_DISK" ]] && echo "AGENTMESH_MAX_DISK_MB=$MAX_DISK"
  [[ -n "$SCHEDULE" ]] && echo "AGENTMESH_AVAILABILITY_SCHEDULE=\"$SCHEDULE\""
  echo "AGENTMESH_OUTSIDE_SCHEDULE=$OUTSIDE"
  [[ -n "$UPDATE_KEY" ]] && echo "AGENTMESH_UPDATE_PUBLIC_KEY=$UPDATE_KEY"
  true
} > "$CONFIG"
export AGENTMESH_CONFIG_FILE="$CONFIG"
# Keep the installed wheel so a failed signed update can roll back to it.
mkdir -p "$DATA_DIR/releases" && chmod 700 "$DATA_DIR"
cp "$WHEEL" "$DATA_DIR/releases/"

say "Checking this machine"
"$VENV/bin/agentmesh-worker" hardware | sed 's/^/    /'

if [[ -z "$TOKEN" ]]; then
  [[ -t 0 ]] || die "--token is required when not interactive"
  read -r -s -p "Enrollment token (from the provider dashboard): " TOKEN; echo
fi
say "Enrolling"
"$VENV/bin/agentmesh-worker" enroll --token "$TOKEN"

if [[ $SERVICE -eq 1 ]]; then
  say "Installing background service"
  "$VENV/bin/agentmesh-worker" service install --name "$NAME" $LINGER
fi

echo
say "Done. Useful commands:"
echo "    $VENV/bin/agentmesh-worker status        (with AGENTMESH_CONFIG_FILE=$CONFIG)"
echo "    $VENV/bin/agentmesh-worker doctor"
echo "    $VENV/bin/agentmesh-worker pause | drain | resume"
echo "    $HERE/uninstall.sh --name $NAME"
