#!/usr/bin/env bash
#
# Deploy the agents to Agent Runtime (Vertex AI Agent Engine), from the repo root in Cloud Shell:
#
#     bash agent/deploy_agent_runtime.sh
#
# Then talk to it:
#
#     python3 agent/query_agent_runtime.py "Plan next month's four Saturdays."
#
# What gets deployed:
#   toolbox          Cloud Run, PRIVATE (Agent Runtime hosts the agent, not the MCP server)
#   clinic-planner   Agent Runtime: the ADK agent tree, sessions managed by Agent Runtime
#
# Agent Runtime runs the agent as the Reasoning Engine service agent
#   service-<PROJECT_NUMBER>@gcp-sa-aiplatform-re.iam.gserviceaccount.com
# which this script grants BigQuery read + jobs and permission to invoke the toolbox.
# Re-running updates the same Agent Runtime instance (its id is kept in agent/.agent_runtime_id).
#
# Takes 5-10 minutes: Agent Runtime builds a container image.

set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"

# shellcheck source=deploy_toolbox.sh
source "${HERE}/deploy_toolbox.sh"     # sets PROJECT, REGION, DATASET, TOOLBOX_URL

PROJECT_NUMBER="$(gcloud projects describe "${PROJECT}" --format 'value(projectNumber)')"
RE_SA="service-${PROJECT_NUMBER}@gcp-sa-aiplatform-re.iam.gserviceaccount.com"
ENV_FILE="${HERE}/.agent_runtime.env"
ID_FILE="${HERE}/.agent_runtime_id"

echo "== Python environment (~/.venvs/a4i)"
if [ ! -d "${HOME}/.venvs/a4i" ]; then python3 -m venv "${HOME}/.venvs/a4i"; fi
# shellcheck disable=SC1091
source "${HOME}/.venvs/a4i/bin/activate"
# The gcp extra pins a google-cloud-aiplatform compatible with ADK 2.7.0.
pip install -q "google-adk[toolbox,gcp]==2.7.0" pyyaml

echo "== Agent Runtime environment (${ENV_FILE})"
# No GOOGLE_CLOUD_PROJECT / GOOGLE_CLOUD_LOCATION here: the platform owns those. The agent reads
# A4I_PROJECT for BigQuery and A4I_MODEL_LOCATION for the Gemini endpoint instead.
cat > "${ENV_FILE}" <<EOF
GOOGLE_GENAI_USE_VERTEXAI=TRUE
A4I_PROJECT=${PROJECT}
A4I_DATASET=${DATASET}
A4I_MODEL=gemini-3.6-flash
A4I_MODEL_LOCATION=global
TOOLBOX_URL=${TOOLBOX_URL}
EOF

ID_ARG=()
if [ -s "${ID_FILE}" ]; then
  ID_ARG=(--agent_engine_id "$(cat "${ID_FILE}")")
  echo "   updating existing instance $(cat "${ID_FILE}")"
fi

echo "== Deploy to Agent Runtime (5-10 minutes)"
LOG="$(mktemp)"
adk deploy agent_engine \
  --project "${PROJECT}" --region "${REGION}" \
  --display_name clinic-planner \
  --description "Decides where one mobile clinic parks on four Saturdays, audits who the plan lands on, and explains it to the neighborhoods." \
  --env_file "${ENV_FILE}" \
  ${ID_ARG[@]+"${ID_ARG[@]}"} \
  "${HERE}/clinic_planner" 2>&1 | tee "${LOG}"

RESOURCE="$(grep -oE 'projects/[^ ]+/reasoningEngines/[0-9]+' "${LOG}" | tail -1 || true)"
if [ -z "${RESOURCE}" ]; then
  echo "Could not find the deployed resource name in the output above." >&2; exit 1
fi
echo "${RESOURCE}" > "${ID_FILE}"

echo "== Permissions for the Agent Runtime identity (${RE_SA})"
for role in roles/bigquery.dataViewer roles/bigquery.jobUser roles/aiplatform.user; do
  retry_bind gcloud projects add-iam-policy-binding "${PROJECT}" \
    --member "serviceAccount:${RE_SA}" --role "${role}" --condition=None --quiet
done
retry_bind gcloud run services add-iam-policy-binding toolbox --member "serviceAccount:${RE_SA}" \
  --role roles/run.invoker --region "${REGION}" --project "${PROJECT}"

echo
echo "Done. Agent Runtime resource: ${RESOURCE}"
echo "Try it:  python3 agent/query_agent_runtime.py \"Plan next month's four Saturdays.\""
echo "(Permissions can take a minute or two to apply after the first deploy.)"
