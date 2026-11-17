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
# Two service accounts, least privilege:
#   toolbox-identity  BigQuery read + jobs
#   clinic-agent      Vertex AI (Gemini), BigQuery read + jobs (plan_saturdays), invoke toolbox
#
# Safe to re-run. Override REGION, PROJECT, DATASET, TOOLBOX_VERSION as environment variables.
# NOTE: the agent service is deployed --allow-unauthenticated so judges can open the demo URL.
# Remove that flag (and use `gcloud run services proxy`) if you do not want it public.

set -euo pipefail

PROJECT="${PROJECT:-$(gcloud config get-value project 2>/dev/null || true)}"
REGION="${REGION:-us-central1}"
DATASET="${DATASET:-a4i_health}"
TOOLBOX_VERSION="${TOOLBOX_VERSION:-1.17.0}"
HERE="$(cd "$(dirname "$0")" && pwd)"
TB_SA="toolbox-identity@${PROJECT}.iam.gserviceaccount.com"
AG_SA="clinic-agent@${PROJECT}.iam.gserviceaccount.com"

if [ -z "${PROJECT}" ] || [ "${PROJECT}" = "(unset)" ]; then
  echo "No project. Run: gcloud config set project YOUR_PROJECT_ID" >&2; exit 1
fi
echo "Project ${PROJECT}  Region ${REGION}  Dataset ${DATASET}"

echo "== APIs"
gcloud services enable run.googleapis.com secretmanager.googleapis.com \
  artifactregistry.googleapis.com cloudbuild.googleapis.com aiplatform.googleapis.com \
  bigquery.googleapis.com --project "${PROJECT}"

echo "== Service accounts"
for sa in toolbox-identity clinic-agent; do
  gcloud iam service-accounts describe "${sa}@${PROJECT}.iam.gserviceaccount.com" \
      --project "${PROJECT}" >/dev/null 2>&1 \
    || gcloud iam service-accounts create "${sa}" --project "${PROJECT}"
done
bind() { gcloud projects add-iam-policy-binding "${PROJECT}" --member "serviceAccount:$1" \
           --role "$2" --condition=None --quiet >/dev/null; }
bind "${TB_SA}" roles/bigquery.dataViewer
bind "${TB_SA}" roles/bigquery.jobUser
bind "${AG_SA}" roles/bigquery.dataViewer
bind "${AG_SA}" roles/bigquery.jobUser
bind "${AG_SA}" roles/aiplatform.user
# The audit views read bigquery-public-data, which every account can read.

echo "== Toolbox config -> Secret Manager"
sed -e "s|{{PROJECT}}|${PROJECT}|g" -e "s|{{DATASET}}|${DATASET}|g" \
    "${HERE}/toolbox/tools.yaml.tmpl" > "${HERE}/toolbox/tools.yaml"
if gcloud secrets describe tools --project "${PROJECT}" >/dev/null 2>&1; then
  gcloud secrets versions add tools --data-file="${HERE}/toolbox/tools.yaml" --project "${PROJECT}"
else
  gcloud secrets create tools --data-file="${HERE}/toolbox/tools.yaml" --project "${PROJECT}"
fi
gcloud secrets add-iam-policy-binding tools --member "serviceAccount:${TB_SA}" \
  --role roles/secretmanager.secretAccessor --project "${PROJECT}" >/dev/null

echo "== Deploy toolbox (private)"
gcloud run deploy toolbox \
  --image "us-central1-docker.pkg.dev/database-toolbox/toolbox/toolbox:${TOOLBOX_VERSION}" \
  --service-account "${TB_SA}" --region "${REGION}" --project "${PROJECT}" \
  --no-allow-unauthenticated \
  --set-secrets "/app/tools.yaml=tools:latest" \
  --args="--config=/app/tools.yaml","--address=0.0.0.0","--port=8080"
TOOLBOX_URL="$(gcloud run services describe toolbox --region "${REGION}" --project "${PROJECT}" \
               --format 'value(status.url)')"
gcloud run services add-iam-policy-binding toolbox --member "serviceAccount:${AG_SA}" \
  --role roles/run.invoker --region "${REGION}" --project "${PROJECT}" >/dev/null
echo "   toolbox: ${TOOLBOX_URL}"

echo "== Deploy clinic-planner (adk web UI)"
# shellcheck disable=SC1091
[ -d "${HOME}/.venvs/a4i" ] && source "${HOME}/.venvs/a4i/bin/activate"
command -v adk >/dev/null || pip install -q -r "${HERE}/clinic_planner/requirements.txt"
adk deploy cloud_run --project "${PROJECT}" --region "${REGION}" \
  --service_name clinic-planner --with_ui "${HERE}/clinic_planner" -- \
  --service-account "${AG_SA}" --allow-unauthenticated \
  --set-env-vars "GOOGLE_GENAI_USE_VERTEXAI=TRUE,GOOGLE_CLOUD_PROJECT=${PROJECT},GOOGLE_CLOUD_LOCATION=global,A4I_MODEL=gemini-3.6-flash,A4I_DATASET=${DATASET},TOOLBOX_URL=${TOOLBOX_URL}"

echo
echo "Done. Agent UI: $(gcloud run services describe clinic-planner --region "${REGION}" \
  --project "${PROJECT}" --format 'value(status.url)')"
