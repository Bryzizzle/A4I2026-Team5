#!/usr/bin/env bash
#
# Deploy MCP Toolbox for Databases to Cloud Run as a PRIVATE service (no public access).
# Sourced by deploy.sh (agent on Cloud Run) and deploy_agent_runtime.sh (agent on Agent Runtime);
# can also be run on its own:  bash agent/deploy_toolbox.sh
#
# After it runs, TOOLBOX_URL holds the service URL. Callers must grant roles/run.invoker on the
# `toolbox` service to whichever identity the agent runs as.

set -euo pipefail

PROJECT="${PROJECT:-$(gcloud config get-value project 2>/dev/null || true)}"
REGION="${REGION:-us-central1}"
DATASET="${DATASET:-a4i_health}"
TOOLBOX_VERSION="${TOOLBOX_VERSION:-1.17.0}"
AGENT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TB_SA="toolbox-identity@${PROJECT}.iam.gserviceaccount.com"

# New service accounts take up to a minute to become visible to IAM ("does not exist").
# Retry a binding command until it succeeds or ~2 minutes pass.
retry_bind() {
  local i
  for i in $(seq 1 12); do
    if "$@" >/dev/null 2>&1; then return 0; fi
    echo "   waiting for IAM to see the new service account (attempt ${i}/12)..."
    sleep 10
  done
  "$@" >/dev/null   # final attempt, with its error shown
}

if [ -z "${PROJECT}" ] || [ "${PROJECT}" = "(unset)" ]; then
  echo "No project. Run: gcloud config set project YOUR_PROJECT_ID" >&2; exit 1
fi
echo "Project ${PROJECT}  Region ${REGION}  Dataset ${DATASET}"

echo "== APIs"
gcloud services enable run.googleapis.com secretmanager.googleapis.com \
  artifactregistry.googleapis.com cloudbuild.googleapis.com aiplatform.googleapis.com \
  bigquery.googleapis.com --project "${PROJECT}"

echo "== Toolbox service account"
gcloud iam service-accounts describe "${TB_SA}" --project "${PROJECT}" >/dev/null 2>&1 \
  || gcloud iam service-accounts create toolbox-identity --project "${PROJECT}"
for role in roles/bigquery.dataViewer roles/bigquery.jobUser; do
  retry_bind gcloud projects add-iam-policy-binding "${PROJECT}" \
    --member "serviceAccount:${TB_SA}" --role "${role}" --condition=None --quiet
done

echo "== Toolbox config -> Secret Manager"
sed -e "s|{{PROJECT}}|${PROJECT}|g" -e "s|{{DATASET}}|${DATASET}|g" \
    "${AGENT_DIR}/toolbox/tools.yaml.tmpl" > "${AGENT_DIR}/toolbox/tools.yaml"
if gcloud secrets describe tools --project "${PROJECT}" >/dev/null 2>&1; then
  gcloud secrets versions add tools --data-file="${AGENT_DIR}/toolbox/tools.yaml" --project "${PROJECT}"
else
  gcloud secrets create tools --data-file="${AGENT_DIR}/toolbox/tools.yaml" --project "${PROJECT}"
fi
retry_bind gcloud secrets add-iam-policy-binding tools --member "serviceAccount:${TB_SA}" \
  --role roles/secretmanager.secretAccessor --project "${PROJECT}"

echo "== Deploy toolbox (private)"
gcloud run deploy toolbox \
  --image "us-central1-docker.pkg.dev/database-toolbox/toolbox/toolbox:${TOOLBOX_VERSION}" \
  --service-account "${TB_SA}" --region "${REGION}" --project "${PROJECT}" \
  --no-allow-unauthenticated \
  --set-secrets "/app/tools.yaml=tools:latest" \
  --args="--config=/app/tools.yaml","--address=0.0.0.0","--port=8080"
TOOLBOX_URL="$(gcloud run services describe toolbox --region "${REGION}" --project "${PROJECT}" \
               --format 'value(status.url)')"
export TOOLBOX_URL
echo "   toolbox: ${TOOLBOX_URL}"
