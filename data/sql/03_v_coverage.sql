-- 03_v_coverage.sql
-- "WHAT WE COULD NOT TELL YOU" — one row per county, counted, not hidden.
--
-- This feeds part 2 of the Clinic Plan. Every field is either a count of what is
-- missing, or a statement of the scale a layer actually resolves at. Safe for any agent
-- to read (contains no demographic columns).

CREATE OR REPLACE VIEW `{{PROJECT}}.{{DATASET}}.v_coverage` AS
WITH
b AS (SELECT * FROM `{{PROJECT}}.{{DATASET}}.burden_tracts`),
v AS (SELECT * FROM `{{PROJECT}}.{{DATASET}}.v_van_need`),
e AS (SELECT * FROM `{{PROJECT}}.{{DATASET}}.exposure_tracts`),
s AS (SELECT * FROM `{{PROJECT}}.{{DATASET}}.care_sites`),
d AS (SELECT * FROM `{{PROJECT}}.{{DATASET}}.disease_weekly`)
SELECT
  (SELECT ANY_VALUE(SUBSTR(geo_id, 1, 5)) FROM b) AS county_fips,

  -- People layer (TRACT)
  (SELECT COUNT(*) FROM b)                                          AS tracts_total,
  (SELECT CAST(SUM(total_pop) AS INT64) FROM b)                     AS population_total,
  (SELECT COUNTIF(need_score IS NOT NULL) FROM v)                   AS tracts_scored,
  (SELECT COUNTIF(excluded_reason IS NOT NULL) FROM v)              AS tracts_not_scored,
  (SELECT COUNTIF(components_missing > 0 AND need_score IS NOT NULL) FROM v)
                                                                    AS tracts_scored_with_missing_inputs,
  (SELECT COUNTIF(pct_lack_transport IS NOT NULL) FROM b)           AS tracts_with_lack_transport,
  (SELECT COUNTIF(pct_no_vehicle IS NULL) FROM b)                   AS tracts_missing_no_vehicle,

  -- Care layer (FACILITY POINTS, federal only => every distance is an upper bound)
  (SELECT COUNT(*) FROM s)                                          AS care_sites_total,
  (SELECT COUNTIF(site_kind IN ('FQHC', 'Health Center site')) FROM s) AS safety_net_sites,
  (SELECT CAST(SUM(total_pop) AS INT64) FROM v WHERE km_to_safety_net > 5)
                                                                    AS people_over_5km_from_safety_net,
  (SELECT ROUND(MAX(km_to_safety_net), 1) FROM v)                   AS worst_km_to_safety_net,

  -- Federal shortage designations (siting signal; often EMPTY)
  (SELECT COUNT(*) FROM `{{PROJECT}}.{{DATASET}}.shortage_areas`)   AS shortage_areas_designated,
  (SELECT COUNT(*) FROM `{{PROJECT}}.{{DATASET}}.shortage_facilities`)
                                                                    AS shortage_facilities_NOT_a_siting_signal,

  -- Current disease (HEALTH SERVICE AREA, multi-county, on a county key)
  (SELECT COUNT(*) FROM d)                                          AS disease_weeks_total,
  (SELECT COUNTIF(percent_visits_covid IS NOT NULL) FROM d)         AS disease_weeks_with_covid,
  (SELECT MAX(IF(percent_visits_covid IS NOT NULL, week_end, NULL)) FROM d)
                                                                    AS disease_latest_usable_week,
  (SELECT ANY_VALUE(hsa) FROM d)                                    AS disease_hsa,
  (SELECT ANY_VALUE(hsa_counties) FROM d)                           AS disease_hsa_counties,

  -- Air (12 KM GRID wearing tract ids)
  (SELECT ROUND(SAFE_DIVIDE(APPROX_QUANTILES(mean_pm, 10)[OFFSET(9)],
                            APPROX_QUANTILES(mean_pm, 10)[OFFSET(1)]), 3) FROM e)
                                                                    AS pm25_p90_over_p10,

  -- Fixed statements the agent can quote verbatim.
  [
    'Distances are straight lines, not travel time, to FEDERALLY RECOGNIZED sites only, inside the county line: an upper bound.',
    'Disease prevalence (PLACES) is MODELED for people like those who live there, not counted.',
    'Air quality is a 12 km model grid: it describes the county and bad days, not one street versus another.',
    'Emergency-department trends describe a multi-county Health Service Area, never a neighborhood.',
    'Free clinics, county clinics and pharmacies are not in any license-clean national list, so they are invisible here.'
  ] AS standing_limitations
