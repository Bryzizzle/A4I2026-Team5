#!/usr/bin/env bash
#
# Run the Clinic Plan agents in Cloud Shell, with adk web, against your BigQuery views.
# Prerequisite: bash data/run_sql.sh has built v_van_need, v_coverage and the audit views.
#
#     bash agent/run_local.sh
#
# Then: Web Preview -> Preview on port 8080, pick "clinic_planner", and ask
#       "Plan next month's four Saturdays."
#
# What it does: renders the MCP Toolbox config, downloads the Toolbox server (once), starts it on
# port 5000 in the background, installs the Python deps into ~/.venvs/a4i, writes
# agent/clinic_planner/.env if missing, and starts adk web on port 8080.

set -euo pipefail

TOOLBOX_VERSION="${TOOLBOX_VERSION:-1.17.0}"
PROJECT="${PROJECT:-$(gcloud config get-value project 2>/dev/null || true)}"
DATASET="${DATASET:-a4i_health}"
HERE="$(cd "$(dirname "$0")" && pwd)"

if [ -z "${PROJECT}" ] || [ "${PROJECT}" = "(unset)" ]; then
  echo "No project. Run: gcloud config set project YOUR_PROJECT_ID" >&2
  exit 1
fi

echo "== Rendering toolbox/tools.yaml for ${PROJECT}.${DATASET}"
sed -e "s|{{PROJECT}}|${PROJECT}|g" -e "s|{{DATASET}}|${DATASET}|g" \
    "${HERE}/toolbox/tools.yaml.tmpl" > "${HERE}/toolbox/tools.yaml"

if [ ! -x "${HERE}/toolbox/toolbox" ]; then
  echo "== Downloading MCP Toolbox v${TOOLBOX_VERSION}"
  curl -sSL -o "${HERE}/toolbox/toolbox" \
    "https://storage.googleapis.com/mcp-toolbox-for-databases/v${TOOLBOX_VERSION}/linux/amd64/toolbox"
  chmod +x "${HERE}/toolbox/toolbox"
fi

echo "== Starting MCP Toolbox on :5000 (log: agent/toolbox/toolbox.log)"
pkill -f "toolbox/toolbox --config" 2>/dev/null || true
"${HERE}/toolbox/toolbox" --config "${HERE}/toolbox/tools.yaml" --port 5000 \
  > "${HERE}/toolbox/toolbox.log" 2>&1 &
TOOLBOX_PID=$!
trap 'kill ${TOOLBOX_PID} 2>/dev/null || true' EXIT
for _ in $(seq 1 20); do
  if curl -s -o /dev/null "http://127.0.0.1:5000/"; then break; fi
  if ! kill -0 "${TOOLBOX_PID}" 2>/dev/null; then
    echo "Toolbox exited. Its log:" >&2; cat "${HERE}/toolbox/toolbox.log" >&2; exit 1
  fi
  sleep 0.5
done
echo "   toolbox is up"

echo "== Python environment (~/.venvs/a4i)"
if [ ! -d "${HOME}/.venvs/a4i" ]; then python3 -m venv "${HOME}/.venvs/a4i"; fi
# shellcheck disable=SC1091
source "${HOME}/.venvs/a4i/bin/activate"
pip install -q -r "${HERE}/clinic_planner/requirements.txt" pyyaml

if [ ! -f "${HERE}/clinic_planner/.env" ]; then
  sed -e "s|your-project-id|${PROJECT}|" -e "s|a4i_health|${DATASET}|" \
      "${HERE}/clinic_planner/.env.example" > "${HERE}/clinic_planner/.env"
  echo "   wrote agent/clinic_planner/.env"
fi

echo "== Offline tests"
(cd "${HERE}" && python -m unittest test_offline)

echo "== adk web on :8080. Open Web Preview -> port 8080. Ctrl+C stops both servers."
cd "${HERE}"
# Web Preview serves the UI from https://8080-<id>.cloudshell.dev through a proxy, so the browser's
# Origin never matches the forwarded Host and ADK's origin check answers 403. Allow that domain.
adk web --host 0.0.0.0 --port 8080 \
  --allow_origins "regex:https://.*\.cloudshell\.dev" \
  --allow_origins "regex:https://.*\.cloudshell\.dev:[0-9]+"
