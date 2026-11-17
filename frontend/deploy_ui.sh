#!/usr/bin/env bash
#
# Deploy the Clinic Plan Console to Cloud Run (public), from the repo root in Cloud Shell:
#
#     bash frontend/deploy_ui.sh
#
# Prerequisite: bash agent/deploy_agent_runtime.sh (writes agent/.agent_runtime_id).
# The console calls Agent Runtime as service account clinic-ui (roles/aiplatform.user).
# max-instances=1 keeps the "one live run at a time" guard true across the service.
# If frontend/sample_run.json is missing but a local run was saved, it is bundled for Replay.

set -euo pipefail
PROJECT="${PROJECT:-$(gcloud config get-value project 2>/dev/null || true)}"
REGION="${REGION:-us-central1}"
HERE="$(cd "$(dirname "$0")" && pwd)"
UI_SA="clinic-ui@${PROJECT}.iam.gserviceaccount.com"
ID_FILE="${HERE}/../agent/.agent_runtime_id"

[ -s "${ID_FILE}" ] || { echo "No agent/.agent_runtime_id. Run: bash agent/deploy_agent_runtime.sh" >&2; exit 1; }
AGENT_RUNTIME_ID="$(cat "${ID_FILE}")"
echo "Project ${PROJECT}  Region ${REGION}"
echo "Agent Runtime ${AGENT_RUNTIME_ID}"

if [ ! -f "${HERE}/sample_run.json" ] && [ -f /tmp/clinic_last_run.json ]; then
  cp /tmp/clinic_last_run.json "${HERE}/sample_run.json"
  echo "Bundled your last local run as sample_run.json for Replay."
fi

retry_bind() {
  local i
  for i in $(seq 1 12); do
    if "$@" >/dev/null 2>&1; then return 0; fi
    echo "   waiting for IAM to see the new service account (attempt ${i}/12)..."; sleep 10
  done
  "$@" >/dev/null
}

gcloud iam service-accounts describe "${UI_SA}" --project "${PROJECT}" >/dev/null 2>&1 \
  || gcloud iam service-accounts create clinic-ui --project "${PROJECT}"
retry_bind gcloud projects add-iam-policy-binding "${PROJECT}" --member "serviceAccount:${UI_SA}" \
  --role roles/aiplatform.user --condition=None --quiet

gcloud run deploy clinic-ui --source "${HERE}" --region "${REGION}" --project "${PROJECT}" \
  --service-account "${UI_SA}" --allow-unauthenticated \
  --max-instances 1 --timeout 3600 --memory 1Gi \
  --set-env-vars "AGENT_RUNTIME_ID=${AGENT_RUNTIME_ID}"

echo
echo "Console: $(gcloud run services describe clinic-ui --region "${REGION}" --project "${PROJECT}" --format 'value(status.url)')"
