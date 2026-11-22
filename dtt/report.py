"""Builds the PDF test report for one batch, from its summary.csv and envelope.json.

The report says, for each sensor, up to which fault level the drone stays safe and what goes wrong
beyond it, in every condition and wind level that was tested.
"""
import collections
import csv
import datetime
import json
import os
import re
import statistics

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.colors import ListedColormap  # noqa: E402
from reportlab.lib import colors  # noqa: E402
from reportlab.lib.enums import TA_LEFT  # noqa: E402
from reportlab.lib.pagesizes import A4  # noqa: E402
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet  # noqa: E402
from reportlab.lib.units import mm  # noqa: E402
from reportlab.platypus import (Image, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate,  # noqa: E402
                                Spacer, Table, TableStyle)

from . import analyze, conditions, faults  # noqa: E402

OK = {"PASS", "SAFE_FAIL"}
GREEN, LIGHT_GREEN, AMBER, RED, GREY = "#2e7d32", "#9ccc65", "#ffb300", "#d32f2f", "#bdbdbd"
REACTION_WINDOW_S = 60.0


def vehicle_text(env):
    """(drone, flight software) lines from the batch's recorded vehicle; older batches have none."""
    v = env.get("vehicle") or {}
    px4 = v.get("autopilot") == "px4"
    drone = "%s '%s' frame model, " % ("PX4 SIH simulator" if px4 else "SITL", "sihsim_quadx" if px4 and v.get("model") == "quad" else v.get("model", "quad"))
    if v.get("params_file"):
        drone += "parameter file %s (sha256 %s)" % (v["params_file"], v["params_sha256"][:12])
    else:
        drone += "%s default parameters (a generic quadcopter, not a specific product)" % ("PX4" if px4 else "ArduPilot")
    # Batches from before PX4 support recorded the version under "ardupilot".
    firmware = "%s %s, software-in-the-loop simulator (SITL)" % (
        "PX4" if px4 else "ArduPilot", v.get("firmware") or v.get("ardupilot") or "Copter-4.7.3")
    if v.get("tool_commit"):
        firmware += "; test tool %s" % v["tool_commit"]
    return drone, firmware


# ---- data ------------------------------------------------------------------------------------
def load(batch):
    with open(os.path.join(batch, "summary.csv")) as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        r["level"], r["repeat"] = int(r["level"]), int(r["repeat"])
    with open(os.path.join(batch, "envelope.json")) as f:
        env = json.load(f)
    return rows, env


def num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def cause(reason):
    """Short, plain-language failure cause from an analyser reason string."""
    r = reason or ""
    rules = [
        (r"believing it was", "flew into the ground (wrong height estimate)"),
        (r"hit the ground at", "lost control and crashed"),
        (r"crash detected", "crashed"),
        (r"geofence breached", "left the geofence"),
        (r"failsafe too slow", "safety mode too late (over 5 s after the error passed 10 m)"),
        (r"(position error|drift) [\d.]+ m.*no (safety mode|failsafe)", "followed a false position, no safety mode"),
        (r"never switched its motors off", "safety mode on, came down but motors kept running"),
        (r"failsafe engaged but", "safety mode on but did not land"),
        (r"did not land", "did not land"),
        (r"never switched on", "fault not reached"),
        (r"mission not completed", "mission not completed"),
    ]
    for pat, text in rules:
        if re.search(pat, r):
            return text
    return r[:60] or "unknown"


def failure_bound(n):
    """With 0 failures in n flights, the failure rate is below this at 95% confidence."""
    return 1 - 0.05 ** (1.0 / n)


def flyable_groups(env):
    return [k for k, g in env["groups"].items() if all(v in OK for v in g["baseline"])]


def group_label(g):
    speed = g.get("wind_speed_ms")
    wind = g["wind"] if speed is None else "%s %.1f m/s" % (g["wind"], speed)
    return "%s / %s" % (g["condition"].capitalize(), wind)


# ---- charts ---------------------------------------------------------------------------------
def verdict_grid_png(rows, env, sensor, path):
    """Rows = condition/wind groups, columns = levels; colour = how the repeats ended."""
    keys = list(env["groups"])
    levels = list(faults.LEVELS)
    codes, texts = [], []
    for k in keys:
        c, w = k.split("/")
        crow, trow = [], []
        for lv in levels:
            vs = [r["verdict"] for r in rows if r["condition"] == c and r["wind"] == w
                  and r["fault"] == sensor and r["level"] == lv]
            n_ok = sum(v in OK for v in vs)
            if not vs or all(v in ("NOT_TESTED", "ERROR") for v in vs):
                crow.append(0); trow.append("n/t")
            elif n_ok == len(vs):
                crow.append(4 if all(v == "PASS" for v in vs) else 3); trow.append("%d/%d" % (n_ok, len(vs)))
            elif n_ok > 0:
                crow.append(2); trow.append("%d/%d" % (n_ok, len(vs)))
            else:
                crow.append(1); trow.append("0/%d" % len(vs))
        codes.append(crow)
        texts.append(trow)
    cmap = ListedColormap([GREY, RED, AMBER, LIGHT_GREEN, GREEN])
    fig, ax = plt.subplots(figsize=(7.2, 0.32 * len(keys) + 1.1), dpi=160)
    ax.imshow(codes, cmap=cmap, vmin=0, vmax=4, aspect="auto")
    for i, trow in enumerate(texts):
        for j, t in enumerate(trow):
            ax.text(j, i, t, ha="center", va="center", fontsize=7,
                    color="white" if codes[i][j] in (1, 4) else "black")
    ax.set_xticks(range(len(levels)))
    ax.set_xticklabels(["L%d\n%s" % (lv, _wrap(faults.label(sensor, lv), 16)) for lv in levels], fontsize=6.5)
    ax.set_yticks(range(len(keys)))
    ax.set_yticklabels([group_label(env["groups"][k]) for k in keys], fontsize=7)
    ax.tick_params(length=0)
    for s in ax.spines.values():
        s.set_visible(False)
    ax.set_xticks([x - 0.5 for x in range(1, len(levels))], minor=True)
    ax.set_yticks([y - 0.5 for y in range(1, len(keys))], minor=True)
    ax.grid(which="minor", color="white", linewidth=1.5)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def _wrap(text, width):
    words, lines, line = text.split(), [], ""
    for w in words:
        if len(line) + len(w) + 1 > width and line:
            lines.append(line)
            line = w
        else:
            line = (line + " " + w).strip()
    lines.append(line)
    return "\n".join(lines[:3])


# ---- report text -------------------------------------------------------------------------------
def sensor_summary(rows, env, sensor):
    """Worst-case safe level over all flyable conditions, first unsafe level, main failure cause."""
    flyable = flyable_groups(env)
    limits = [env["groups"][k]["sensors"][sensor]["safe_up_to_level"] for k in flyable]
    limits = [x for x in limits if x is not None]
    worst = min(limits) if limits else None
    best = max(limits) if limits else None
    first_bad = None if worst is None or worst >= max(faults.LEVELS) else worst + 1
    causes = collections.Counter()
    if first_bad:
        for k in flyable:
            c, w = k.split("/")
            for r in rows:
                if (r["condition"], r["wind"], r["fault"], r["level"]) == (c, w, sensor, first_bad) \
                        and r["verdict"] == "UNSAFE":
                    causes[cause(r["reason"])] += 1
    # Isolated failures: a milder level fails somewhere but a harsher level is safe everywhere.
    # Such a limit rests on a few flights and should be investigated before it is relied on.
    # It only applies when few flights failed: GPS L2 (a 20 m jump) failing in every flight while
    # L5 (receiver dead) is handled is two different faults, not an isolated failure.
    isolated = False
    n_bad = sum(causes.values())
    n_first_bad = sum(1 for r in rows if r["fault"] == sensor and r["level"] == first_bad
                      and "%s/%s" % (r["condition"], r["wind"]) in set(flyable))
    if first_bad and 4 * n_bad <= n_first_bad:
        for lv in faults.LEVELS:
            if lv <= first_bad:
                continue
            vs = [r["verdict"] for r in rows if r["fault"] == sensor and r["level"] == lv
                  and "%s/%s" % (r["condition"], r["wind"]) in set(flyable) and r["verdict"] != "NOT_TESTED"]
            if vs and all(v in OK for v in vs):
                isolated = True
                break
    n_safe = sum(1 for r in rows if r["fault"] == sensor and r["level"] == worst
                 and "%s/%s" % (r["condition"], r["wind"]) in set(flyable))
    return dict(worst=worst, best=best, first_bad=first_bad, n_bad=n_bad, isolated=isolated, n_safe=n_safe,
                cause=causes.most_common(1)[0][0] if causes else None)


def level_outcomes(rows, env, sensor):
    """Per level, over flyable groups: verdict counts, main failure cause, reaction and drift."""
    flyable = set(flyable_groups(env))
    out = []
    for lv in faults.LEVELS:
        rs = [r for r in rows if r["fault"] == sensor and r["level"] == lv
              and "%s/%s" % (r["condition"], r["wind"]) in flyable and r["verdict"] != "NOT_TESTED"]
        cnt = collections.Counter(r["verdict"] for r in rs)
        causes = collections.Counter(cause(r["reason"]) for r in rs if r["verdict"] not in OK)
        # A safety mode long after the fault (e.g. a fence return minutes later) is not a reaction to it.
        react = [num(r["failsafe_reaction_s"]) for r in rs
                 if num(r["failsafe_reaction_s"]) is not None and num(r["failsafe_reaction_s"]) <= REACTION_WINDOW_S]
        drift = [num(r["max_drift_m"]) for r in rs if num(r["max_drift_m"]) is not None]
        out.append(dict(level=lv, n=len(rs), passed=cnt["PASS"], safe=cnt["SAFE_FAIL"], unsafe=cnt["UNSAFE"],
                        cause=causes.most_common(1)[0][0] if causes else "-",
                        react=("%.1f s" % statistics.median(react)) if react else "-",
                        drift=("%.0f m" % statistics.median(drift)) if drift else "-"))
    return out


def build(batch, out_path=None):
    rows, env = load(batch)
    faults.use((env.get("vehicle") or {}).get("autopilot") or "ardupilot")   # level labels come from that fault file
    DRONE, FIRMWARE = vehicle_text(env)
    out_path = out_path or os.path.join(batch, "report.pdf")
    fig_dir = os.path.join(batch, "report_figures")
    os.makedirs(fig_dir, exist_ok=True)
    sensors = [s for s in faults.SENSORS if any(r["fault"] == s for r in rows)]

    ss = getSampleStyleSheet()
    H1 = ParagraphStyle("H1", parent=ss["Heading1"], fontSize=17, spaceAfter=6)
    H2 = ParagraphStyle("H2", parent=ss["Heading2"], fontSize=13, spaceBefore=8, spaceAfter=4)
    B = ParagraphStyle("B", parent=ss["BodyText"], fontSize=9, leading=12, alignment=TA_LEFT)
    S = ParagraphStyle("S", parent=B, fontSize=7.5, leading=9.5, textColor=colors.HexColor("#555555"))
    cell = ParagraphStyle("cell", parent=B, fontSize=8, leading=10)

    def table(data, widths, header_bg="#263238", zebra=True, extra=None):
        t = Table(data, colWidths=widths, repeatRows=1)
        style = [("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(header_bg)),
                 ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                 ("FONTSIZE", (0, 0), (-1, -1), 8), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                 ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#cfd8dc")),
                 ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]
        if zebra:
            for i in range(1, len(data)):
                if i % 2 == 0:
                    style.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor("#f5f7f8")))
        t.setStyle(TableStyle(style + (extra or [])))
        return t

    P = lambda txt, st=cell: Paragraph(txt, st)  # noqa: E731
    story = []
    n_flights = len(rows)
    flyable = flyable_groups(env)
    unflyable = [k for k in env["groups"] if k not in flyable]
    today = datetime.date.today().isoformat()

    # ---- page 1: summary -------------------------------------------------------------------
    story += [Paragraph("Sensor fault tolerance report", H1),
              Paragraph("<b>Drone:</b> %s<br/><b>Flight software:</b> %s<br/><b>Report date:</b> %s"
                        " &nbsp; <b>Test batch:</b> %s<br/><b>Flights:</b> %d simulated patrol missions"
                        " (%.1f minutes of computer time)" % (DRONE, FIRMWARE, today, os.path.basename(batch.rstrip("/")),
                                                              n_flights, env.get("wall_minutes") or 0), B),
              Spacer(1, 4 * mm),
              Paragraph("Results at a glance", H2),
              Paragraph("Each sensor was broken on purpose, one at a time, at five levels from mild to severe, "
                        "in %d combinations of place, temperature and wind. <b>Safe up to</b> is the most severe "
                        "level at which the drone either finished its mission correctly or switched to a safety "
                        "mode in time and landed &mdash; in <i>every</i> repeat and <i>every</i> flyable "
                        "condition (worst case). The best case over conditions is shown in brackets. "
                        "The small print gives how many flights that level rests on and, with none of them "
                        "failing, the highest failure rate still consistent with that at 95%% confidence." % len(env["groups"]), B),
              Spacer(1, 2 * mm)]
    data = [["Sensor", "Safe up to (worst case)", "Fails at", "What goes wrong first"]]
    tints = []
    for i, s in enumerate(sensors, 1):
        sm = sensor_summary(rows, env, s)
        if sm["worst"] is None:
            safe_txt, fail_txt = "not tested", "-"
        elif sm["worst"] == 0:
            safe_txt, fail_txt = "none of the tested levels", "L1: " + faults.label(s, 1)
        else:
            safe_txt = "L%d: %s" % (sm["worst"], faults.label(s, sm["worst"]))
            fail_txt = "L%d: %s" % (sm["first_bad"], faults.label(s, sm["first_bad"])) if sm["first_bad"] else "not reached (all levels safe)"
        if sm["first_bad"] and not sm["n_bad"]:
            fail_txt = "L%d not verified: its flights could not be judged" % sm["first_bad"]
        if sm["best"] is not None and sm["best"] != sm["worst"]:
            safe_txt += " (best: L%d)" % sm["best"]
        if sm["worst"] and sm["n_safe"]:
            safe_txt += "<br/><font size=7 color='#555555'>%d of %d flights safe: failure rate under %.0f%%</font>" % (
                sm["n_safe"], sm["n_safe"], 100 * failure_bound(sm["n_safe"]))
        what = sm["cause"] or "-"
        if sm["isolated"]:
            what += " <i>(isolated: %d flight%s; harsher levels passed - investigate)</i>" % (
                sm["n_bad"], "" if sm["n_bad"] == 1 else "s")
        data.append([P("<b>%s</b>" % faults.name(s)), P(safe_txt), P(fail_txt), P(what)])
        colour = GREEN if sm["worst"] == max(faults.LEVELS) else (RED if not sm["worst"] else AMBER)
        tints.append(("LINEBEFORE", (0, i), (0, i), 4, colors.HexColor(colour)))
    story.append(table(data, [30 * mm, 50 * mm, 45 * mm, 50 * mm], extra=tints))
    story.append(Spacer(1, 3 * mm))
    if unflyable:
        story.append(Paragraph(
            "<b>Wind limit.</b> Even with no sensor fault, the drone could not fly the mission in: %s. "
            "It could not make headway upwind and was blown outside the 600 m geofence. Sensor limits are "
            "not given for these conditions." % ", ".join(group_label(env["groups"][k]) for k in unflyable), B))
    story += [Spacer(1, 3 * mm), Paragraph("How each flight is judged", H2), table([
        ["Verdict", "Rule"],
        [P("<b>PASS</b>"), P("Mission completed, landed within 10 m of home, position error under 10 m.")],
        [P("<b>SAFE FAIL</b>"), P("The autopilot switched to a safety mode no later than 5 s after its position "
                                  "error passed 10 m (or before it got that large) and landed, without leaving "
                                  "the geofence or crashing.")],
        [P("<b>UNSAFE</b>"), P("Left the geofence, crashed (including hitting the ground while believing it was "
                               "over 5 m up without then landing by itself), a safety mode more than 5 s after "
                               "the position error passed 10 m, or anything else.")],
        [P("<b>NOT TESTED</b>"), P("The drone never reached the point where the fault is switched on.")],
        [P("<b>ERROR</b>"), P("The flight log is incomplete, so the flight could not be judged. A level with such "
                              "a flight is not counted as safe.")],
    ], [30 * mm, 145 * mm]),
        Spacer(1, 2 * mm),
        Paragraph("Position error is the larger of the horizontal and vertical difference between where the drone "
                  "really was (simulator truth) and where it believed it was. Faults hit every unit of a sensor "
                  "(both IMUs, all compasses, both barometers), so the autopilot cannot switch to a healthy spare.", S),
        PageBreak()]

    # ---- page 2: safe-limit matrix ------------------------------------------------------------
    story += [Paragraph("Safe limit by condition and wind", H2),
              Paragraph("Highest fault level at which every repeat passed or failed safely. "
                        "L5 = all tested levels safe; L0 = unsafe even at the mildest level; "
                        "n/a = the drone fails without any fault in that condition; "
                        "? = the next level could not be judged, so the limit may be higher.", B), Spacer(1, 2 * mm)]
    hdr = ParagraphStyle("hdr", parent=cell, fontSize=7, leading=8.5, textColor=colors.white)
    data = [["Condition / wind", "Baseline"] + [Paragraph(faults.name(s).split(" (")[0], hdr) for s in sensors]]
    extra = []
    for i, (k, g) in enumerate(env["groups"].items(), 1):
        row = [P(group_label(g)), "/".join(v[:1] for v in g["baseline"])]
        for j, s in enumerate(sensors, 2):
            lim = g["sensors"][s]["safe_up_to_level"]
            row.append("n/a" if lim is None else "L%d%s" % (lim, "?" if g["sensors"][s].get("not_verified_level") else ""))
            col = GREY if lim is None else GREEN if lim == max(faults.LEVELS) else RED if lim == 0 else AMBER
            extra.append(("BACKGROUND", (j, i), (j, i), colors.HexColor(col)))
            if col in (GREEN, RED):
                extra.append(("TEXTCOLOR", (j, i), (j, i), colors.white))
        data.append(row)
    extra.append(("ALIGN", (1, 0), (-1, -1), "CENTER"))
    # Fit the sensor columns into the page width (176 mm usable), however many fault families.
    col_w = min(22.0, (176.0 - 48.0 - 16.0) / max(1, len(sensors))) * mm
    story.append(table(data, [48 * mm, 16 * mm] + [col_w] * len(sensors), zebra=False, extra=extra))
    story += [Spacer(1, 4 * mm), Paragraph("Test conditions", H2)]
    data = [["Condition", "Place", "Temperature", "Density altitude", "Air density", "Winds at 50 m (m/s)"]]
    for c in sorted({g["condition"] for g in env["groups"].values()}, key=conditions.CONDITIONS.index):
        d = conditions.describe(c)
        winds = ", ".join("%s %.1f" % (w, conditions.wind(c, w)[0]) for w in conditions.WINDS)
        data.append([c.capitalize(), P(d["site_name"]), "%.1f °C (%s)" % (d["temperature_c"], d["temperature_case"]),
                     "%d m" % d["density_altitude_m"], "%.0f%%" % (100 * d["air_density_ratio"]), P(winds)])
    story.append(table(data, [20 * mm, 30 * mm, 26 * mm, 30 * mm, 18 * mm, 51 * mm]))
    story.append(Paragraph(
        "Weather: NASA POWER hourly data 2020&ndash;2024 (hot = 99th percentile temperature; winds = 50th, 95th "
        "and 99.9th percentile at 50 m, with turbulence at 30&ndash;40% of the mean). The simulator's air thins "
        "with altitude but ignores temperature, so each condition is flown from its density altitude: the height "
        "in the standard atmosphere with the same air density. Leh temperatures are corrected from the NASA grid "
        "cell's mean height (about 4,530 m) to the town (3,500 m).", S))
    story.append(PageBreak())

    # ---- one section per sensor ----------------------------------------------------------------
    for s in sensors:
        png = os.path.join(fig_dir, "%s_grid.png" % s)
        verdict_grid_png(rows, env, s, png)
        sm = sensor_summary(rows, env, s)
        head = [Paragraph(faults.name(s), H2),
                Paragraph("<b>Fault:</b> %s." % faults._CONFIG[s]["description"], B)]
        if sm["worst"] is not None:
            if sm["first_bad"] and not sm["n_bad"]:
                head.append(Paragraph("<b>Safe up to L%d</b> in every flyable condition. L%d (%s) is not verified: "
                                      "its flights could not be judged." % (
                                          sm["worst"], sm["first_bad"], faults.label(s, sm["first_bad"])), B))
            elif sm["first_bad"]:
                head.append(Paragraph("<b>Safe up to L%d</b> in every flyable condition; first failures at L%d (%s): "
                                      "mostly <i>%s</i>." % (sm["worst"], sm["first_bad"], faults.label(s, sm["first_bad"]),
                                                             sm["cause"] or "-"), B))
                if sm["isolated"]:
                    head.append(Paragraph(
                        "<b>Note:</b> the L%d failures are isolated (%d flight%s), and harsher levels passed in every "
                        "flyable condition. This limit rests on very few flights and should be investigated "
                        "before it is relied on." % (sm["first_bad"], sm["n_bad"], "" if sm["n_bad"] == 1 else "s"), B))
            else:
                head.append(Paragraph("<b>Safe at every tested level</b> in every flyable condition. The levels "
                                      "tested did not find this sensor's breaking point.", B))
        img = Image(png, width=175 * mm, height=175 * mm * (0.32 * len(env["groups"]) + 1.1) / 7.2)
        legend = Paragraph("Cell = repeats that ended PASS or SAFE FAIL out of repeats flown. Dark green: all PASS; "
                           "light green: all safe, some via safety mode; amber: mixed; red: none safe; "
                           "grey: not tested, or no flight could be judged.", S)
        data = [["Level", "Fault", "Flights", "Pass", "Safe fail", "Unsafe", "Main failure", "Reaction", "Error"]]
        for o in level_outcomes(rows, env, s):
            data.append(["L%d" % o["level"], P(faults.label(s, o["level"])), o["n"], o["passed"], o["safe"],
                         o["unsafe"], P(o["cause"]), o["react"], o["drift"]])
        lvl_table = table(data, [10 * mm, 38 * mm, 13 * mm, 10 * mm, 13 * mm, 13 * mm, 40 * mm, 18 * mm, 17 * mm],
                          extra=[("ALIGN", (2, 1), (5, -1), "CENTER")])
        story += head + [Spacer(1, 2 * mm), img, legend, Spacer(1, 3 * mm), lvl_table,
                         Paragraph("Counts cover flyable conditions only. Reaction = median seconds from the fault to "
                                   "the safety mode, over flights where one switched on within %d s. Error = median of "
                                   "each flight's largest gap between where the drone was and where it believed it was "
                                   "(under GPS jamming the belief can jump kilometres while the drone stays close)." %
                                   REACTION_WINDOW_S, S),
                         PageBreak()]

    # ---- method and limitations ------------------------------------------------------------------
    story += [Paragraph("Method", H2), Paragraph(
        "Each flight takes off to 50 m, flies a 375 m square patrol loop (1.5 km) around home and returns to "
        "launch, inside a 600 m circular geofence with a 120 m ceiling. The fault switches on as the drone leaves "
        "the second corner, about 265 m from home, and stays on until the end. Every test is repeated with the "
        "wind from 0°, 120° and 240° (calm: once). Verdicts come from the drone's onboard flight log compared "
        "with the simulator's true position.", B),
        Paragraph("Limitations", H2)]
    limits = [
        "Simulation only. A specific drone's weight, motors, battery and parameters change the results. "
        "Its parameter file can be supplied (--params) and is named on page 1 when it was; the airframe "
        "physics stay those of the simulator's frame model.",
        "GPS spoofing and jamming are modelled at the receiver's output (a false position, velocity or no "
        "fix), not as radio signals. A spoofing drag runs until the flight ends, so a faster drone is "
        "dragged for less time.",
        "Wind data are hourly averages (NASA POWER reanalysis), so real gusts are stronger than modelled.",
        "Temperature is represented only through air density. Cold-battery capacity loss and sensor temperature "
        "drift are not modelled.",
        "The simulator's random generator has a fixed seed; repeats differ by wind direction only. GPS jamming "
        "uses random data, so its results vary between runs and need more repeats for a reliable rate.",
        "Where every level passed (for example accelerometer and compass in normal wind), the tested levels were "
        "too mild to find the breaking point.",
        "A single unsafe repeat sets a lower limit for the whole group (worst case); check the per-sensor "
        "grids before acting on an isolated failure.",
    ]
    for t in limits:
        story.append(Paragraph("&bull; " + t, B))

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(colors.HexColor("#777777"))
        canvas.drawString(18 * mm, 10 * mm, "Sensor fault tolerance report - %s - simulated tests" % DRONE)
        canvas.drawRightString(A4[0] - 18 * mm, 10 * mm, "page %d" % doc.page)
        canvas.restoreState()

    doc = SimpleDocTemplate(out_path, pagesize=A4, leftMargin=17 * mm, rightMargin=17 * mm,
                            topMargin=15 * mm, bottomMargin=17 * mm,
                            title="Sensor fault tolerance report", author="drone test tool")
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return out_path
