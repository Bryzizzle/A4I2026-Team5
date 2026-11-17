#!/usr/bin/env bash
#
# Build the data lane's views on top of the eight loaded tables.
# Run AFTER the notebook or scripts/load.sh, from the repo root, in Cloud Shell:
#
#     bash data/run_sql.sh
#
# Optional overrides (environment variables):
#     PROJECT    defaults to `gcloud config get-value project`
#     DATASET    defaults to a4i_health
#     ACS_TABLE  defaults to bigquery-public-data.census_bureau_acs.censustract_2020_5yr
#                (must be on 2020 tract boundaries; the audit prints acs_match_rate)
#
# Safe to re-run: every view is CREATE OR REPLACE. Works on bash 3.2+.

set -euo pipefail

PROJECT="${PROJECT:-$(gcloud config get-value project 2>/dev/null || true)}"
DATASET="${DATASET:-a4i_health}"
ACS_TABLE="${ACS_TABLE:-bigquery-public-data.census_bureau_acs.censustract_2020_5yr}"

if [ -z "${PROJECT}" ] || [ "${PROJECT}" = "(unset)" ]; then
  echo "No project. Run: gcloud config set project YOUR_PROJECT_ID  (or PROJECT=... bash data/run_sql.sh)" >&2
  exit 1
fi
command -v bq >/dev/null 2>&1 || { echo "'bq' not found. Run this in Cloud Shell." >&2; exit 1; }

HERE="$(cd "$(dirname "$0")" && pwd)"

render() {
  sed -e "s|{{PROJECT}}|${PROJECT}|g" \
      -e "s|{{DATASET}}|${DATASET}|g" \
      -e "s|{{ACS_TABLE}}|${ACS_TABLE}|g" "$1"
}

run() {
  local f="$1"
  echo
  echo "=== $(basename "$f")"
  # Pipe the SQL on stdin: passed as an argument, a leading "-- comment" is parsed as a flag.
  render "$f" | bq --project_id="${PROJECT}" --location=US query \
     --use_legacy_sql=false --max_rows=100 --format=pretty
}

echo "Project: ${PROJECT}   Dataset: ${DATASET}"
echo "ACS:     ${ACS_TABLE}"

run "${HERE}/sql/01_validate.sql"
run "${HERE}/sql/02_v_van_need.sql"
run "${HERE}/sql/03_v_coverage.sql"

if ! run "${HERE}/sql/04_v_equity_audit.sql"; then
  echo
  echo "The audit views failed. Most likely the ACS table name is wrong. List the options:"
  echo "  bq query --use_legacy_sql=false \"SELECT table_name FROM \\\`bigquery-public-data.census_bureau_acs.INFORMATION_SCHEMA.TABLES\\\` WHERE table_name LIKE 'censustract%' ORDER BY 1\""
  echo "then: ACS_TABLE=bigquery-public-data.census_bureau_acs.<name> bash data/run_sql.sh"
  exit 1
fi

echo
echo "=== Top 10 tracts by need_score"
bq --project_id="${PROJECT}" --location=US query --use_legacy_sql=false --format=pretty \
  "SELECT need_rank, geo_id, need_score, total_pop, ROUND(pct_uninsured,1) unins,
          ROUND(pct_no_vehicle,1) no_veh, km_to_safety_net, near_existing_safety_net
   FROM \`${PROJECT}.${DATASET}.v_van_need\`
   WHERE need_rank <= 10 ORDER BY need_rank"

echo
echo "=== What we could not tell you"
bq --project_id="${PROJECT}" --location=US query --use_legacy_sql=false --format=prettyjson \
  "SELECT * EXCEPT(standing_limitations) FROM \`${PROJECT}.${DATASET}.v_coverage\`"

echo
echo "=== Equity audit of the top decile (AUDITOR ONLY)"
bq --project_id="${PROJECT}" --location=US query --use_legacy_sql=false --format=pretty \
  "SELECT * FROM \`${PROJECT}.${DATASET}.v_equity_audit_top_decile\`"

echo
echo "Done. Views: v_van_need, v_coverage (planner-safe); v_equity_audit_base, v_equity_audit_top_decile (auditor only)."
