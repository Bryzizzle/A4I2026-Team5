-- 02_v_van_need.sql
-- THE PLANNER'S VIEW: what "needs the van" means for our team, one row per tract.
--
-- Definition (a modeling decision; defend it, don't hide it):
--
--   need_score (0-100) = weighted mean of within-county percentile ranks:
--
--     WHO IS SICK AND NOT BEING SEEN                         60%
--       30%  pct_uninsured       PLACES, adults 18-64 (our headline uninsured number)
--       15%  pct_checkup         PLACES, INVERTED: low checkup rate = high need
--       15%  chronic burden      mean rank of diabetes, high BP, COPD, asthma (PLACES)
--     DISTANCE TO CARE THEY CAN USE                          20%
--       20%  km_to_safety_net    straight line to nearest FQHC / HRSA health center site
--     CAN'T GET THERE EVEN IF IT IS CLOSE                    20%
--       15%  pct_no_vehicle      SVI (vehicle ownership)
--        5%  pct_mobility_difficulty   PLACES
--
-- Deliberately EXCLUDED, and why:
--   * PM2.5 / exposure_tracts: a 12 km grid wearing tract IDs. p90/p10 is ~1.05 in Fulton,
--     so it would add noise dressed up as signal. Air is county context, not a tract ranker.
--   * disease_weekly: a multi-county Health Service Area figure. Cannot rank tracts.
--   * Race / ethnicity: banned as a model input. It is used ONLY in the audit views (04),
--     which the planner agent must not be given access to.
--   * pct_lack_transport: NULL in 11 states (incl. TX). Kept as a displayed column so the
--     agent can quote it where present, but not scored, so scores mean the same everywhere.
--   * shortage_areas HPSA_SCORE: empty in 4 of 6 pre-staged counties, and mixed-grain
--     (tract or county GEO_ID). Reported as context, not scored.
--
-- Population floor: tracts under 500 people are not scored (too small to fill a van-day,
-- and PLACES estimates there are the most smoothed). They stay visible with excluded_reason.
--
-- Missing components: the score is renormalized over the components that are present, and
-- components_missing says how many were absent. Treat components_missing > 0 with care.
--
-- Scale of every number here: TRACT, except distances which are tract-centroid to
-- facility-point straight lines (an upper bound: federal sites only, county line cuts off).
-- PLACES values are MODELED prevalence, not counts.

CREATE OR REPLACE VIEW `{{PROJECT}}.{{DATASET}}.v_van_need` AS
WITH base AS (
  SELECT
    b.geo_id,
    b.total_pop,
    b.latitude,
    b.longitude,
    b.pct_uninsured,
    b.pct_uninsured_all_ages,
    b.pct_checkup,
    b.pct_diabetes,
    b.pct_high_bp,
    b.pct_copd,
    b.pct_asthma,
    b.pct_no_vehicle,
    b.pct_mobility_difficulty,
    b.pct_lack_transport,
    b.pct_age_65_plus,
    b.pct_limited_english,
    b.pct_no_internet,
    a.km_to_any_care,
    a.km_to_safety_net,
    a.extra_km_if_uninsured,
    CASE
      WHEN b.latitude IS NULL OR b.longitude IS NULL THEN 'no centroid'
      WHEN b.total_pop IS NULL OR b.total_pop < 500 THEN 'population under 500'
      ELSE NULL
    END AS excluded_reason
  FROM `{{PROJECT}}.{{DATASET}}.burden_tracts` b
  LEFT JOIN `{{PROJECT}}.{{DATASET}}.tract_access` a USING (geo_id)
),

-- Percentile ranks among SCORED tracts only, and only among non-NULL values.
-- PARTITION BY (x IS NULL) keeps NULLs from being ranked as the lowest value.
ranked AS (
  SELECT
    *,
    IF(pct_uninsured IS NULL, NULL,
       PERCENT_RANK() OVER (PARTITION BY excluded_reason IS NULL, pct_uninsured IS NULL
                            ORDER BY pct_uninsured)) AS r_uninsured,
    IF(pct_checkup IS NULL, NULL,
       PERCENT_RANK() OVER (PARTITION BY excluded_reason IS NULL, pct_checkup IS NULL
                            ORDER BY pct_checkup DESC)) AS r_no_checkup,   -- inverted
    IF(pct_diabetes IS NULL, NULL,
       PERCENT_RANK() OVER (PARTITION BY excluded_reason IS NULL, pct_diabetes IS NULL
                            ORDER BY pct_diabetes)) AS r_diabetes,
    IF(pct_high_bp IS NULL, NULL,
       PERCENT_RANK() OVER (PARTITION BY excluded_reason IS NULL, pct_high_bp IS NULL
                            ORDER BY pct_high_bp)) AS r_high_bp,
    IF(pct_copd IS NULL, NULL,
       PERCENT_RANK() OVER (PARTITION BY excluded_reason IS NULL, pct_copd IS NULL
                            ORDER BY pct_copd)) AS r_copd,
    IF(pct_asthma IS NULL, NULL,
       PERCENT_RANK() OVER (PARTITION BY excluded_reason IS NULL, pct_asthma IS NULL
                            ORDER BY pct_asthma)) AS r_asthma,
    IF(km_to_safety_net IS NULL, NULL,
       PERCENT_RANK() OVER (PARTITION BY excluded_reason IS NULL, km_to_safety_net IS NULL
                            ORDER BY km_to_safety_net)) AS r_distance,
    IF(pct_no_vehicle IS NULL, NULL,
       PERCENT_RANK() OVER (PARTITION BY excluded_reason IS NULL, pct_no_vehicle IS NULL
                            ORDER BY pct_no_vehicle)) AS r_no_vehicle,
    IF(pct_mobility_difficulty IS NULL, NULL,
       PERCENT_RANK() OVER (PARTITION BY excluded_reason IS NULL, pct_mobility_difficulty IS NULL
                            ORDER BY pct_mobility_difficulty)) AS r_mobility
  FROM base
),

chronic AS (
  SELECT
    *,
    -- Mean of whichever chronic ranks exist (PLACES nulls them together in practice).
    (SELECT AVG(x) FROM UNNEST([r_diabetes, r_high_bp, r_copd, r_asthma]) x) AS r_chronic
  FROM ranked
),

scored AS (
  SELECT
    *,
    -- Weighted mean over present components, renormalized.
    SAFE_DIVIDE(
        0.30 * IFNULL(r_uninsured, 0)
      + 0.15 * IFNULL(r_no_checkup, 0)
      + 0.15 * IFNULL(r_chronic, 0)
      + 0.20 * IFNULL(r_distance, 0)
      + 0.15 * IFNULL(r_no_vehicle, 0)
      + 0.05 * IFNULL(r_mobility, 0),
        IF(r_uninsured  IS NULL, 0, 0.30)
      + IF(r_no_checkup IS NULL, 0, 0.15)
      + IF(r_chronic    IS NULL, 0, 0.15)
      + IF(r_distance   IS NULL, 0, 0.20)
      + IF(r_no_vehicle IS NULL, 0, 0.15)
      + IF(r_mobility   IS NULL, 0, 0.05)
    ) AS raw_score,
      IF(r_uninsured  IS NULL, 1, 0) + IF(r_no_checkup IS NULL, 1, 0)
    + IF(r_chronic    IS NULL, 1, 0) + IF(r_distance   IS NULL, 1, 0)
    + IF(r_no_vehicle IS NULL, 1, 0) + IF(r_mobility   IS NULL, 1, 0) AS components_missing
  FROM chronic
)

SELECT
  geo_id,
  total_pop,
  latitude,
  longitude,
  IF(excluded_reason IS NULL, ROUND(100 * raw_score, 1), NULL) AS need_score,
  IF(excluded_reason IS NULL,
     RANK() OVER (PARTITION BY excluded_reason IS NULL ORDER BY raw_score DESC),
     NULL) AS need_rank,
  excluded_reason,
  components_missing,

  -- The two strongest drivers, so the planner can say WHY in one breath.
  ARRAY(
    SELECT AS STRUCT d.driver, ROUND(d.r, 2) AS pctile
    FROM UNNEST([
      STRUCT('uninsured (18-64)'      AS driver, r_uninsured  AS r),
      STRUCT('low routine checkup',              r_no_checkup),
      STRUCT('chronic disease burden',           r_chronic),
      STRUCT('far from safety-net care',         r_distance),
      STRUCT('no vehicle',                       r_no_vehicle),
      STRUCT('mobility difficulty',              r_mobility)
    ]) d
    WHERE d.r IS NOT NULL
    ORDER BY d.r DESC
    LIMIT 2
  ) AS top_drivers,

  -- A sentence a human can read. Scales stated, "federally recognized" stated.
  IF(excluded_reason IS NULL,
     FORMAT(
       '%s people. %s of adults 18-64 uninsured (modeled, tract). %s of households have no vehicle (tract). '
       || '%s km straight-line to the nearest federally recognized safety-net site (upper bound).',
       FORMAT("%'d", CAST(total_pop AS INT64)),
       IFNULL(FORMAT('%.0f%%', pct_uninsured), 'unknown share'),
       IFNULL(FORMAT('%.0f%%', pct_no_vehicle), 'unknown share'),
       IFNULL(FORMAT('%.1f', km_to_safety_net), '?')),
     NULL) AS reason,

  -- Judgment flags for the planner (not scored, but should change a decision).
  km_to_safety_net < 1.0 AS near_existing_safety_net,

  -- Raw inputs, so nobody has to re-join to explain a number.
  pct_uninsured, pct_uninsured_all_ages, pct_checkup,
  pct_diabetes, pct_high_bp, pct_copd, pct_asthma,
  pct_no_vehicle, pct_mobility_difficulty, pct_lack_transport,
  pct_age_65_plus, pct_limited_english, pct_no_internet,
  km_to_any_care, km_to_safety_net, extra_km_if_uninsured,

  -- Component ranks (0 = best in county, 1 = worst).
  ROUND(r_uninsured, 3)  AS r_uninsured,
  ROUND(r_no_checkup, 3) AS r_no_checkup,
  ROUND(r_chronic, 3)    AS r_chronic,
  ROUND(r_distance, 3)   AS r_distance,
  ROUND(r_no_vehicle, 3) AS r_no_vehicle,
  ROUND(r_mobility, 3)   AS r_mobility
FROM scored
