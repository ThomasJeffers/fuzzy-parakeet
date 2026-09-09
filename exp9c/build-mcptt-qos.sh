#!/usr/bin/env bash
# Rebuild PCRF (+ optional P-CSCF) offline from already-patched trees.
# Does NOT re-run apply-mcptt-qos.py (that caused the duplicate-member failure).
# Apply once yourself, then build:
#   python3 apply-mcptt-qos.py --open5gs ... --kamailio ...
#   ./build-mcptt-qos.sh
set -euo pipefail

ROOT="${DOCKER_OPEN5GS:-$HOME/docker_open5gs}"
COMPOSE="${COMPOSE_FILE:-$ROOT/4g-volte-deploy.yaml}"

echo "== Rebuild Open5GS base image (local tree; no wiping checkout) =="
cd "$ROOT/base"
docker build --force-rm -t open5gs .

echo "== Recreate PCRF =="
cd "$ROOT"
docker compose -f "$COMPOSE" up -d --force-recreate --no-deps pcrf

if [[ "${REBUILD_PCSCF:-1}" == "1" ]]; then
  echo "== Rebuild / recreate P-CSCF if ims_base Dockerfile exists =="
  if [[ -f "$ROOT/ims_base/Dockerfile" ]]; then
    docker build --force-rm -t pcscf "$ROOT/ims_base" || \
      docker build --force-rm -t docker_open5gs_pcscf "$ROOT/ims_base" || true
  fi
  docker compose -f "$COMPOSE" up -d --force-recreate --no-deps pcscf || true
fi

echo
echo "Verify:"
echo "  docker logs pcrf 2>&1 | grep -E 'AF-Application-Identifier|Rx media policy'"
