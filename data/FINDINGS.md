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

## The plan: four Saturdays

From `python3 data/plan_saturdays.py --audit`. Rules:
- Take the highest `need_score`.
- Skip tracts within 1 km of an existing safety-net site.
- Keep picks at least 3 km apart.

| Saturday | Tract | Score (rank) | People | Uninsured 18–64 | No vehicle | To safety net | Why |
|---|---|---|---:|---:|---:|---:|---|
| 1 | `13121011430` | 78.2 (1) | 4,338 | 25% | 7% | 13.5 km | Far: uninsured and skipping checkups, with the nearest safety-net site 13.5 km away |
| 2 | `13121006801` | 77.2 (3) | 2,297 | **35%** | unknown | 1.4 km | Highest uninsured rate in the county. **No vehicle data for this tract** |
| 3 | `13121007604` | 76.9 (5) | 3,191 | 20% | 33% | 4.4 km | Mobility difficulty and chronic disease |
| 4 | `13121006602` | 76.2 (7) | 1,050 | 22% | **46%** | 2.2 km | Nearly half of households have no car |

*Uninsured: modeled. No vehicle: survey. Distances: measured, upper bound.*

The plan covers **both kinds of need**: one far-but-has-cars tract and three close-but-no-car tracts.

**Higher-scoring tracts we passed over (the "why not us?" answers):**

| Tract | Score | Why it was passed over |
|---|---:|---|
| `13121011421` | 78.1 | 1.6 km from Saturday 1, so it's likely the same people |
| `13121011431` | 77.0 | 0.5 km from Saturday 1 |
| `13121006802` | 76.2 | 0.9 km from Saturday 2. It has **68% no vehicle** and complete data |

**Effectively tied with Saturday 4:** `13121008701` (74.4) and `13121007808` (74.3, 3,749 people, 56% no vehicle). PLACES estimates are modeled, so a gap under 2 points isn't a real difference.

### Two places the plan should be challenged (the demo moment)

These are the "system rejects its own first answer" moments judges ask for.

**1. Saturday 2 was picked on incomplete data, and it displaced a tract with complete data.**
- `006801` has no vehicle figure. Its score uses the five inputs it has.
- Its neighbor `006802`, 0.9 km away, scored only 1 point lower, has full data, and has 68% of households without a car.
- A reviewer would reasonably swap them.

**2. Saturday 4 is the smallest tract in the plan, and it's tied with a much larger one.**
- `006602` has 1,050 people. `007808` is 1.9 points behind, has 3,749 people and 56% no vehicle.
- With one van-day, the larger tract probably reaches more people.

### Equity audit of the four picks

*Auditor only. Survey: ACS and SVI. 4 tracts is a tiny sample, so always show this next to the top-10% table above.*

| Group | Fulton | The 4 picks | Ratio | Top 10% ratio |
|---|---:|---:|---:|---:|
| Hispanic | 7% | 29% | **4.11×** | 1.86× |
| Limited English | 1.8% | 6.1% | **3.49×** | 1.66× |
| No vehicle | 10% | 22% | 2.12× | — |
| Below poverty | 13% | 20% | 1.56× | 2.41× |
| Black | 43% | 56% | 1.30× | 1.72× |
| Age 65+ | 12% | 5% | **0.39×** | 1.00× |
| White | 39% | 9% | 0.22× | 0.23× |
| Asian | 7% | 1% | 0.09× | 0.13× |

**What to say:**
- **The flyer must be in Spanish.** Hispanic residents are 29% of the people in these four tracts (4.11×), and limited-English households run 3.5× the county rate. The data, not a guess, sets the language list.
- **The plan under-reaches older residents (0.39×).** This follows from our definition: the uninsured input counts adults 18–64, and almost everyone over 65 has Medicare. It's a defensible choice, but say it out loud. A preventive van that reaches few 65+ residents is a trade-off, not an accident.
- **The plan goes where people can't get to care:** households with no vehicle are 2.12× the county rate.
