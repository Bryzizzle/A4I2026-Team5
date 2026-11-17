# data/

**This folder is empty, and that is the design.**

Everything this challenge uses is pulled live from its original publisher by
`notebooks/c5_01_load_explore.ipynb` and loaded straight into BigQuery in **your** project. Nothing
is pre-cleaned and handed to you, because the cleaning decisions *are* the teaching—a shipped table
would hide nine real defects in federal data that you should see happen.

If a publisher is having a bad morning, `bash scripts/load.sh <COUNTY_FIPS>` rebuilds the identical
tables from a Cloud Storage snapshot instead.

## Where the data actually lives

After the notebook or `load.sh` runs, in `<your-project>.a4i_health`:

| Table | Grain | What it holds |
|---|---|---|
| `burden_tracts` | one row per census tract | uninsured, routine checkup, asthma, COPD, diabetes, blood pressure, four disability measures, lack of transportation (`pct_lack_transport`, NULL in 11 states), no-vehicle households, over-65 and under-17 share, limited English, no internet, three SVI theme scores, and a centroid |
| `exposure_tracts` | one row per census tract | mean and maximum PM2.5, and days over 12, 20, 25 and 35 µg/m³ |
| `tract_access` | one row per census tract | distance to the nearest care site of any kind, distance to the nearest safety-net site, and the difference between them |
| `care_sites` | one row per facility | every federally recognized care site inside your county, with coordinates, address and `site_kind` |
| `care_sites_state` | one row per facility | the same for the whole state, before the county filter—useful when the nearest clinic is over the county line |
| `shortage_areas` | one row per HRSA designation | where the federal government says a **neighborhood** is underserved, with `HPSA_SCORE`. Legitimately empty in four of our six counties |
| `shortage_facilities` | one row per HRSA designation | where a **clinic** serves an underserved population. This marks where care already *is*. Not the same thing, and never `UNION` it with the one above |
| `disease_weekly` | one row per week | emergency-department visit percentages for COVID, influenza and RSV—**a multi-county Health Service Area figure written onto a county key** |

**Three of those tables are not what their grain suggests, and the README says which.**
`exposure_tracts` carries an eleven-digit tract ID over a 12 km modeling surface.
`disease_weekly` describes a region, not a county and certainly not a tract. And `shortage_areas`
is empty in the default county for a real reason rather than a broken load.

## If you add your own data

You may, and it earns credit—but the license rules on the challenge card apply to anything you
bring, and they are not a formality. A winning project gets promoted publicly, so an unchecked
share-alike or non-commercial source becomes somebody else's legal problem.

Two traps specific to this domain. **Federal funding does not imply federal license terms**—the best
transit-accessibility dataset in the country is FHWA-sponsored and CC BY-NC. And health data is full
of files that are technically aggregate and practically about individuals; **if a row could be one
person, it is an automatic rejection**, however useful it would have been.

Put small reference files here and commit them. Anything large, or anything pulled live, belongs in
BigQuery rather than in git.

---

## Team 5 data lane: what we built on top of the eight tables

Run once after the notebook or `scripts/load.sh`, from the repo root in Cloud Shell:

```bash
bash data/run_sql.sh          # validate, then build the views; safe to re-run
```

| File | Creates | Who may read it |
|---|---|---|
| `sql/01_validate.sql` | prints OK / WARN / FAIL checks | everyone |
| `sql/02_v_van_need.sql` | `v_van_need`: one row per tract with `need_score`, `need_rank`, `top_drivers`, a plain `reason`, raw inputs | **planner** |
| `sql/03_v_coverage.sql` | `v_coverage`: one row of "what we could not tell you", counted | everyone |
| `sql/04_v_equity_audit.sql` | `v_equity_audit_base`, `v_equity_audit_top_decile`: tracts joined to Census ACS race and poverty | **auditor only** |
| `sql/queries/audit_plan.sql` | parameterized audit of a specific plan (`@tract_ids ARRAY<STRING>`) | **auditor only** |
| `saturdays.py` | `pick_saturdays()`: ranked rows → 4 spaced Saturdays + why each runner-up lost | planner / explainer tool |
| `column_provenance.csv` | every column → source, scale, measured or modeled | everyone; feed it to the agents |

### What "needs the van" means here (defend this on stage)

`need_score` (0–100) is a weighted mean of **within-county percentile ranks**:

- 60%: who is sick and not being seen
  - uninsured 18–64 (PLACES): 30%
  - *low* routine checkup: 15%
  - chronic burden (diabetes, high BP, COPD, asthma): 15%
- 20%: straight-line km to the nearest safety-net site
- 20%: can't get there anyway
  - no-vehicle households (SVI): 15%
  - mobility difficulty: 5%

Tracts under 500 people are not scored.

**Left out on purpose:**
- PM2.5: a 12 km grid, with p90/p10 around 1.05.
- ED disease trends: these describe a multi-county region.
- `pct_lack_transport`: NULL in 11 states.
- HPSA score: empty in most counties.
- Race: banned as an input, used only in the audit views.

### Rules that keep the architecture honest

- **The planner agent gets `v_van_need` and `v_coverage` only.** The audit views carry race. Giving them to the planner breaks the event rule and our multi-agent argument.
- **Check `acs_match_rate` in the audit output.** Below about 0.9 means the ACS tract vintage doesn't match PLACES' 2020 tracts. In that case, set `ACS_TABLE` to a newer ACS tract table.
- **Four tracts is a tiny audit sample.** Always report it next to the top-decile audit.

Local test of the picker (no cloud needed): `cd data && python3 -m unittest test_saturdays`.
