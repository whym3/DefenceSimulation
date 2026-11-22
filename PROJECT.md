# Drone sensor-fault test tool: project overview

*Last updated: 22 November 2026. This file is the running record: what has been achieved, what it
proves, and what to do next. Update it whenever one of those changes.*

## What this project is

A **drone test tool that runs on one computer, with no real drone needed.** It answers one question
for a drone maker or a military buyer:

> *"Up to what point is this drone safe when a sensor goes wrong, and what happens beyond it, in
> Indian conditions?"*

It works in five steps, all automatic:

1. **Fly a mission in simulation.** A virtual quadcopter flies a patrol and returns to base, using
   real flight software: ArduPilot, the same software that flies real drones.
2. **Break one sensor at a time.** GPS, accelerometer, gyro, compass or barometer (height sensor),
   each at five levels from mild to severe.
3. **Add Indian conditions.** Delhi as the baseline, the thin air of Ladakh, the heat of Rajasthan,
   and four wind levels taken from real weather data.
4. **Record what the drone does.** Position error in metres, whether it finished the mission, whether
   its safety mode switched on and how fast, and whether it crashed or left its geofence.
5. **Print a report.** A PDF of a few pages saying "this drone is safe up to here and fails beyond
   here" for each sensor and condition.

### Why it matters

- India's drone certification scheme (QCI / DGCA, tested by bodies such as ARAI, UL, SGS and Bureau
  Veritas) sets **no numeric limits** for GPS loss or wind. Instead it asks each manufacturer for
  **test reports showing that its declared limits and emergency behaviour work**. This tool produces
  that evidence before a costly certification flight test.
- The scheme makes **geofencing mandatory** and covers **−10 °C to +50 °C**. The tool checks both.

### The bigger plan (layers added later)

| Layer | What it adds | When |
|---|---|---|
| 1. Cameras | Normal and thermal camera tests in dust, fog, rain and darkness | When someone uses the sensor tool |
| 2. Vendor comparison | Several makers' drones through the same tests, side by side | What the Army and Air Force would buy |
| 3. Realistic 3D scenes | Unreal Engine mountains, desert and night | Cameras need realistic visuals |
| 4. Counter-drone | Radar, radio and camera detection of enemy drones | Many sensors working together |
| 5. Sensor fusion | Combining sensors and knowing which one to distrust | Builds on what the tests teach |
| 6. Decision dashboard | One screen for commanders, with human-approved suggestions | The long-term company |

**Rule for moving on:** add the next layer when someone is *using* the one before it, not when it
is finished.

---

## Decisions taken

| Topic | Decision | Why |
|---|---|---|
| Flight software | **ArduPilot first** (Copter-4.7.3), PX4 later | ArduPilot's simulator can break every sensor at an adjustable strength; PX4's simulator mostly offers on/off GPS failures |
| Drone type | **Quadcopter only** | Fits the time box; fixed-wing later |
| Which drone | **Generic ArduPilot quadcopter** by default; any drone's parameter file with `--params`, any frame model with `--model` | No vendor yet. First specific airframe flown: ArduPilot's Callisto model |
| Pass | Mission completed, position error under **10 m** | Agreed with the project owner |
| Safe fail | Safety mode no later than **5 s after the position error passes 10 m** (or before it gets that large), then a safe landing, no fence breach | Changed 22 Nov 2026: timed from fault injection, slow faults could never be caught "in time" |
| Unsafe | Fence breach, crash, safety mode later than that, or over 10 m error with no safety mode | A crash or breach now counts even when the flight log is cut short |
| Platform | Windows PC, simulator in **WSL2 Ubuntu 24.04**; also runs on an Apple-silicon Mac | Runs offline; zones can be split across machines |
| Weather data | **NASA POWER** hourly data 2020–2024, cached locally | Free, no account, offline afterwards |

---

## What has been achieved

The four-week plan for the first product is essentially complete.

### Week 1: simulator and first test ✅
- ArduPilot Copter-4.7.3 built and running in WSL2 Ubuntu 24.04.
- Patrol mission: take-off to 50 m, a 1.5 km square loop, return home, inside a 600 m geofence.
- First fault test (GPS cut) and an automatic log analyser comparing the simulator's true position
  with where the drone *believed* it was.

### Week 2: all sensors, five levels each ✅
- 5 sensors × 5 levels, defined in one settings file (`config/faults.yaml`).
- Parallel batch runner (up to 12 simulators at once) with live progress output.
- Hardened scoring after real cases exposed mistakes:
  - **vertical errors** count, not just horizontal;
  - **flying into the ground** while believing it is airborne counts as a crash;
  - only an **actual safety-mode switch** counts as a reaction, not a warning message;
  - a **fence breach** means the *true* position left the fence, not a false alarm from a jammed GPS.

### Week 3: Indian conditions ✅
- Real weather statistics for Delhi, Leh and Jaisalmer from NASA POWER.
- Heat and altitude modelled through **density altitude**: Ladakh in summer flies like 4,598 m
  (air 63% of sea level). Rajasthan at 43 °C flies like 1,227 m.
- Confirmed in the simulator that thin air makes the motors work harder (about 74% output in Ladakh
  against 61% in Delhi).
- Four wind levels per site (calm, typical, strong, extreme), up to 13.3 m/s.
- Full matrix: **780 flights** (3 conditions × 4 winds × 26 tests × 3 repeats).
- **Speed:** found that telemetry flooding was holding the simulator back. Fixed: each flight now
  takes about 5–7 s, and the whole 780-flight matrix runs in about 18 minutes on one PC. A 120× vs 80×
  check gave identical safe limits in all 60 sensor groups.

### Week 4: report, one-command demo, real-flight validation ✅
- **PDF report** generated automatically after every batch: a summary page, a colour-coded safe-limit
  table, one page per sensor with a verdict grid, and the method and limitations.
- Report honesty checks: limits that rest on only a few flights are flagged as isolated.
- **One command:** `python demo.py` gives the report from a small set (52 flights then; 122 now that the abrupt faults are included); `--full` runs everything.
- Fixed flight logs being cut short at high speed (affected 1.4% of flights). Incomplete logs are
  now marked ERROR instead of being judged.
- **Compared with 197 real flights** from the RflyMAD dataset (PX4 quadcopters with injected
  sensor faults). See [validation/RFLYMAD_VALIDATION.md](validation/RFLYMAD_VALIDATION.md). The first
  write-up claimed more than the data shows and was corrected on 22 November 2026:
  - **what holds:** real noise faults are as large as our harsher levels (GPS jumps of 41 to 74 m
    against our L3 = 60 m; compass 576 to 1,500 mGauss against our L5 = 1,000; barometer tens to
    hundreds of metres). PX4 rejected the bad GPS readings in 29 of 43 flights and the bad barometer
    readings in 41 of 45;
  - **what does not hold:** the real flights say nothing about how fast a safety mode would react.
    The faults were switched off after a median of 41 s and the mode changes seen are the scripted
    test ending, not a reaction. Accelerometer and gyro fault sizes could not be measured.
- **Abrupt faults added** (7 families: GPS large jump, barometer step and noise, compass noise and
  scale, accelerometer and gyro scale), with ranges matched to the real flights. 1,080 flights in
  `batches/abrupt-120x` (report included). Result: **GPS and barometer integrity are this drone's weak
  point.** It follows GPS jumps of 100 m and more, and flies into the ground after barometer steps of
  20 m and more, with the EKF failsafe coming only after about 10 s for the largest faults. PX4
  rejected the same kinds of fault in the real flights. Compass and gyro faults are handled at every
  level.

### 22 November 2026: review, fixes, first full runs on new machines ✅
- **Code review of the whole tool** and a market survey (India and worldwide). Outcome: build the
  virtual-testing layer only for now; 3D viewers and command-and-control pictures are crowded markets.
- **Scoring made fairer and safer:** reaction timed from when the fault becomes dangerous; crashes and
  fence breaches no longer hidden by a cut-short log; a level with a flight that could not be judged
  is no longer counted as safe (shown as "not verified").
- **A specific drone can be tested:** `--params` loads its ArduPilot parameter file and `--model` its
  frame model. The report names the file, its hash, the ArduPilot version and the tool commit.
- **Tests added:** `tests/test_verdicts.py`, 11 checks of the scoring rules that need no simulator.
- **Twice as fast:** flights were waiting 8 s for a log that never stops growing. Fixed; Delhi at
  typical wind (183 flights) went from about 4.5 to 2.4 minutes with identical safe limits.
- **Runs on two machines:** set up from scratch on a new Windows PC and on a MacBook (M1). The same
  GPS-loss flight gave the same verdict on both (safety mode at 8.0 s and 8.1 s).
- **Full matrix flown, one batch per zone:** 1,830 flights, every log complete. Delhi and Ladakh on
  the PC, Rajasthan on the MacBook. Reports: `batches/delhi-120x`, `batches/ladakh-120x`,
  `batches/rajasthan-120x` (each has `report.pdf`).
- **First specific airframe:** the Callisto, a 32.5 kg heavy-lift octocopter whose physics model and
  settings ship with ArduPilot, flies the mission in Delhi and Ladakh. On GPS loss it returns home on
  its dead-reckoning failsafe after 10.5 s; the generic quad lands on its EKF failsafe after 8 s.
- **Callisto full matrix flown:** 1,830 flights in 19 minutes on the PC, every log complete
  (`batches/callisto-120x/report.pdf`). 1,122 pass, 178 safe fail, 530 unsafe. Comparison below.
- **Working rule from now on:** when the MacBook is reachable, batches are split with it; results are
  copied back to the PC, verified, and then cleared from the Mac.

### Main findings (generic quadcopter, simulation, 22 November 2026 batches)

Worst case over the three zones and every wind the drone can fly in.

| Sensor fault | Safe up to | What goes wrong beyond |
|---|---|---|
| Barometer slow drift | none of the tested levels | Even 0.05 m/s: follows a false height with no safety mode |
| GPS large jump (100 m and up) | none of the tested levels | Follows the false position; at 700 m and more the fence alarm lands it, and about one flight in five then sits on the ground with motors running |
| GPS gradual | L1: 5 m jump | At 20 m it flies the route shifted, with no safety mode. GPS dead: safety mode after 8 s and a safe landing |
| Barometer step | L1: 5 m | From 20 m: follows a false height |
| Barometer noise | L2: ±5 m | From ±20 m: follows a false height |
| Gyro bias | L3: 0.03 rad/s | Loses control and crashes at 0.08 rad/s |
| Accelerometer bias | L3: 0.6 m/s² (L5 in most conditions) | Follows a false position |
| Accelerometer scale | L3: ×1.1 | Flies into the ground at ×1.15 |
| Compass offset | L1 (isolated: L5 in most conditions) | Left the geofence in strong or extreme wind; harsher levels passed |
| Compass noise, compass scale, gyro scale | all tested levels | — |
| Wind (no fault) | — | Cannot fly the mission at 12.2 m/s in Delhi or 13.3 m/s in Jaisalmer. Flies at 12.1 m/s in Ladakh: the air there is 63% as dense, so the wind pushes about as hard as 9.6 m/s in Delhi |

Verdict counts: Delhi 258 pass, 32 safe fail, 140 unsafe, 180 not tested (extreme wind); Ladakh 375,
54, 181, 0; Rajasthan 260, 30, 140, 180.

### Generic quad against Callisto: a first vendor-style comparison

Same 1,830 tests, same scoring, two airframes. Worst case over every condition each drone can fly in.

| Test | Generic quad | Callisto (32.5 kg octocopter) |
|---|---|---|
| Extreme wind, no fault | Cannot fly in Delhi (12.2 m/s) or Rajasthan (13.3 m/s) | Flies the mission in all three zones |
| Compass offset | L1 (leaves the geofence in strong wind) | L5: safe at every level |
| Accelerometer bias | L3 | L4; at L5 it leaves the geofence |
| Barometer slow drift | none | L1 (0.05 m/s) **see note** |
| GPS gradual | L1 (5 m jump) | L1; up to L3 in calm Ladakh |
| GPS large jump | none | none; up to L2 in calm Delhi |
| Gyro bias | L3; beyond it leaves the geofence | L3; beyond it hits the ground at 12.7 m/s |
| Accelerometer scale | L3; beyond it flies into the ground | L3; beyond it does not land |
| Barometer step, barometer noise | L1, L2 | L1, L2 |
| Compass noise, compass scale, gyro scale | all levels | all levels |

- **What the comparison shows:** the heavier airframe handles wind and compass faults much better,
  and both share the same weak points: GPS and barometer integrity.
- **Note on barometer drift:** the Callisto's better result is partly an effect of the test, not of
  the drone. It flies the route faster (about 272 s against 353 s), so a slow drift has less time to
  build up before landing: at 0.05 m/s the generic quad ends at about 10.3 m of height error, just
  over the 10 m limit. A fair comparison of drift faults needs a fixed time under fault.

### What this proves, and what it does not

**Proves**
- The method works end to end: one autopilot, one broken sensor, a chosen place and wind, an
  automatic verdict, and a report, 1,830 times in under an hour with nobody at the controls.
- It finds things a buyer would act on: for this drone, GPS and barometer integrity are the weak
  points and compass and gyro scale faults are not a concern.
- Environment changes the answer: wind decides whether the mission can be flown at all, and thin air
  shifts that limit.
- Two airframes give different answers to the same fault, which is the basis of a vendor comparison.
- Results reproduce across machines and operating systems.

**Does not prove**
- Anything about a product on sale. The generic quad and the Callisto model are both ArduPilot's own.
- Real-world accuracy. No result has been checked against a real flight of the same drone.
- A failure rate. Each limit rests on three repeats, and some fault levels fail in roughly one flight
  in five because the autopilot itself behaves in two ways (8 of 183 verdicts differed between two
  identical runs).
- Radio-level jamming. Faults are injected at the sensor, not as radio signals.
- Group behaviour, combat effectiveness or value for money.

---

## How to use it

```bash
wsl -d Ubuntu-24.04
source ~/venv-drone/bin/activate
cd <this repo>
python demo.py            # 1-minute demo + PDF report
python demo.py --full     # full 1,830-flight matrix + PDF report
```

Details are in [README.md](README.md); developer notes are in [CLAUDE.md](CLAUDE.md).

---

## Next steps

### Make the numbers defensible (short term)
1. **Confidence numbers.** More repeats at the levels around each safe limit, and a stated confidence
   beside each limit, because some levels fail one flight in five.
2. **GPS-denied faults:** slow GPS spoofing drag, radio-control loss and ground-link loss. These are
   what the Army's post-2025 trials are reported to fail drones on, and they are the market opening.
3. **Make drift faults comparable between drones:** hold the fault for a fixed time (or a fixed
   distance) instead of "until the mission ends", so a faster drone is not flattered.
4. **Tuning study:** rerun the GPS and barometer faults with tighter EKF innovation gates and a faster
   `FS_EKF_THRESH`, to show makers how much their settings would raise the safe limit.
5. **Harder levels** for accelerometer bias and compass, whose breaking points are still unknown, and
   horizontal GPS noise (the simulator has no parameter for it, so the runner must drive it).
6. **Investigate the compass anomaly** (unsafe at L2 in strong wind while L3 to L5 pass).
7. **Score the 120 m geofence ceiling**; today only the 600 m circle is checked.
8. **Cold weather:** a Ladakh winter condition (−24 °C) with a cold-battery model.

### First user (the rule for moving on)
9. **Talk to five drone makers** with a sample report in hand. Ask whether they would pay for a
   pre-trial readiness report and which autopilot they use; that decides whether ArduPilot-only is
   enough. Ask for the parameter file plus weight, motors, propellers and battery.
10. **Shape the report** to match the certification scheme's wording, so it can go into a
    type-certification file as supporting evidence.
11. **Before any sales use:** confirm the single-source press claims about failed GPS-denied trials,
    and take legal advice on the non-commercial RflyMAD data, on GPL duties if ArduPilot binaries are
    shipped, and on ArduPilot's stance on military use. Choose a licence for this repository.

### After that (only once someone is using it)
12. **PX4 support**, since many Indian makers use PX4.
13. **Fixed-wing and VTOL** drones.
14. **Layer 1: cameras.** Normal and thermal camera tests in dust, fog, rain and darkness. This is
    where the Unreal Engine setup (already connected) comes in, for realistic scenes.
15. **Layer 2: vendor scorecard.** Several drones through the same tests, side by side.
