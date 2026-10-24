#!/usr/bin/env bash
# Deploy the tools, fetch weights, and run the three small real requests in order.
# Requires Modal credentials and model keys in the environment (see README.md).
set -euo pipefail
cd "$(dirname "$0")/.."

export MODAL_TOKEN_ID="${MODAL_TOKEN_ID:-${MODAL_API_TOKEN_ID:-}}"
export MODAL_TOKEN_SECRET="${MODAL_TOKEN_SECRET:-${MODAL_API_TOKEN_SECRET:-}}"
export LABLOOP_STATE="${LABLOOP_STATE:-state}"

python -m labloop.cli probe
modal deploy modal_apps/tools_app.py
modal run modal_apps/tools_app.py::download_all
modal run modal_apps/tools_app.py::smoke

python -m labloop.cli run \
  --description "Predict the 3D structure of this short single-chain peptide and report whether the fold is confident." \
  --inputs '{"sequence": "GSHMKTAYIAKQRQISFVKSHFSRQLEERL"}'

COMPLEX='{"chain_a": "MKTAYIAKQRQISFVKSHFSRQ", "chain_b": "GSHMLEERLKALEEKLKALEEK"}'
python -m labloop.cli run \
  --description "Co-fold these two short protein chains with Boltz-2 using one seed and judge whether they form a confident interface." \
  --inputs "$COMPLEX"
python -m labloop.cli run \
  --description "Co-fold these two short protein chains with Boltz-2 using one seed and judge whether they form a confident interface." \
  --inputs "$COMPLEX"

python -m labloop.cli skills
