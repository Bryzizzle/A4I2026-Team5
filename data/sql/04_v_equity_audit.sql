-- 04_v_equity_audit.sql
-- THE AUDITOR'S VIEWS. *** The planner agent must NOT be given access to these. ***
--
-- Race/ethnicity is banned as a model input and REQUIRED as an audit of the output.
-- These views join tracts to Census ACS demographics (bigquery-public-data, US Gov work,
-- public domain) so a separate auditor agent can ask: did the plan land where people
-- cannot reach care, or did the score find a proxy for something else?
--
-- Two views:
--   v_equity_audit_base        one row per tract with demographics. Auditor-only.
--   v_equity_audit_top_decile  county vs top-10%-of-need_score, per group. Ready to report.
-- For auditing a specific 4-Saturday plan use queries/audit_plan.sql (parameterized).
--
-- CAVEATS, which the auditor must state:
--   * ACS tract vintage must match PLACES (2020 tracts). acs_match_rate below tells you;
--     under ~0.9 means a vintage mismatch, not a demographic finding.
--   * ACS race counts are themselves 5-year survey ESTIMATES with margins of error.
--   * Group columns are reported under their ACS column names. Check the
--     'overlap check' row: if > 1.0 the groups overlap (include Hispanic) and shares
--     must not be summed.

CREATE OR REPLACE VIEW `{{PROJECT}}.{{DATASET}}.v_equity_audit_base` AS
WITH acs AS (
  SELECT
    LPAD(CAST(geo_id AS STRING), 11, '0') AS geo_id,
    total_pop      AS acs_pop,
    hispanic_pop,
    black_pop,
    white_pop,
    asian_pop,
    median_income,
    poverty
  FROM `{{ACS_TABLE}}`
)
SELECT
  v.geo_id,
  v.need_score,
  v.need_rank,
  v.total_pop,
  v.pct_limited_english,
  v.pct_age_65_plus,
  v.pct_no_vehicle,
  v.pct_uninsured,
  acs.geo_id IS NOT NULL AS acs_matched,
  acs.acs_pop,
  acs.hispanic_pop,
  acs.black_pop,
  acs.white_pop,
  acs.asian_pop,
  acs.median_income,
  acs.poverty
FROM `{{PROJECT}}.{{DATASET}}.v_van_need` v
LEFT JOIN acs USING (geo_id);


CREATE OR REPLACE VIEW `{{PROJECT}}.{{DATASET}}.v_equity_audit_top_decile` AS
WITH t AS (
  SELECT
    *,
    IFNULL(need_rank <= CEIL(0.10 * COUNTIF(need_rank IS NOT NULL) OVER ()), FALSE) AS selected
  FROM `{{PROJECT}}.{{DATASET}}.v_equity_audit_base`
),
long AS (
  SELECT t.selected, g.grp, g.source, g.n, g.denom
  FROM t,
  UNNEST([
    STRUCT('hispanic_pop'  AS grp, 'ACS' AS source, CAST(t.hispanic_pop AS FLOAT64) AS n,
           CAST(t.acs_pop AS FLOAT64) AS denom),
    STRUCT('black_pop',  'ACS', CAST(t.black_pop AS FLOAT64),  CAST(t.acs_pop AS FLOAT64)),
    STRUCT('white_pop',  'ACS', CAST(t.white_pop AS FLOAT64),  CAST(t.acs_pop AS FLOAT64)),
    STRUCT('asian_pop',  'ACS', CAST(t.asian_pop AS FLOAT64),  CAST(t.acs_pop AS FLOAT64)),
    STRUCT('all other (acs_pop minus the four above)', 'ACS',
           CAST(t.acs_pop - t.hispanic_pop - t.black_pop - t.white_pop - t.asian_pop AS FLOAT64),
           CAST(t.acs_pop AS FLOAT64)),
    STRUCT('below poverty (approx: ACS poverty / total pop)', 'ACS',
           CAST(t.poverty AS FLOAT64), CAST(t.acs_pop AS FLOAT64)),
    STRUCT('limited English', 'SVI', t.pct_limited_english / 100 * t.total_pop, t.total_pop),
    STRUCT('age 65+',         'SVI', t.pct_age_65_plus / 100 * t.total_pop,     t.total_pop),
    STRUCT('overlap check (sum of 4 groups / acs_pop)', 'ACS',
           CAST(t.hispanic_pop + t.black_pop + t.white_pop + t.asian_pop AS FLOAT64),
           CAST(t.acs_pop AS FLOAT64))
  ]) g
  WHERE g.n IS NOT NULL AND g.denom IS NOT NULL AND g.denom > 0
)
SELECT
  grp,
  source,
  ROUND(SAFE_DIVIDE(SUM(n), SUM(denom)), 4)                                   AS county_share,
  ROUND(SAFE_DIVIDE(SUM(IF(selected, n, 0)), SUM(IF(selected, denom, 0))), 4) AS top_decile_share,
  ROUND(SAFE_DIVIDE(
          SAFE_DIVIDE(SUM(IF(selected, n, 0)), SUM(IF(selected, denom, 0))),
          SAFE_DIVIDE(SUM(n), SUM(denom))), 2)                                AS ratio_vs_county,
  (SELECT COUNTIF(selected) FROM t)                                           AS tracts_selected,
  (SELECT ROUND(SAFE_DIVIDE(COUNTIF(acs_matched), COUNT(*)), 3) FROM t)       AS acs_match_rate
FROM long
GROUP BY grp, source
ORDER BY source, grp;

-- Median income has no share; compare medians directly:
--   SELECT selected, APPROX_QUANTILES(median_income, 2)[OFFSET(1)] FROM ... GROUP BY selected
