#!/usr/bin/env bash
# Remove an AgentMesh worker installed by install.sh: stops the service and all managed workloads, deletes
# credentials, configuration, the private Python environment, and (with --purge-models) downloaded models.
# Revoke the node in the provider dashboard as well.
#
#   ./uninstall.sh [--name agentmesh-worker] [--prefix ~/.local/share/agentmesh] [--purge-models] [--yes]
set -euo pipefail

NAME="agentmesh-worker" PREFIX="${HOME}/.local/share/agentmesh" PURGE="" ASSUME_YES=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --name) NAME="$2"; shift 2 ;;
    --prefix) PREFIX="$2"; shift 2 ;;
    --purge-models) PURGE="--purge-models"; shift ;;
    --yes|-y) ASSUME_YES=1; shift ;;
    -h|--help) sed -n '2,7p' "$0"; exit 0 ;;
    *) echo "unknown option $1" >&2; exit 1 ;;
  esac
done
[[ "$NAME" =~ ^[A-Za-z0-9._-]{1,64}$ ]] || { echo "invalid --name" >&2; exit 1; }

CONFIG="${XDG_CONFIG_HOME:-$HOME/.config}/agentmesh/$NAME.env"
VENV="$PREFIX/venv-$NAME"
DATA_DIR="$PREFIX/$NAME"

echo "This removes worker '$NAME': service, workloads, credentials, $CONFIG, $VENV${PURGE:+, and models in $DATA_DIR}."
if [[ $ASSUME_YES -eq 0 && -t 0 ]]; then
  read -r -p "Continue? [y/N] " answer; [[ "$answer" =~ ^[Yy] ]] || exit 1
fi

if [[ -x "$VENV/bin/agentmesh-worker" && -f "$CONFIG" ]]; then
  AGENTMESH_CONFIG_FILE="$CONFIG" "$VENV/bin/agentmesh-worker" uninstall --service "$NAME" $PURGE --remove-config
elif [[ -x "$VENV/bin/agentmesh-worker" ]]; then
  "$VENV/bin/agentmesh-worker" service uninstall --name "$NAME" || true
fi
rm -f "$CONFIG"
rmdir "$(dirname "$CONFIG")" 2>/dev/null || true
rm -rf "$VENV"
if [[ -n "$PURGE" ]]; then rm -rf "$DATA_DIR"; fi
rmdir "$PREFIX" 2>/dev/null || true
echo "Removed. Remember to revoke the node in the provider dashboard."
