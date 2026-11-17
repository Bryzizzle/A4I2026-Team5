# What the data says: Fulton County, GA (13121)

For the story lane, from the data lane's run of `data/run_sql.sh` on 2026-11-17.

Every number has a label. **Measured** means a straight count or distance. **Modeled** means an estimate (CDC PLACES). **Survey** means a Census or SVI estimate. Judges check these labels, so keep them on your slides.

---

## The three numbers to lead with

1. **443,800 people live more than 5 km from a clinic that will see them uninsured.**
   - That's 42% of Fulton's 1,066,710 residents. The worst tract is **28.6 km** away.
   - *Measured, but an upper bound:* straight-line distance to federally recognized sites inside the county only.
2. **135 of 326 tracts (41%) are further from a safety-net clinic than from the nearest clinic of any kind.**
   - "There's a clinic nearby" and "there's a clinic that will take you" are different things.
   - *Measured.*
3. **Uninsured rates vary 3.16× across Fulton's tracts. Air pollution varies 1.049×.**
   - The obvious ranking (by pollution) can't tell neighborhoods apart. The air data comes from a 12 km model grid, so neighboring tracts share one number.
   - *Uninsured: modeled. PM2.5: modeled.*

---

## How we decided who "needs the van"

`need_score` runs from 0 to 100. It's a weighted mix of how each tract ranks **within Fulton** on six inputs:

| Group | Inputs | Weight |
|---|---|---:|
| Sick and not being seen | Uninsured adults 18–64 (30%), low routine checkup (15%), chronic disease (15%) | 60% |
| Far from care they can use | Distance to nearest safety-net site | 20% |
| Can't get there anyway | No vehicle (15%), mobility difficulty (5%) | 20% |

**Left out on purpose, and why:**

| Input | Why it's out |
|---|---|
| Air quality | 12 km grid, can't separate neighborhoods |
| Disease trends | One figure for 4 counties |
| Shortage designations | Fulton has none live |
| Race | Banned as an input; used only to audit the result |

Tracts under 500 people aren't scored. That's 1 tract.

---

## The decision the data forces: two kinds of need

The top 10 splits into two groups that point to different answers.

| | Far, but people have cars | Close, but no car |
|---|---|---|
| Tracts | `011430`, `011421`, `011431` (ranks 1, 2, 4) | `006802`, `006602`, `007808` (ranks 6, 7, 9) |
| Uninsured, 18–64 | 23–35% | 22–29% |
| No vehicle | 5–7% | **46–68%** |
| Distance to safety net | **13.5–14.6 km** | 1.3–2.2 km |

**The line for the stage:** "A car makes 14 km a 20-minute drive. No car makes 2 km a bus transfer and a day off work. Our score had to choose, and here's how it did."

**Two more points:**
- The three "far" tracts sit next to each other. Our Saturday picker keeps only one of them, because two Saturdays a few blocks apart serve the same people twice.
- Rank 3, `006801`, has no vehicle data. Its score uses the five inputs we have, so say so if it appears in the plan.

---

## Who the plan lands on (the equity audit)

We compared the neediest 10% of tracts (33 tracts) against the whole county. The auditor agent sees these demographics. The planner never does.

| Group | Fulton | Neediest 10% | Ratio |
|---|---:|---:|---:|
| Below poverty | 13% | 31% | **2.41×** |
| Hispanic | 7% | 13% | 1.86× |
| Black | 43% | 74% | 1.72× |
| Limited English | 1.8% | 2.9% | 1.66× |
| Age 65+ | 12% | 12% | 1.00× |
| White | 39% | 9% | 0.23× |
| Asian | 7% | 1% | 0.13× |

*Survey (Census ACS 5-year, 2020 tracts). Every tract matched (match rate 1.0).*

**What to say:**
- **What it shows.** Without ever seeing race or income, the plan lands in Fulton's poorest neighborhoods. Those are also disproportionately Black and Hispanic.
- **What it doesn't settle.** It doesn't prove the score avoided a racial proxy. But poverty concentrates the most (2.41×), more than any racial group, and poverty wasn't an input either. That fits a score that's finding structural need.
- **Why it's reported in full.** We report the full table, not a clean summary.

**Limited English at 1.66×** is the data's reason for writing the flyer in more than one language.

---

## What we could not tell you (say this; judges reward it)

| Topic | Limitation |
|---|---|
| Distances | Straight lines, not travel time. Federal sites only. They stop at the county line. **Every distance is an upper bound.** |
| Chronic disease and uninsured rates | Modeled estimates for "people like those who live there," not counts |
| Air quality | A 12 km grid. It describes the county and bad days, not one street versus another |
| Respiratory trends | Usable data through 2026-11-07, but one number shared by **Clayton, DeKalb, Fulton and Gwinnett**. It can never be a neighborhood claim |
| Shortage designations | 0 live in Fulton: all 99 are proposed for withdrawal. **No federal signal doesn't mean no problem** |
| Invisible care | Free clinics, county clinics and pharmacies: no license-clean list exists |

---

## Validation (what we checked before building)

- **No failures.** 326 tracts, no duplicates, every tract ID 11 characters, every tract has an access row, 55 safety-net sites.
- **Two warnings, both real defects in federal data and both worth a slide:**
  - Air quality can't separate neighborhoods (1.049×).
  - Fulton has zero live shortage areas.

---

## Still to come from the data lane

- **The actual 4 Saturdays.** Run `python3 data/plan_saturdays.py --audit` in Cloud Shell. The output gives the four tracts, the reason for each, the higher-scoring tracts we passed over and why, and the audit of those four tracts.
- **A caution for the 4-tract audit:** 4 tracts is a tiny sample, so always show it next to the top-10% table above.
