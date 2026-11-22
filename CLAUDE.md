# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A Python tool that flies a quadcopter patrol mission in ArduPilot SITL (Copter-4.7.3), injects one sensor fault (5 sensors x 5 levels) mid-flight, then scores the DataFlash log as `PASS`, `SAFE_FAIL` or `UNSAFE`. Flights run under a condition (Delhi, Ladakh or Rajasthan, flown at density altitude) and a wind level taken from NASA POWER statistics. A batch runner flies conditions x winds x faults x repeats on several simulators in parallel and works out each sensor's safe limit per condition and wind. The scoring rules, fault levels, conditions and mission geometry are in [README.md](README.md).

## Environment

Everything runs inside **WSL Ubuntu** (`wsl -d Ubuntu-24.04`), not native Windows. The repo is reached under `/mnt/c/...`. Only `tests/test_verdicts.py` runs on plain Windows Python (it needs PyYAML only).

- One-time setup: `bash setup/build_ardupilot.sh`. It creates the venv `~/venv-drone`, installs pymavlink, clones ArduPilot into `~/ardupilot` and builds `build/sitl/bin/arducopter`. Override the release with `ARDUPILOT_TAG`. To check on a long build, use `setup/build_status.sh` (it tails `~/build.log`) and `setup/pip_status.sh`.
- `dtt/sitl.py` finds ArduPilot through `ARDUPILOT_DIR` (default `~/ardupilot`).
- Python dependencies: `pymavlink`, `reportlab` (pip, in the venv), `PyYAML` and `matplotlib`. PyYAML and matplotlib come from the system through the venv's `--system-site-packages`. `pdftoppm` (apt `poppler-utils`) renders report pages to PNG for checking. `tests/test_verdicts.py` checks the verdict chain and `envelope()` on made-up logs (no simulator); there is no linter config or package manifest.
- When calling `wsl` from Git Bash, set `MSYS_NO_PATHCONV=1` and put multi-command shell logic in a script file. PowerShell mangles `$` and `|` inside `wsl -- bash -c "..."`. `wsl.exe` also passes its command line through a Linux shell **before** `bash -c` runs, so `$var` set inside `bash -c '...'` (loop variables, `d=$(...)`) expands to empty. Put such logic in a `.sh` file, or compute values on the Git Bash side and pass them in literally.

## Commands

```bash
source ~/venv-drone/bin/activate
python run_one.py                                   # baseline flight (delhi, typical wind)
python run_one.py --fault gps --level 5 --repeat 1  # one fault flight; repeat N sets the wind direction
python run_one.py --condition ladakh --wind extreme --fault gyro --level 3
python run_one.py --fault gps --instance 1          # second simulator in parallel (TCP port 5770)
python tests/test_verdicts.py                       # scoring-rule tests; run after any change to analyze.py or envelope()
python demo.py                                      # 122 flights + report.pdf (--full: 1,830 flights)
python run_batch.py                                 # all conditions x winds x 12 fault families (1,830 flights; --group gradual: 780) -> batches/<time>/ incl. report.pdf
python run_batch.py --params drone.parm --model quad   # a specific drone's parameter file; also on run_one.py
python make_report.py batches/<name>                # rebuild report.pdf from summary.csv + envelope.json
python tools/check_logs.py batches/<name>           # verdict counts + flights whose log has no touchdown
python run_batch.py --conditions delhi --winds typical --sensors compass --levels 4 5 --repeats 1
python run_batch.py --group abrupt                  # only steps/noise/scale faults (gradual | abrupt | all)
python tools/compare_batches.py batches/<a> batches/<b>   # verdict diff on flights common to both (e.g. 40x vs 80x)
python tools/fetch_weather.py                       # re-download NASA POWER data -> data/weather*, needs internet
python tools/hover_throttle.py <run_dir> ...        # cruise throttle demand and motor PWM (thin-air check)
python tools/profile_flight.py 120 14               # wall-clock time per phase of one flight (speed bottlenecks)

# RflyMAD real-flight validation (data in E:\datasets\rflymad\extracted, read-only, untrusted input):
python tools/rflymad_survey.py /mnt/e/datasets/rflymad/extracted validation/rflymad_real_sensor_cases.csv
python tools/rflymad_summary.py validation/rflymad_real_sensor_cases.csv
python tools/rflymad_magnitudes.py /mnt/e/datasets/rflymad/extracted validation/rflymad_real_sensor_cases.csv validation/rflymad_fault_magnitudes.csv
python tools/rflymad_inspect.py <case_dir>          # one case: TestInfo sheet, ULog topics, fault marker

python tools/timeline.py runs/<run_id> [--every 10]   # events + horizontal/vertical drift around the fault
python tools/rescore_batch.py batches/<name>          # re-score a whole batch and rebuild summary.csv/envelope.json
python tools/rescore.py runs/<id> ...                 # re-score individual runs
python tools/check_mag.py <run_dir>                   # compass readings before/after the fault
python tools/check_simstate.py                        # SITL instance 2: confirm SIM_STATE truth arrives
python tools/debug_mission.py                         # SITL instance 1: mission upload handshake only
bash setup/stop_all.sh                                # kill any batch, run_one and arducopter processes
```

## Architecture

`run_one.py` `fly()` runs one test: start SITL, connect, `wait_ready()`, set `BASE_PARAMS` and the repeat's wind parameters, upload the mission, arm and take off in GUIDED, switch to AUTO, run the main loop, stop SITL, copy the log, delete the scratch directory, score the log, and write `result.json`. The main loop injects the fault when `MISSION_CURRENT.seq >= FAULT_AT_SEQ` and ends when the vehicle disarms or `--max-wall-s` passes.

The main loop also ends a flight with `meta.stuck_on_ground` once the simulator's true altitude (`SIM_STATE`, requested at `TELEMETRY_HZ` (2 Hz) with `MAV_CMD_SET_MESSAGE_INTERVAL`, because it is not in the standard streams) has been at ground level for `STUCK_ON_GROUND_S`. A drone that flies into the ground while believing it is airborne never disarms, so without this check the flight would run until `--max-wall-s`.

`run_batch.py` runs each flight as a `run_one.py` subprocess, using a thread pool and a queue of free SITL instance numbers. It prints `start`, result and `progress:` lines through `say()`, which holds a lock and flushes whole lines so they stream cleanly to a background task's output. It then calls `write_outputs()` to produce `summary.csv` and `envelope.json`. `--model`/`--params` reach `Sitl(model=, extra_defaults=)`; `dtt.sitl.provenance()` records the model, parameter-file hash, ArduPilot version and tool commit in `result.json` meta and `envelope.json["vehicle"]`, which `report.vehicle_text()` prints. `envelope.json` holds `groups["<condition>/<wind>"]`, each with a baseline and per-sensor safe limits. `tools/rescore_batch.py` reuses `row_from_result()` and `write_outputs()`; week-2 batches get wind `fixed-3ms`. **Don't edit `dtt/` or `run_one.py` while a batch is running**: each flight starts a fresh `run_one.py` that imports the current code.

- **`dtt/sitl.py`**: one `arducopter` process, started with `--wipe` in a scratch directory `~/dtt-work/<run_id>_i<N>`. Instance N listens on TCP `5760 + 10*N`. Startup waits for the text "Waiting for connection" in `sitl.out`. **Do not probe the port**: SITL would take the probe as its ground-station connection.
- **`dtt/flight.py`**: the `Vehicle` MAVLink client. It locks onto the autopilot's own heartbeat (component 1), because a target component of 0 makes mission upload fail. All vehicle state is updated only in `pump()`, and every wait or handshake loop reads messages through `pump()`. `wait_ready()` waits for "is using GPS", because mission upload returns `NO_SPACE` before boot finishes.
- **`config/conditions.yaml` + `dtt/conditions.py`**: a condition is a site plus a temperature case (mean, hot or cold) from `data/weather_stats.json`. `home(condition)` puts the SITL home altitude at the **density altitude** (`density_altitude_m`), because the SITL frame model (`SIM_Frame.cpp`) takes air density from altitude through ISA and ignores temperature. `wind(condition, level)` gives the 50 m wind percentile for the site and turbulence as a fraction of it. In `run_batch.py`, calm wind gets one repeat. `CTUN.ThO` is already compensated for air density by ArduPilot, so judge thin-air effects from motor PWM (`RCOU`).
- **`tools/fetch_weather.py`**: NASA POWER hourly API, per year 2020–2024. The grid-cell elevation (in the response geometry) can be far from the site's (Leh is +1,033 m), so temperatures are lapse-rate corrected to `elevation_m`.
- **`dtt/mission.py`**: the patrol mission and the fence parameters. Its `SITES` is used only by the debug tools; flights take their home from `conditions.home()`. A mission item's index in the list is its MAVLink sequence number. `FAULT_AT_SEQ = 4` depends on this layout, so update it whenever waypoints change.
- **`config/faults.yaml` + `dtt/faults.py`**: each fault family has a `group` (`gradual` by default, or `abrupt`), which `faults.sensors_in(group)` and `run_batch --group` use. Simulator semantics that are easy to get wrong: `SIM_ACCn_SCAL` *divides* the reading (a 1.2x error is 0.8333); `SIM_GYRn_SCALE` is in percent; `SIM_BARO_RND` and `SIM_MAG_RND` are uniform ±amplitude; `SIM_GPS1_NOISE` is a slow altitude sine, not noise. Each family has levels 1 to 5, and each level is a set of `SIM_*` parameters. A level may instead be a list of alternative sets; `Vehicle.apply_first_supported` uses the first set SITL accepts. `{north_m: X}` converts metres to degrees, because `SIM_GPS1_GLTCH` is added straight to latitude in degrees. `wind_for_repeat(n, speed, turbulence)` gives the wind parameters, with the direction taken from repeat n. **The SITL RNG has a fixed seed** (`get_random16` in AP_Math), so repeats differ only by wind direction. Flights are still not exactly repeatable: SITL is not lockstepped to the Python client, so the fault lands at a slightly different simulated time under different host load (2 of 78 verdicts differed between 10x and 40x).
- **`dtt/analyze.py`**: scores using the `.BIN` log only.
  - Fault time is the first `PARM` message that matches the fault parameters, with a relative tolerance.
  - Horizontal drift is `SIM` truth against the latest `POS` estimate. A `POS` sample younger than 0.3 s counts as fresh. After the fault, an older sample means the estimate is lost.
  - Vertical error is truth height against estimated height, with the datum offset taken from the first estimate. The 10 m / 50 m rules use `max(horizontal, vertical)`.
  - The reaction is timed from the **hazard** (`hazard_t`: position error first over `PASS_DRIFT_M` after the fault), not from injection; a reaction before the hazard is in time. `failsafe_reaction_s` is still from injection.
  - The reaction (the safety mode switching on) is only a `MODE` change whose `Rsn` is in `FAILSAFE_MODE_REASONS`. `ERR` failsafe or glitch entries are reported as `first_warning` and do not count as a reaction: a GPS glitch warning with no mode change used to be scored as SAFE_FAIL by mistake.
  - Crash means the autopilot's crash `ERR`, a touchdown faster than 3 m/s, or touching the ground while a **current** estimate (less than 1 s old) of the height is above 5 m **and** `landed` is False (it never disarmed by itself; a gentle touchdown followed by disarming is not a crash). The barometer-drift faults do the last one. With GPS loss the estimate stops, so there is no belief to compare against.
  - A fence breach is the **true** position going beyond the radius. `ERR` subsystem 9 (the autopilot's own fence alarm) can fire on a jammed or false position and is reported only as `fence_alarm`.
  - The numeric code sets come from the Copter-4.7.3 headers `ModeReason.h` and `AP_Logger.h`; check them again if the ArduPilot tag changes. The verdict is decided by an ordered `if/elif` chain, so the order of the branches matters: a fence breach or crash is checked before the incomplete-log `ERROR`, so it is not hidden by a cut-short log.

- **RflyMAD tools** (`tools/rflymad_*.py`, results in `validation/`): they need `pyulog` and `openpyxl` (pip, venv). Each case folder holds a `TestInfo_*.xlsx` (fault ID, `[mode, params...]`, injection time relative to the script) and `log_*/*.ulg`. The injection time is taken from the ULog `rfly_ctrl_lxl` topic (`id` in 123450–123549 while the fault is active), not from TestInfo. Mode 3 = noise (mean, sd per axis), 4 = scale. A few folder labels disagree with fault IDs (6 GPS-folder cases carry the magnetometer ID 123455). Mean shifts are dominated by the drone's own motion; use high-passed noise and jumps (`rflymad_magnitudes.py`) as the fault size. The write-up is `validation/RFLYMAD_VALIDATION.md`.
- **`dtt/report.py`** (+ `make_report.py`): builds the ReportLab PDF from a batch's `summary.csv` and `envelope.json`, with matplotlib verdict grids in `report_figures/`. `cause()` maps analyser reason strings to short phrases with regexes, so update it when you change the reason wording in `analyze.py`. Worst-case limits use only flyable groups (baseline all OK). `sensor_summary()` flags **isolated** failures, where a milder level fails but a harsher level passes everywhere. Reaction medians ignore safety modes later than `REACTION_WINDOW_S` (60 s). Level labels come from `labels:` in `faults.yaml`. Values that contain commas must be quoted, because the labels are YAML flow mappings.

## Gotchas

- **Logs cut short at high speedup.** ArduPilot writes its DataFlash log from a buffer. If SITL is killed right after disarm, the last tens of simulated seconds are lost (11 of 780 flights at 120x before the fix). `run_one` force-disarms if needed and calls `Sitl.wait_log_flushed()`, which waits until the log file stops growing, before `stop()`. `analyze.score` gives `ERROR` when a log ends more than 2 m above home. `run_batch.run_job` re-flies an `ERROR` flight once. In `run_batch.envelope` a level with an `ERROR` or `NOT_TESTED` flight is not safe: the limit stops there as `not_verified_level` (shown as `?`), or as `first_unsafe_level` if a flight there was `UNSAFE`. `tools/check_logs.py` lists flights whose log has no touchdown.

- **Telemetry limits speed.** MAVLink stream rates are per *simulated* second. With every stream at 10 Hz, the Python client received about 6,000 msg/s at high `--speedup`, and SITL slowed to about 21x to wait for it, so 40x, 80x and 120x all took about 17 s per flight. `Vehicle.__init__` therefore turns all streams off and requests only EXTENDED_STATUS, POSITION and SIM_STATE at `TELEMETRY_HZ` (2). That gives about 4.5 s per flight, with missions running at about 88x. Scoring reads the onboard `.BIN` log, which telemetry rates don't affect. `tools/profile_flight.py [speedup] [instance]` times each phase of one flight.

- The timestamps in `statustext` and `fault_injected_sim_s` are simulator boot time. The `analyze.py` timestamps are log `TimeUS`. Both are simulator time, but they are not guaranteed to line up exactly.
- `result.json` files from before a change to `analyze.py` keep their old fields until you run `tools/rescore.py` on them.
