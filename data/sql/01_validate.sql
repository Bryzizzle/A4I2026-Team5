-- 01_validate.sql
-- Sanity checks on the eight loaded tables BEFORE we build anything on them.
-- One row per check: check_name, value, verdict (OK / WARN / FAIL), why_it_matters.
--
-- FAIL = our load or join is broken, stop.
-- WARN = the publisher handed us something untidy, or the county lacks a signal.
--        A WARN is not a bug. It is usually a finding worth saying out loud.

WITH
b AS (SELECT * FROM `{{PROJECT}}.{{DATASET}}.burden_tracts`),
a AS (SELECT * FROM `{{PROJECT}}.{{DATASET}}.tract_access`),
e AS (SELECT * FROM `{{PROJECT}}.{{DATASET}}.exposure_tracts`),
s AS (SELECT * FROM `{{PROJECT}}.{{DATASET}}.care_sites`),
d AS (SELECT * FROM `{{PROJECT}}.{{DATASET}}.disease_weekly`)

SELECT 'burden_tracts rows' AS check_name,
       CAST((SELECT COUNT(*) FROM b) AS STRING) AS value,
       IF((SELECT COUNT(*) FROM b) > 0, 'OK', 'FAIL') AS verdict,
       'One row per census tract. Zero means the load failed.' AS why_it_matters
UNION ALL
SELECT 'geo_id is always 11 characters',
       CAST((SELECT COUNTIF(LENGTH(geo_id) != 11) FROM b) AS STRING),
       IF((SELECT COUNTIF(LENGTH(geo_id) != 11) FROM b) = 0, 'OK', 'FAIL'),
       'A lost leading zero (CA, AL, AZ...) silently breaks every join.'
UNION ALL
SELECT 'duplicate tract ids in burden_tracts',
       CAST((SELECT COUNT(*) - COUNT(DISTINCT geo_id) FROM b) AS STRING),
       IF((SELECT COUNT(*) - COUNT(DISTINCT geo_id) FROM b) = 0, 'OK', 'FAIL'),
       'Duplicates double-count people in every population total.'
UNION ALL
SELECT 'tracts with coordinates but no access row',
       CAST((SELECT COUNT(*) FROM b WHERE latitude IS NOT NULL
               AND geo_id NOT IN (SELECT geo_id FROM a)) AS STRING),
       IF((SELECT COUNT(*) FROM b WHERE latitude IS NOT NULL
               AND geo_id NOT IN (SELECT geo_id FROM a)) = 0, 'OK', 'FAIL'),
       'tract_access should cover every tract that has a centroid.'
UNION ALL
SELECT 'safety-net sites in county (FQHC + Health Center site)',
       CAST((SELECT COUNTIF(site_kind IN ('FQHC', 'Health Center site')) FROM s) AS STRING),
       IF((SELECT COUNTIF(site_kind IN ('FQHC', 'Health Center site')) FROM s) > 0, 'OK', 'FAIL'),
       'With none, km_to_safety_net is NULL everywhere and the core measure is gone.'
UNION ALL
SELECT 'tracts further from safety-net care than from any care',
       CAST((SELECT COUNTIF(extra_km_if_uninsured > 0) FROM a) AS STRING),
       IF((SELECT COUNTIF(extra_km_if_uninsured > 0) FROM a) > 0, 'OK', 'WARN'),
       'Zero means the central gap of this challenge does not exist in this county.'
UNION ALL
SELECT 'pct_lack_transport populated (PLACES, 40 states only)',
       CAST((SELECT COUNTIF(pct_lack_transport IS NOT NULL) FROM b) AS STRING),
       IF((SELECT COUNTIF(pct_lack_transport IS NOT NULL) FROM b) > 0, 'OK', 'WARN'),
       'NULL in 11 states incl. TX. Fall back to pct_no_vehicle (vehicle OWNERSHIP, not the same thing).'
UNION ALL
SELECT 'pct_no_vehicle populated (SVI; -999 already nulled)',
       CAST((SELECT COUNTIF(pct_no_vehicle IS NOT NULL) FROM b) AS STRING),
       IF((SELECT COUNTIF(pct_no_vehicle IS NOT NULL) FROM b)
            >= 0.9 * (SELECT COUNT(*) FROM b), 'OK', 'WARN'),
       'SVI suppresses some tracts with -999; those are NULL here, not zero.'
UNION ALL
SELECT 'designated shortage AREAS',
       CAST((SELECT COUNT(*) FROM `{{PROJECT}}.{{DATASET}}.shortage_areas`) AS STRING),
       IF((SELECT COUNT(*) FROM `{{PROJECT}}.{{DATASET}}.shortage_areas`) > 0, 'OK', 'WARN'),
       'Empty is legitimate (Fulton: 99 of 99 Proposed For Withdrawal). No signal is not no problem.'
UNION ALL
SELECT 'weeks with a usable COVID ED value',
       FORMAT('%d of %d', (SELECT COUNTIF(percent_visits_covid IS NOT NULL) FROM d),
                          (SELECT COUNT(*) FROM d)),
       IF((SELECT COUNTIF(percent_visits_covid IS NOT NULL) FROM d) > 0, 'OK', 'WARN'),
       'Santa Clara and the Bronx are all NULL. And it is a multi-county HSA figure anyway.'
UNION ALL
SELECT 'exposure tracts not in burden_tracts',
       CAST((SELECT COUNT(*) FROM e WHERE geo_id NOT IN (SELECT geo_id FROM b)) AS STRING),
       'OK',
       'Expected: EPA models every tract, PLACES suppresses tiny ones. Always LEFT JOIN from burden.'
UNION ALL
SELECT 'PM2.5 p90/p10 across tracts (12 km grid)',
       CAST(ROUND((SELECT SAFE_DIVIDE(APPROX_QUANTILES(mean_pm, 10)[OFFSET(9)],
                                      APPROX_QUANTILES(mean_pm, 10)[OFFSET(1)]) FROM e), 3) AS STRING),
       'WARN',
       'Near 1.0 means air cannot separate neighborhoods. Deliberately NOT in the need score.'
UNION ALL
SELECT 'PLACES uninsured (18-64) p90/p10 across tracts',
       CAST(ROUND((SELECT SAFE_DIVIDE(APPROX_QUANTILES(pct_uninsured, 10)[OFFSET(9)],
                                      APPROX_QUANTILES(pct_uninsured, 10)[OFFSET(1)]) FROM b), 2) AS STRING),
       'OK',
       'Compare with the PM2.5 ratio above. This is the spread that actually separates tracts.'
