-- audit_plan.sql — AUDITOR ONLY. Audit a specific plan (e.g. the four Saturday tracts).
--
-- Parameter: @tract_ids ARRAY<STRING>   (11-character tract geo_ids)
--
--   bq query --use_legacy_sql=false \
--     --parameter='tract_ids:ARRAY<STRING>:["13121010214","13121007802","13121011100","13121006801"]' \
--     "$(sed -e 's|{{PROJECT}}|my-proj|g' -e 's|{{DATASET}}|a4i_health|g' data/sql/queries/audit_plan.sql)"
--
-- Works unchanged as an MCP Toolbox tool (array parameter).
--
-- Four tracts is a TINY sample. A ratio of 2.0 on four tracts is a description of these
-- four places, not evidence of a systematic bias. Report it alongside the top-decile view
-- (v_equity_audit_top_decile), which audits the ranking itself on ~10% of the county.

WITH t AS (
  SELECT *, geo_id IN UNNEST(@tract_ids) AS selected
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
    STRUCT('no vehicle',      'SVI', t.pct_no_vehicle / 100 * t.total_pop,      t.total_pop)
  ]) g
  WHERE g.n IS NOT NULL AND g.denom IS NOT NULL AND g.denom > 0
)
SELECT
  grp,
  source,
  ROUND(SAFE_DIVIDE(SUM(n), SUM(denom)), 4)                                   AS county_share,
  ROUND(SAFE_DIVIDE(SUM(IF(selected, n, 0)), SUM(IF(selected, denom, 0))), 4) AS plan_share,
  ROUND(SAFE_DIVIDE(
          SAFE_DIVIDE(SUM(IF(selected, n, 0)), SUM(IF(selected, denom, 0))),
          SAFE_DIVIDE(SUM(n), SUM(denom))), 2)                                AS ratio_vs_county,
  (SELECT COUNTIF(selected) FROM t)                                           AS tracts_found,
  ARRAY_LENGTH(@tract_ids)                                                    AS tracts_requested
FROM long
GROUP BY grp, source
ORDER BY source, grp
