#!/usr/bin/env bash
#
# Deploy to Cloud Run, from the repo root in Cloud Shell:
#
#     bash agent/deploy.sh
#
# Two services:
#   toolbox          MCP Toolbox for Databases (Google's image), PRIVATE: only the agent may call it
#   clinic-planner   the ADK agents with the adk web UI
#
# Service account clinic-agent: Vertex AI (Gemini), BigQuery read + jobs (plan_saturdays),
# and permission to invoke the toolbox.
#
# Safe to re-run. Override REGION, PROJECT, DATASET, TOOLBOX_VERSION as environment variables.
# NOTE: the agent service is deployed --allow-unauthenticated so judges can open the demo URL.
# Remove that flag (and use `gcloud run services proxy`) if you do not want it public.
#
# For Agent Runtime instead of Cloud Run, use agent/deploy_agent_runtime.sh.

set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"

# shellcheck source=deploy_toolbox.sh
source "${HERE}/deploy_toolbox.sh"     # sets PROJECT, REGION, DATASET, TOOLBOX_URL

AG_SA="clinic-agent@${PROJECT}.iam.gserviceaccount.com"

echo "== Agent service account"
gcloud iam service-accounts describe "${AG_SA}" --project "${PROJECT}" >/dev/null 2>&1 \
  || gcloud iam service-accounts create clinic-agent --project "${PROJECT}"
for role in roles/bigquery.dataViewer roles/bigquery.jobUser roles/aiplatform.user; do
  retry_bind gcloud projects add-iam-policy-binding "${PROJECT}" \
    --member "serviceAccount:${AG_SA}" --role "${role}" --condition=None --quiet
done
retry_bind gcloud run services add-iam-policy-binding toolbox --member "serviceAccount:${AG_SA}" \
  --role roles/run.invoker --region "${REGION}" --project "${PROJECT}"

echo "== Deploy clinic-planner (adk web UI)"
# shellcheck disable=SC1091
[ -d "${HOME}/.venvs/a4i" ] && source "${HOME}/.venvs/a4i/bin/activate"
command -v adk >/dev/null || pip install -q -r "${HERE}/clinic_planner/requirements.txt"
adk deploy cloud_run --project "${PROJECT}" --region "${REGION}" \
  --service_name clinic-planner --with_ui "${HERE}/clinic_planner" -- \
  --service-account "${AG_SA}" --allow-unauthenticated \
  --set-env-vars "GOOGLE_GENAI_USE_VERTEXAI=TRUE,GOOGLE_CLOUD_PROJECT=${PROJECT},A4I_PROJECT=${PROJECT},GOOGLE_CLOUD_LOCATION=global,A4I_MODEL=gemini-3.6-flash,A4I_DATASET=${DATASET},TOOLBOX_URL=${TOOLBOX_URL}"

echo
echo "Done. Agent UI: $(gcloud run services describe clinic-planner --region "${REGION}" \
  --project "${PROJECT}" --format 'value(status.url)')"
