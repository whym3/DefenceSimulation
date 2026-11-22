# Drone sensor-fault test tool: project overview

*Last updated: 22 November 2026*

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
| Which drone | **Generic ArduPilot quadcopter** | No vendor yet; a maker's parameter file can replace it |
| Pass | Mission completed, position error under **10 m** | Agreed with the project owner |
| Safe fail | Safety mode switched on within **5 s**, then a safe landing, no fence breach | Agreed |
| Unsafe | Fence breach, crash, more than **50 m** error with no safety mode, safety mode later than 5 s | Agreed |
| Platform | Windows PC, simulator in **WSL2 Ubuntu 24.04** | Runs offline on one machine |
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
- **Validated against 197 real flights** from the RflyMAD dataset (PX4 quadcopters with injected
  sensor faults). See [validation/RFLYMAD_VALIDATION.md](validation/RFLYMAD_VALIDATION.md):
  - **our fault sizes are realistic:** real GPS faults are 47–67 m jumps (our L3 = 60 m); real compass
    faults are 360–1,300 mGauss (our L3–L5 = 300–1,000); real barometer faults reach tens to hundreds
    of metres, which our L3–L5 drift also reaches by the end of a flight;
  - **real faults are mostly abrupt noise, ours are gradual drift and steady offsets.** PX4 rejected
    the abrupt GPS and barometer faults; ArduPilot in our tests did not reject slow drift or steady
    offsets. The gradual faults are the hard cases, which is worth keeping;
  - **only 2 of 197 real flights triggered an automatic failsafe.** The safety pilot handled the
    rest. That supports the tool's focus: what happens when no pilot is there to take over.
- **Abrupt faults added** (7 families: GPS large jump, barometer step and noise, compass noise and
  scale, accelerometer and gyro scale), with ranges matched to the real flights. 1,080 flights in
  `batches/abrupt-120x` (report included). Result: **GPS and barometer integrity are this drone's weak
  point.** It follows GPS jumps of 100 m and more, and flies into the ground after barometer steps of
  20 m and more, with the EKF failsafe coming only after about 10 s for the largest faults. PX4
  rejected the same kinds of fault in the real flights. Compass and gyro faults are handled at every
  level.

### Main findings so far (generic quadcopter, simulation)

| Sensor | Safe up to (worst case) | What goes wrong beyond |
|---|---|---|
| GPS | L1: 5 m position jump | At 20 m and 60 m jumps it accepts the false position and flies the whole route shifted, with no safety mode. GPS dead: safety mode after about 8 s (limit 5 s) |
| Accelerometer | L4: 1.2 m/s² bias (L5 in normal wind) | In strong wind, flies into the ground at 2.5 m/s² |
| Gyro | L3: 0.03 rad/s bias | Loses control and crashes at 0.08 rad/s |
| Compass | L1 (isolated: 2 flights) | Every harsher level passed; needs investigation |
| Barometer | none of the tested levels | Even 0.05 m/s drift: it sinks while believing it holds height, and flies into the ground |
| Wind | — | Cannot fly the mission at all in 12–13 m/s at Delhi or Jaisalmer; manages 12 m/s in Ladakh, where thin air pushes less |

*Confirmed by the final week-4 batch (`batches/week4-final-120x`): 780 flights, every flight log
complete, and safe limits identical to week 3 in all 60 sensor groups. The full report is
[batches/week4-final-120x/report.pdf](batches/week4-final-120x/report.pdf).*

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

### Finish the first product (short term)
1. ~~Add abrupt fault types~~ (done, see above). Remaining: **horizontal GPS noise**, which needs the
   runner to drive it because the simulator has no parameter for it. Then a **tuning study**: rerun the
   GPS and barometer faults with tighter EKF innovation gates and a faster `FS_EKF_THRESH`, to show
   makers how much their settings would raise the safe limit.
2. **Harden the fault levels.** The accelerometer and compass passed almost every level, so the
   breaking point is still unknown. Add harsher levels such as larger bias, compass interference from
   motor current, and local magnetic disturbance.
   - **Licence check:** RflyMAD is for non-commercial use; ask Beihang's Reliable Flight Control group
     before citing the validation in sales or certification material.
3. **Investigate the compass anomaly.** Two flights at level 2 left the geofence in strong wind while
   levels 3–5 passed. Find out whether it's a real failure mode or a simulator artefact.
4. **More repeats for GPS jamming.** Jamming uses random data; about 10 repeats would give a reliable
   failure rate instead of a 3-repeat snapshot.
5. **Cold weather.** Add a Ladakh winter condition (−24 °C) together with a cold-battery model;
   battery capacity loss in the cold is not modelled yet.
6. **Put the code under version control** (git) and tidy old trial batches.

### First user (the rule for moving on)
7. **Find a first user:** a drone maker or a unit willing to run the tool on *their* drone. Ask for
   the ArduPilot parameter file plus weight, motors, propellers and battery, so the report describes
   their aircraft instead of a generic one.
8. Shape the report to match the certification scheme's wording, so it can go into a type-certification
   file as supporting evidence.

### After that (only once someone is using it)
9. **PX4 support**, since many Indian makers use PX4.
10. **Fixed-wing and VTOL** drones.
11. **Layer 1: cameras.** Normal and thermal camera tests in dust, fog, rain and darkness. This is
    where the Unreal Engine setup (already connected) comes in, for realistic scenes.
12. **Layer 2: vendor scorecard.** Several drones through the same tests, side by side.
