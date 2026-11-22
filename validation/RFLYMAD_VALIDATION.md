# Validation against real flights (RflyMAD)

*22 November 2026. The data and the scripts that produced these numbers are listed at the end.*

*Corrected later the same day after re-deriving the figures from the two CSVs: fault durations, what
the mode changes in the real flights mean, which "jump" figures are real fault sizes, and how often
PX4 rejected the readings. The tool's own results in section 3 were scored with the earlier rule
(safety mode within 5 s of the fault being switched on); re-score the batch before quoting them.*

## What was compared

**RflyMAD** is a public multicopter fault dataset from Beihang University's Reliable Flight Control
group (published in the International Journal of Robotics Research, 2025). We used its
**real-flight sensor-fault set**: **197 real PX4 quadcopter flights** in which a sensor fault was
injected in flight:

| Sensor | Flights | Fault types injected |
|---|---|---|
| GPS | 43 | noise (16), "scale" (27) |
| Accelerometer | 34 | noise (11), scale factor (23) |
| Gyro | 39 | noise (17), scale factor (22) |
| Compass | 36 | noise (16), scale factor (20) |
| Barometer | 45 | noise (18), scale factor (27) |

The flights cover hover, waypoint, velocity, circling and acceleration manoeuvres. Faults last
4 to 116 s (median 41 s) and are then switched off. Every flight was in scripted (OFFBOARD) mode when
the fault was injected, and a safety pilot supervises every flight.

**What a comparison can and cannot show.** RflyMAD was flown with **PX4**; our tool uses **ArduPilot**.
RflyMAD injects **noise** and **scale-factor** faults; ours injects **bias, drift, jumps, jamming and
total loss**. The real flights have no ground-truth position, and the fault is switched off before
the flight ends. So verdicts can't be matched one-to-one. What the data *can* show:
1. **How big real noise faults are**, so we can judge whether our five levels are realistic.
2. **Whether a real autopilot's estimator rejects the bad readings.** It cannot show whether an
   automatic safety mode would have switched on, because the faults end first (section 2).

## 1. How big real faults are

Measured from each flight's PX4 log: the faulted sensor's fast noise in the 10 s before and during
the fault (slow flight motion removed), and its largest jump from the pre-fault average.
Values are medians over flights; the maximum is in brackets. The "largest jump" of a **scale** fault
on GPS or compass is mostly the drone's own movement, not the fault: for GPS it is 1.5 m in hover
flights but about 140 m in velocity and acceleration flights, and for compass 63 mGauss in hover but
664 in circling flights. Those two cells are marked † and are not used as fault sizes. Noise-fault
jumps and barometer jumps are similar in hover and in moving flights, so they are fault sizes.

| Sensor | Fault type | Fast noise before → during | Largest jump during fault | Our levels (L1 → L5) |
|---|---|---|---|---|
| **GPS** | noise | 0.3 m → **17 m** (340 m) | **67 m** (1,133 m) | jumps of 5, 20, 60 m → jamming → dead |
| GPS | "scale" | 0.06 m → 0.2 m | 47 m (160 m) † | |
| **Barometer** | noise | 0.27 m → **81 m** (206 m) | **324 m** (695 m) | drift 0.05 → 1.0 m/s (≈ 8 → 170 m by the end of a flight) |
| Barometer | scale | 0.23 m → 0.32 m | **83 m** (409 m) | |
| **Compass** | noise | 12 → **450 mGauss** (1,000) | **1,300 mGauss** (3,229) | offsets of 50 → 1,000 mGauss |
| Compass | scale | 14 → 13 mGauss | 361 mGauss (832) † | |
| **Accelerometer** | noise / scale | 5.7 → 5.8 m/s² | (lost in vibration) | bias 0.1 → 2.5 m/s² |
| **Gyro** | noise / scale | 0.67 → 0.80 rad/s | (lost in vibration) | bias 0.005 → 0.2 rad/s |

**What this says about our levels:**
- **GPS:** real **noise** faults (median jump 41 to 74 m in every manoeuvre, hover included) are
  around our **L3 (60 m)**. Our L1 (5 m) and L2 (20 m) are *milder* than the noise faults in the set,
  which is good: the tool tests below the real-world range too.
  Real faults are mostly **noise**, while ours are **steady offsets**. Both are realistic: steady
  offsets are what spoofing produces.
- **Barometer:** real faults are **abrupt and large** (steps of tens to hundreds of metres). Ours is a
  **slow drift**, which ends up at similar totals by L3–L5 but builds up gradually. That makes it
  harder for an autopilot to notice, as the results confirm (see section 2).
- **Compass:** real **noise** faults (median jump 1,300 mGauss, 576 in waypoint flights) are at or
  above our **L5** (1,000 mGauss). The size of the real scale faults could not be separated from the
  drone turning.
- **Accelerometer and gyro:** in real flights the injected noise and scale faults are **smaller than
  the drone's own vibration** (raw IMU noise about 5.7 m/s² and 0.67 rad/s), so they barely show in
  the data. Our biases (up to 2.5 m/s² and 0.2 rad/s) are steady offsets that vibration does not hide.
  The real fault sizes could not be measured, so this data neither supports nor contradicts our levels.

## 2. How a real autopilot reacted

| Sensor | Estimator rejected the readings?* | Automatic safety mode | What happened |
|---|---|---|---|
| GPS | in **29 of 43** flights (test ratio over 1; median 151) | none (0 of 43) | mode changed to manual altitude/position at the end of the fault window |
| Barometer | in **41 of 45** flights (median 91) | 2 of 45 (83 s and 87 s after the fault) | as above; 3 flights went to auto-land |
| Compass | in 3 of 36 flights | none | as above |
| Accelerometer / gyro | no | none | as above |

\* `estimator_innovation_test_ratios`: PX4 rejects a measurement when its ratio exceeds 1.

**What this means for our results:**
1. **PX4 rejected abrupt, noisy GPS and barometer faults in most flights.** In our tool, ArduPilot **did not reject a
   slow barometer drift**, and it **accepted a steady 20 m or 60 m GPS offset after about 20 s**. These
   are different fault shapes, not a contradiction. A gradual or steady error passes consistency
   checks that a sudden one fails. This supports keeping the drift and offset faults: they are the
   *hard* cases.
2. **The real flights do not show how fast an automatic safety mode would be.** Only 2 of 197
   flights triggered PX4's own failsafe, but the faults were switched off after a median of 41 s.
   In 159 of the 192 flights with a mode change, the first change came within 2 s of the fault
   window ending: that is the scripted test handing back control, not a reaction to the fault. So
   this data neither confirms nor contradicts our finding that ArduPilot's automatic safety
   reaction is often absent or slow.

## 3. Abrupt faults in our tool, compared with the real flights

Following recommendation 1 below, the tool now has seven **abrupt** fault families with ranges taken
from the real data (`group: abrupt` in `config/faults.yaml`). Batch `batches/abrupt-120x`:
1,080 flights (3 conditions × 4 winds × 7 families × 5 levels × 3 repeats), all logs complete.
Counts below cover the 24 flights per level in conditions the drone can fly in.

| Fault family | Safe up to (worst case) | What goes wrong beyond | Real fault range (RflyMAD) | Verdict in the real range |
|---|---|---|---|---|
| **GPS large jump** | **none** (unsafe from 100 m) | 100–200 m: follows the false position with no safety mode. 400 m: leaves the geofence. 700–1,100 m: EKF failsafe after **10 s** (limit 5 s) | jumps 47–67 m median, up to 1.1 km | **unsafe** (as the gradual 60 m jump) |
| **Barometer step** | 5 m | from 20 m: flies into the ground believing it is still up. 100–300 m: EKF failsafe after 10 s, still crashes | jumps 83–324 m median | **unsafe** |
| **Barometer noise** | ±5 m (sd 2.9 m) | from ±20 m: follows a false height or flies into the ground | noise sd about 81 m | **unsafe** |
| **Compass noise** | ±1,700 mGauss (all levels) | — | noise sd about 450 mGauss (max 1,000) | **safe** |
| **Compass scale** | ×1.5 (all levels; 1 isolated failure at ×1.2 in Ladakh extreme wind) | — | ×0.8–1.5 | **safe** |
| **Accelerometer scale (vertical)** | ×1.1 | ×1.15: flies into the ground; ×1.2: loses control in some cases | ×0.85–1.2 | **unsafe at the top of the range** |
| **Gyro scale** | +25% (all levels) | — | ×0.9–1.15 | **safe** |

**Comparison with PX4 in the real flights:**
- **GPS and barometer.** PX4 **rejected** abrupt GPS and barometer faults in most real flights (29 of 43
  and 41 of 45). ArduPilot with default settings, in our simulation, **did not reject**
  GPS jumps of 100–400 m or barometer steps of 20 m or more before they caused a failure. Its EKF
  failsafe needed about **10 s**, and only for the largest faults. This is the most important
  finding of the validation: for the generic ArduPilot quadcopter, **GPS and barometer integrity
  checks are the weak point**, whether the fault is gradual or sudden.
- **Compass and gyro.** Both autopilots coped. No automatic action was needed, and the drone held course.
- **Accelerometer scale.** Real scale faults up to ×1.2 sit above our ×1.1 safe limit, so the top of the
  real range would be unsafe for this drone.

**Caveats.** PX4 and ArduPilot are different autopilots, and our drone uses default ArduPilot settings
on a generic frame. In the real flights a rejected measurement doesn't show whether the drone
*would* have survived, because the fault was switched off and control handed back. The comparison shows which faults each
autopilot detects, not a like-for-like survival rate. A maker can tune ArduPilot's EKF innovation
gates and failsafe timing (for example `EK3_POS_I_GATE`, `EK3_HGT_I_GATE`, `FS_EKF_THRESH`), and
running the tool on *their* parameter file (`--params`) is how to check that.

**Scoring note.** While reviewing this batch, the "flew into the ground" crash rule was refined: it now
counts only when the drone touched the ground while believing it was more than 5 m up **and did not
then land and switch off by itself**. A 5 m barometer step had been flagged although the drone touched
down at a normal 0.5 m/s and disarmed. Re-scoring changed 24 barometer-step level-1 flights, plus 4
borderline barometer-noise and accelerometer flights, to PASS. The gradual-fault batch
(`batches/week4-final-120x`) was unchanged: its barometer crashes were drones left sitting on the
ground with motors running.

## Data-quality notes

- 6 flights in RflyMAD's *GPS* folder carry the **magnetometer** fault ID (123455), and 1 flight in the
  *compass* folder carries the **gyro** ID (123453). The folder and fault labels disagree for these
  7 cases. They are kept in the tables under their folder, and they don't change any median materially.
- The "acceleration" (`dece-*`) folders in the real set are empty.
- Means shift during every fault window because the drone moves, so only noise levels and jumps
  are used as fault-size measures.

## Recommendations for the tool

1. **Add abrupt fault types alongside the gradual ones.** *(Done; see section 3. Still to do:
   horizontal GPS noise, which needs the runner to drive it because Copter-4.7.3's simulator has no
   parameter for it.)* These match what RflyMAD and most test
   houses inject, and they show whether ArduPilot rejects them as PX4 did:
   - GPS noise of 5–50 m (and jumps beyond 60 m);
   - barometer steps of 20–300 m (`SIM_BARO_GLITCH`) and noise (`SIM_BARO_RND`);
   - compass noise up to 1,000 mGauss (`SIM_MAG_RND`) and scale errors of 0.8–1.5 (`SIM_MAG1_SCALING`);
   - accelerometer and gyro scale errors of 0.85–1.2 (`SIM_ACC1_SCAL`, `SIM_GYR1_SCALE`).
2. **Keep the drift and offset faults.** They are the cases a real estimator doesn't catch.
3. **Report "no automatic safety mode" prominently.** In real supervised flights the pilot is the
   safety net; the report should say plainly what happens without one.

## Licence

RflyMAD is copyright of the Reliable Flight Control Group, Beihang University. Its dataset page says
it is *"supposed to be used in non-commercial situations"*; commercial use needs their agreement.
Since this tool is intended as a product, get permission before citing this validation in sales or
certification material.

## Files

| What | Where |
|---|---|
| Raw downloads | `E:\datasets\rflymad\raw\` (SampleData.zip 340 MB, Real-Sensors.zip 4.01 GB) |
| Extracted data | `E:\datasets\rflymad\extracted\` (197 flights, 14.3 GB) |
| One row per flight: fault, sensor changes, PX4 reaction | [rflymad_real_sensor_cases.csv](rflymad_real_sensor_cases.csv) |
| Fault sizes in physical units | [rflymad_fault_magnitudes.csv](rflymad_fault_magnitudes.csv) |
| Scripts | `tools/rflymad_inspect.py`, `tools/rflymad_survey.py`, `tools/rflymad_summary.py`, `tools/rflymad_magnitudes.py` |
