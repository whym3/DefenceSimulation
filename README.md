# Drone test tool

Flies a quadcopter mission in the ArduPilot simulator, breaks one sensor at one of five levels,
and scores what the drone does. It runs offline on one PC.

## Setup (once)

Inside WSL Ubuntu (`wsl -d Ubuntu-24.04`):

```bash
bash setup/build_ardupilot.sh   # clones ArduPilot Copter-4.7.3 and builds the simulator
```

## Quick start: one command

```bash
source ~/venv-drone/bin/activate
cd <this repo>           # under WSL, a Windows folder is /mnt/c/...
python demo.py          # 122 flights (Delhi + Ladakh, typical wind, all 12 fault families) + PDF report
python demo.py --full   # the full 1,830-flight matrix + PDF report
python tests/test_verdicts.py   # checks the scoring rules on made-up flights; no simulator needed
```

The report is written to `batches/<name>/report.pdf`. It has a one-page summary of each sensor's
safe limit, a colour-coded table by condition and wind, one page per sensor with a verdict grid and
what goes wrong at each level, and the method and limitations.

## Run tests

```bash

python run_one.py                                          # one baseline flight (Delhi, typical wind)
python run_one.py --fault gps --level 5                    # one fault flight
python run_one.py --condition ladakh --wind strong --fault barometer --level 2
python run_batch.py                                        # everything: 3 conditions x 4 winds x 61 tests x repeats (1,830 flights)
python run_batch.py --params my_drone.parm --model quad    # test a specific drone's ArduPilot parameter file
python run_batch.py --conditions delhi --winds typical     # one condition and wind
python run_batch.py --sensors compass --levels 4 5 --repeats 1 --parallel 4
```

Weather data is fetched once with `python tools/fetch_weather.py` (NASA POWER, no account needed)
and cached in `data/`, so tests run offline.

- `run_one.py` saves `flight.BIN`, `sitl.out` and `result.json` under `runs/<run id>/`.
- `run_batch.py` saves every flight plus `summary.csv` (one row per flight), `envelope.json`
  (each sensor's safe limit) and `report.pdf` under `batches/<time>/`. Use `--no-report` to skip the
  PDF, and `python make_report.py batches/<name>` to rebuild it without flying.
- **Speed:** by default flights run at 120× real time on 12 simulators (each simulator actually
  reaches about 90×), about 4.5 s per flight; the 780-flight gradual matrix (`--group gradual`)
  takes about 10.5 minutes.
  Checks: 40× against 10× gave identical verdicts for 76 of 78 flights, and 120× against 80× gave
  identical safe limits in all 60 sensor groups. The only flight-level differences were GPS
  jamming, which uses random data. `tools/compare_batches.py A B` repeats this check.

## Faults

Defined in [config/faults.yaml](config/faults.yaml) as ArduPilot SITL `SIM_*` parameters, five
levels per sensor. Each fault hits every unit of that sensor (both IMUs, all compasses, both barometers).

| Sensor | Level 1 → 5 |
|---|---|
| GPS | 5 m, 20 m, 60 m position jump → jamming → receiver dead |
| Accelerometer | forward bias 0.1, 0.3, 0.6, 1.2, 2.5 m/s² |
| Gyro | roll bias 0.005, 0.01, 0.03, 0.08, 0.2 rad/s |
| Compass | offset 50, 150, 300, 600, 1000 mGauss |
| Barometer | height drift 0.05, 0.1, 0.25, 0.5, 1.0 m/s |

**Abrupt faults** (`group: abrupt`, ranges matched to 197 real RflyMAD flights; see
[validation/RFLYMAD_VALIDATION.md](validation/RFLYMAD_VALIDATION.md)):

| Fault family | Level 1 → 5 |
|---|---|
| GPS large jump | 100, 200, 400, 700, 1,100 m |
| Barometer step | 5, 20, 50, 100, 300 m |
| Barometer noise | ±2, ±5, ±20, ±60, ±150 m |
| Compass noise | ±100, ±300, ±600, ±1,000, ±1,700 mGauss |
| Compass scale error | field ×1.05, ×1.1, ×1.2, ×1.35, ×1.5 |
| Accelerometer scale error | vertical ×1.02, ×1.05, ×1.1, ×1.15, ×1.2 |
| Gyro scale error | rates +2, +5, +10, +15, +25% |

Run a group with `python run_batch.py --group gradual` or `--group abrupt` (the default is `all`).
Horizontal GPS noise has no simulator parameter in Copter-4.7.3, so it is not included yet.

**Repeats.** The simulator's random generator has a fixed seed, so repeats differ by wind
direction instead: 0°, 120° and 240°. Calm wind has no direction, so it gets one repeat.
Flights are still not exactly repeatable: the simulator is not locked to the test script, so the
moment the fault lands shifts slightly with computer load (2 of 78 verdicts differed between 10×
and 40×). Three repeats are three scenarios, not a failure-rate estimate.

**Drone under test.** By default the drone is ArduPilot's generic quadcopter with default settings.
`--params <file>` loads a drone's own ArduPilot parameter file (EKF gates, failsafe settings, tuning)
and `--model` picks the simulator frame model. The file's SHA-256, the ArduPilot version and this
tool's commit are saved in `result.json` and `envelope.json` and printed on the report's first page.
The test's own settings (geofence, wind) are applied on top of the file.

A frame model can also carry the airframe's physics (mass, rotors, battery, drag). ArduPilot ships
one for the Callisto, a 32.5 kg heavy-lift octocopter, with its parameter file:

```bash
python run_batch.py --model "octa-quad:@ROMFS/models/Callisto.json" \
    --params ~/ardupilot/Tools/autotest/models/Callisto.param --out batches/callisto-120x
```

**Run-to-run variation.** Some verdicts change between identical runs because the autopilot itself
behaves in two ways. Example: after a 700 m GPS jump the fence alarm lands the drone; in about four
flights in five it then switches its motors off within 3 s (SAFE_FAIL), and in the rest it sits on
the ground with motors running (UNSAFE). Which one happens depends on whether its estimator switched
lanes at the alarm. A level like this has a failure rate, not a fixed verdict, so three repeats can
miss it.

## Conditions

Defined in [config/conditions.yaml](config/conditions.yaml), using NASA POWER hourly weather for 2020–2024.

| Condition | Site, temperature | Flown at density altitude | Air vs sea level |
|---|---|---|---|
| delhi | Delhi, 25.1 °C (mean) | 622 m | 94% |
| ladakh | Leh (3,500 m), 24.9 °C (hot, 99th percentile) | 4,598 m | 63% |
| rajasthan | Jaisalmer, 43.0 °C (hot, 99th percentile) | 1,227 m | 89% |

- **Heat.** ArduPilot's quadcopter model thins the air with altitude but ignores temperature, so each
  condition is flown from its *density altitude*: the standard-atmosphere height with the same air density.
  At Ladakh the motors cruise at about 74% output against 61% in Delhi (`tools/hover_throttle.py`).
- **Leh temperature.** NASA POWER's grid cell for Leh averages 4,533 m, about 1,000 m above the town,
  so its temperatures are corrected to 3,500 m with the standard lapse rate (6.5 °C/km).
- **Wind levels**, from hourly wind at 50 m: calm (0), typical (50th percentile), strong (95th),
  extreme (99.9th), with turbulence at 30–40% of the mean wind. NASA POWER is hourly-averaged
  reanalysis, so real gusts are stronger than these figures.

| Wind at 50 m | typical | strong | extreme |
|---|---|---|---|
| Delhi | 4.2 m/s | 8.1 m/s | 12.2 m/s |
| Leh | 2.5 m/s | 6.0 m/s | 12.1 m/s |
| Jaisalmer | 5.1 m/s | 10.0 m/s | 13.3 m/s |

Not modelled yet: cold-battery capacity loss and IMU temperature effects.

## Scoring rules

| Verdict | Rule |
|---|---|
| PASS | Mission completed, landed within 10 m of home, position error under 10 m |
| SAFE_FAIL | The autopilot switched to a safety mode (failsafe mode change) no later than 5 s after the position error passed 10 m, or before it got that large, and landed, with no fence breach and no crash |
| UNSAFE | Fence breached, a crash, a safety mode more than 5 s after the position error passed 10 m, or anything else (including any other flight with over 10 m position error and no safety mode) |
| NOT_TESTED | The drone never reached the point where the fault switches on (for example it could not fly upwind), so the flight says nothing about the sensor |
| ERROR | The flight log ends with the drone still in the air and shows no fence breach or crash, so the ending is unknown. The batch runner flies such a flight once more |

The safety mode is timed from when the fault became dangerous, not from when it was switched on: a
slow drift is harmless for its first seconds, so no autopilot could react to it within 5 s of
injection. `result.json` gives both times (`failsafe_reaction_s` from the fault,
`reaction_after_hazard_s` from the 10 m point).

A level with a NOT_TESTED or ERROR flight is not counted as safe. The safe limit stops below it and
is marked `?` (`not_verified_level` in `envelope.json`): the level is neither proven safe nor unsafe.

If the baseline (no fault) fails in a condition and wind, that group's sensor limits show as **n/a**.

- **Position error** is the worse of horizontal and vertical error between the simulator's true
  position (`SIM` log message) and the drone's own estimate (`POS`).
- **Crash** means the autopilot's crash check fired, the drone touched down faster than 3 m/s, or it
  touched the ground while believing it was more than 5 m up *and* did not then land and switch its
  motors off by itself.
- **Warnings** such as "GPS glitch" are reported, but they don't count as a safety mode switching on.
- **Fence breach** means the drone's *true* position left the 600 m circle. The autopilot's own fence
  alarm can fire on a false position (for example under GPS jamming); that is reported as `fence_alarm`.
- A drone that flies into the ground while believing it is airborne never switches its motors off.
  The runner ends that flight once the simulator shows it sitting on the ground for 15 s.
- **Safe limit** of a sensor is the highest level at which every repeat, and every milder level,
  scored PASS or SAFE_FAIL.

## Mission

Take-off to 50 m, a 375 m square patrol loop (1.5 km) around home, then return to launch. A
600 m circular geofence with a 120 m ceiling is set. Scoring checks only the 600 m circle, not the
ceiling. Faults switch on as the drone leaves the second corner, about 265 m from home.
