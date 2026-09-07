#!/usr/bin/env python3
"""Step 3: report.json -> a self-contained HTML page.

Standalone by design: stdlib only, no imports from this package, no network.

Colour: see ramp() — two palettes, --palette status (each stage the colour of
the job it is doing) and --palette mono (one blue ordinal ramp).
"""

from __future__ import annotations

import argparse
import html
import json
import math
import sys

# The palette is muted on purpose: the page it sits on is warm neutral paper,
# and a saturated ramp fought it. Everything here is low-chroma — the blues run
# OKLCH C 0.05-0.07 and the green sits at 0.10, against 0.10-0.16 and 0.21 for
# the same roles in a stock chart palette. Separation is bought with lightness
# instead, which is why the steps are spread as wide as each surface allows
# rather than clustered. Values are OKLCH-generated, so keep them in that space
# if you retune: nudging a hex by eye will quietly break the step spacing.
RAMP_L = [
    "#9eb7d4",
    "#8daaca",
    "#7d9cc0",
    "#6d8fb5",
    "#6082a9",
    "#53759c",
    "#48698d",
    "#3f5c7d",
    "#36506d",
    "#2e445c",
]
# Not the light ramp reused: the dark end has to stay off the dark surface, so
# the whole run is lifted and the pale end stops short of reading as white text.
RAMP_D = [
    "#a1bad7",
    "#91aecf",
    "#82a2c6",
    "#7496bd",
    "#688bb2",
    "#5c7fa6",
    "#537398",
    "#4a6889",
    "#435d7a",
    "#3c526b",
]
# Warm greys for the stages nothing has moved out of yet: the parked column,
# plus any status prepended to the scale ahead of it. Warm rather than dead
# neutral so they belong to the same page as the paper and the body ink, and so
# they separate from the cool marks by hue as well as by lightness.
#
# The anchor is deliberately faint — 2.2:1 on the light surface, the quietest
# mark on the page, because "nothing has happened here" should not shout. That
# leaves nowhere fainter to go, so the rarer stages prepended ahead of it step
# the other way, toward more contrast, rather than fading into the paper. Beyond
# three the last step repeats.
NEUTRAL_L = ["#b2aba2", "#938b7f", "#746a5d"]
NEUTRAL_D = ["#70685c", "#90887c", "#b1aa9f"]

# Hues for the in-flight stages under the "status" palette, in fixed order:
# blue, amber, red, violet. On the usual board that is In Progress / In Review /
# Testing, which is where the order comes from — amber for "waiting on someone",
# red for "being broken on purpose".
#
# Four is the cap, not an arbitrary stopping point. Muting costs chroma, chroma
# is most of the distance between two hues, and a fifth and sixth muted hue
# cannot be added without some pair dropping below the point where full-colour
# readers can separate them (teal against the green, rose against the violet,
# measured both ways). A board with more in-flight stages than this falls back
# to the ordinal ramp for that group; grey and green keep their roles.
FLIGHT_L = ["#4579b2", "#be9f50", "#91362f", "#9f7bba"]
FLIGHT_D = ["#5c91cc", "#d7b768", "#af4d45", "#b28dcd"]

# Closed. A muted green, split by mode: it has to sit far enough from the red
# next to it in lightness that red-green colour blindness still separates them,
# and the red is not at the same lightness in both modes.
DONE_L, DONE_D = "#579766", "#6fb07d"

# "status" gives each stage the colour of the job it is doing; "mono" is the
# single-hue ordinal ramp this started as, where colour carries the order and
# nothing else.
PALETTES = ("status", "mono")

STRINGS = {
    "en": {
        "title": "{project} board flow",
        "heading": "Where the work stands",
        "sub": (
            "{total} issues moved into {track} inside this window — or are still "
            "sitting in “{parked}”. Below: the stage each one is at "
            "<b>now</b>, broken down by label."
        ),
        "kpi_closed": "closed ({done})",
        "kpi_total": "issues in scope",
        "kpi_mid": "in intermediate stages",
        "kpi_parked": "parked in {parked}",
        "by_label": "By label",
        "by_label_desc": (
            "The closed share is in the middle of each ring. Segments run in "
            "stage order; each colour names a stage rather than ranking it."
        ),
        "by_label_desc_mono": (
            "The closed share is in the middle of each ring. The ring reads "
            "in stage order: the further along the scale, the further along "
            "the flow."
        ),
        "compare": "Label comparison",
        "compare_desc": (
            "Rings compare poorly against each other — the same data on one scale, 100% per row."
        ),
        "all_issues": "All {total} issues",
        "all_desc": "Sorted by stage, unclosed first.",
        "th": ["Issue", "Summary", "Label", "Stage now", "Assignee", "Note"],
        "parked_since": "parked in “{parked}” since {since}",
        "closed": "closed",
        "issues_short": "issues",
        "how": "How this was built",
        "rules": "Selection rules",
        "rule_1": (
            "An issue is in scope if it <b>transitioned</b> into {track} between "
            "{d0} and {d1}, per the changelog."
        ),
        "rule_2": (
            "Plus issues <b>still</b> in “{parked}”. Entry cutoff: "
            "<code>{cutoff}</code> — issues that landed there later are excluded."
        ),
        "rule_restrict": "For label <b>{label}</b>, only <code>{users}</code> are counted.",
        "rule_now": (
            "The stage on the charts is each issue's <b>current</b> status, not "
            "the status it moved into during the window."
        ),
        "parked_head": "Parked in “{parked}”",
        "parked_none": "None.",
        "excluded_head": "Dropped by --restrict ({n})",
        "kept_in": "(still counted in {cats})",
        "dropped": "(dropped entirely)",
        "caveats": "Caveats",
        "cav_multi": (
            "An issue with several labels is counted in each of them, so the "
            "per-label total ({sum}) can differ from the unique issue count "
            "({total})."
        ),
        "cav_alias": (
            "The changelog and the REST fields can spell the same status "
            "differently; the mapping was discovered from the data, not "
            "hardcoded."
        ),
        "cav_live": "A snapshot is a moment in time; the board moves on.",
        "cav_extra": "Statuses outside the configured scale, prepended to it: <code>{extra}</code>.",
        "cav_jql": "Query: <code>{jql}</code>",
        "small_n": "Small sample — a percentage on this few issues is not meaningful.",
        "only": "Only counted: {users}.",
        "no_issues": "No issues match the selection.",
        "unassigned": "unassigned",
    },
    "ru": {
        "title": "Поток доски {project}",
        "heading": "Где стоят задачи",
        "sub": (
            "{total} задач сменили "
            "статус на {track} в этом "
            "окне — либо так и "
            "остались висеть в "
            "«{parked}». Ниже: на каком "
            "этапе каждая из них "
            "находится <b>сейчас</b>, "
            "в разрезе тегов."
        ),
        "kpi_closed": "закрыто ({done})",
        "kpi_total": "задач в выборке",
        "kpi_mid": "в промежуточных этапах",
        "kpi_parked": "висят в {parked}",
        "by_label": "По тегам",
        "by_label_desc": (
            "Доля закрытого — "
            "в центре каждой "
            "диаграммы. Сегменты "
            "идут по порядку "
            "этапов; цвет называет "
            "этап, а не ранжирует "
            "его."
        ),
        "by_label_desc_mono": (
            "Доля закрытого — "
            "в центре каждой "
            "диаграммы. Кольцо "
            "читается по порядку "
            "этапов: чем дальше "
            "сегмент по шкале, "
            "тем дальше задача "
            "по потоку."
        ),
        "compare": "Сравнение тегов",
        "compare_desc": (
            "Кольца плохо "
            "сравниваются между "
            "собой — здесь те же "
            "данные в один "
            "масштаб, 100% на каждую "
            "строку."
        ),
        "all_issues": "Все {total} задач",
        "all_desc": ("Отсортировано по этапу — незакрытое сверху."),
        "th": ["Задача", "Название", "Тег", "Этап сейчас", "Исполнитель", "Примечание"],
        "parked_since": "висит в «{parked}» с {since}",
        "closed": "закрыто",
        "issues_short": "задач",
        "how": "Как собрано",
        "rules": "Правила выборки",
        "rule_1": (
            "Задача попала в "
            "выборку, если "
            "<b>переходила</b> в {track} "
            "с {d0} по {d1} (по changelog)."
        ),
        "rule_2": (
            "Плюс задачи, "
            "<b>оставшиеся</b> в «{parked}». "
            "Отсечка попадания "
            "туда: <code>{cutoff}</code> — задачи, "
            "попавшие позже, не "
            "учтены."
        ),
        "rule_restrict": ("Для тега <b>{label}</b> учтены только <code>{users}</code>."),
        "rule_now": (
            "Этап на диаграммах — <b>текущий</b> статус задачи, а не тот, в который она переходила."
        ),
        "parked_head": "Висят в «{parked}»",
        "parked_none": "Нет таких задач.",
        "excluded_head": "Отброшено правилом --restrict ({n})",
        "kept_in": "(учтена в {cats})",
        "dropped": "(исключена полностью)",
        "caveats": "Оговорки",
        "cav_multi": (
            "Задача с несколькими "
            "тегами считается в "
            "каждом своём теге, "
            "поэтому сумма по "
            "тегам ({sum}) может "
            "отличаться от числа "
            "уникальных задач ({total})."
        ),
        "cav_alias": (
            "В changelog и в полях API один и "
            "тот же статус может "
            "называться по-разному; "
            "соответствие "
            "определено из данных, "
            "а не зашито в код."
        ),
        "cav_live": ("Данные — срез на момент выгрузки; доска живёт и цифры смещаются."),
        "cav_extra": ("Статусы вне заданной шкалы, добавлены в её начало: <code>{extra}</code>."),
        "cav_jql": "Запрос: <code>{jql}</code>",
        "small_n": ("Малая выборка — проценты на такой базе не показательны."),
        "only": "Учтены только: {users}.",
        "no_issues": ("Нет задач под критерии выборки."),
        "unassigned": "не назначена",
    },
}


def _pick(steps, k):
    """k steps spread evenly over a ramp, ends included."""
    return [steps[round(i * (len(steps) - 1) / max(k - 1, 1))] for i in range(k)]


def ramp(stages: list[str], parked: str, done: str, palette: str = PALETTES[0]):
    """Stage colours for (light, dark), one per stage.

    Two palettes, because the two readings of a stage scale are both legitimate
    and the choice belongs to whoever is looking at the board.

    **mono** puts every stage on one blue ordinal ramp. Colour carries the order
    and nothing else: further along the ramp is further along the flow, and a
    reader can rank two segments they cannot name. What they cannot do is tell
    them apart quickly — muted single-hue steps land ΔE 12 apart at five stages
    (OKLab x100), and an 11px donut arc is not much surface to judge that on.

    **status** gives each stage the colour of the job it is doing, and gets the
    separation back by spending hue instead of position:

        not started  →  warm grey    nothing is happening in this column
        in flight    →  blue, amber, red, violet, in that fixed order
        closed       →  muted green  the number the whole report is about

    Worst adjacent pair, five stages: ΔE 21.5 light / 17.7 dark, against 12 for
    mono, and it holds up under simulated red-green colour blindness (15.2 /
    14.8) — which is why the green is lighter than the red rather than merely
    a different hue from it. What it gives up is the ranking: amber is not
    "further along" than blue, it is only different, so the order lives in the
    legend and the stage names rather than in the colour.

    Both palettes are low-chroma; see the ramp definitions for why, and for what
    the muting costs. Under either, the pale end of a mode's scale sits near
    2:1 on its surface, which is legal only because every segment is also named
    in the legend and in the table.
    """
    n = len(stages)
    if palette == "mono":
        return _pick(RAMP_L, n), list(reversed(_pick(RAMP_D, n)))

    di = stages.index(done)
    pi = stages.index(parked) if parked in stages else -1
    neutral = [i for i in range(n) if i <= pi and i != di]
    flight = [i for i in range(n) if i not in neutral and i != di]

    def outward(steps, k):
        return list(reversed([steps[min(i, len(steps) - 1)] for i in range(k)]))

    # More in-flight stages than there are hues that stay apart when muted: fall
    # back to the ordinal ramp for that group rather than inventing a fifth hue.
    over = len(flight) > len(FLIGHT_L)
    light, dark = [None] * n, [None] * n
    for slot, c_l, c_d in (
        (neutral, outward(NEUTRAL_L, len(neutral)), outward(NEUTRAL_D, len(neutral))),
        (
            flight,
            _pick(RAMP_L, len(flight)) if over else FLIGHT_L[: len(flight)],
            list(reversed(_pick(RAMP_D, len(flight)))) if over else FLIGHT_D[: len(flight)],
        ),
        ([di], [DONE_L], [DONE_D]),
    ):
        for i, c1, c2 in zip(slot, c_l, c_d, strict=True):
            light[i], dark[i] = c1, c2
    return light, dark


def donut(counts, total, size=196):
    C = 2 * math.pi * 38
    gap, off, parts = 1.3, 0.0, []
    for i, n in enumerate(counts):
        if n:
            seg = C * n / total
            vis = max(seg - gap, 0.8)
            parts.append(
                f'<circle class="seg" cx="50" cy="50" r="38" fill="none" '
                f'stroke="var(--st{i})" stroke-width="11" '
                f'stroke-dasharray="{vis:.2f} {C - vis:.2f}" '
                f'stroke-dashoffset="{-off:.2f}"></circle>'
            )
        off += C * n / total
    return (
        f'<svg viewBox="0 0 100 100" width="{size}" height="{size}" aria-hidden="true" '
        f'style="transform:rotate(-90deg)">' + "".join(parts) + "</svg>"
    )


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="render", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("-i", "--report", default="report.json")
    p.add_argument("-o", "--out", default="flow.html")
    p.add_argument("--lang", default="en", choices=sorted(STRINGS))
    p.add_argument(
        "--palette",
        default=PALETTES[0],
        choices=PALETTES,
        help="stage colours: 'status' gives each stage a hue of its own, "
        "'mono' puts them all on one blue ordinal ramp",
    )
    p.add_argument("--title", default=None, help="page <title>: a short noun phrase")
    p.add_argument("--heading", default=None, help="the h1 on the page")
    return p


def main(argv: list[str] | None = None) -> int:
    a = build_parser().parse_args(argv)
    try:
        with open(a.report, encoding="utf-8") as fh:
            d = json.load(fh)
    except FileNotFoundError:
        sys.exit(f"No report at {a.report}. Run: jira-flow-report aggregate")
    T = STRINGS[a.lang]
    e = html.escape

    M, ST, CATS, DONE = d["meta"], d["meta"]["stages"], d["meta"]["cats"], d["meta"]["done"]
    A, AT = d["all"], d["all"]["total"]
    if not AT:
        sys.exit("The report is empty — nothing matched that window.")
    di = ST.index(DONE)
    L, DK = ramp(ST, M["parked"], DONE, a.palette)
    w0, w1 = M["window"]

    def fmt(iso):
        return ".".join(reversed(iso.split("-")))

    proj = M.get("project") or "Jira"
    quo = (lambda s: f"“{s}”") if a.lang == "en" else (lambda s: f"«{s}»")
    tracklist = ", ".join(quo(e(t)) for t in M["track"])
    title = a.title or T["title"].format(project=proj)
    heading = a.heading or T["heading"]
    srv = M.get("server", "")

    def cards():
        out = []
        for cat in CATS:
            c = d["cats"][cat]
            tot, cnt = c["total"], c["counts"]
            if not tot:
                out.append(
                    f'<article class="card"><header class="ch"><h3>{e(cat)}</h3>'
                    f'<span class="tot">0 {T["issues_short"]}</span></header>'
                    f'<p class="smalln">{T["no_issues"]}</p></article>'
                )
                continue
            legend = "".join(
                f'<li><span class="sw" style="background:var(--st{i})"></span>'
                f'<span class="lb">{e(ST[i])}</span><span class="ct">{n}</span>'
                f'<span class="pc">{n / tot * 100:.0f}%</span></li>'
                for i, n in enumerate(cnt)
                if n
            )
            warn = f'<p class="smalln">{T["small_n"]}</p>' if tot < 5 else ""
            note = (
                f'<p class="smalln">{T["only"].format(users=e(", ".join(M["restrict"][cat])))}</p>'
                if cat in M["restrict"]
                else ""
            )
            out.append(
                f'<article class="card">\n'
                f'  <header class="ch"><h3>{e(cat)}</h3>'
                f'<span class="tot">{tot} {T["issues_short"]}</span></header>\n'
                f'  <div class="dwrap">{donut(cnt, tot)}\n'
                f'    <div class="center"><strong>{cnt[di] / tot * 100:.0f}'
                f'<span class="pctsign">%</span></strong><span>{T["closed"]}</span></div>\n'
                f'  </div>\n  <ul class="legend">{legend}</ul>{warn}{note}\n</article>'
            )
        return "\n".join(out)

    def stacked():
        out = []
        allrow = "__all__"
        for cat in [*CATS, allrow]:
            src = A if cat == allrow else d["cats"][cat]
            tot, cnt = src["total"], src["counts"]
            if not tot:
                continue
            segs = "".join(
                f'<span class="sseg" style="flex:{n};background:var(--st{i})" '
                f'title="{e(ST[i])}: {n} ({n / tot * 100:.0f}%)"></span>'
                for i, n in enumerate(cnt)
                if n
            )
            name = ("all labels" if a.lang == "en" else "все теги") if cat == allrow else cat
            out.append(
                f'<div class="srow{" total" if cat == allrow else ""}">'
                f'<span class="sname">{e(name)}</span>'
                f'<div class="sbar">{segs}</div>'
                f'<span class="sdone">{cnt[di] / tot * 100:.0f}%</span></div>'
            )
        return "\n".join(out)

    def link(key):
        return f'<a href="{srv}/browse/{key}">{key}</a>' if srv else key

    def tbl():
        out = []
        for r in d["table"]:
            i = ST.index(r["status"])
            chips = "".join(f'<span class="chip">{e(c)}</span>' for c in r["shown_cats"])
            note = (
                T["parked_since"].format(parked=e(M["parked"]), since=r["parked_since"])
                if r["reason"] == "parked"
                else ""
            )
            out.append(
                f'<tr><td class="k">{link(r["key"])}</td>'
                f'<td class="sm">{e(r["summary"][:70])}</td><td>{chips}</td>'
                f'<td><span class="dot" style="background:var(--st{i})"></span>{e(r["status"])}</td>'
                f'<td class="as">{e(r["assignee"] or "—")}</td>'
                f'<td class="nt">{note}</td></tr>'
            )
        return "\n".join(out)

    parked = (
        "".join(
            f"<li>{link(s['key'])} — {s['since']}, {e(', '.join(s['cats']))}, "
            f"{e(s['assignee'] or T['unassigned'])} — {e(s['summary'][:60])}</li>"
            for s in d["parked_list"]
        )
        or f"<li>{T['parked_none']}</li>"
    )
    exc = "".join(
        f"<li>{link(x['key'])} — {e(x['assignee'] or T['unassigned'])} <em>"
        + (T["kept_in"].format(cats=e(", ".join(x["kept_in"]))) if x["kept_in"] else T["dropped"])
        + "</em></li>"
        for x in d["excluded"]
    )
    exc_block = (
        f'<div class="note"><h3>{T["excluded_head"].format(n=len(d["excluded"]))}</h3>'
        f"<ul>{exc}</ul></div>"
        if d["excluded"]
        else ""
    )
    rules = "".join(
        f"<li>{T['rule_restrict'].format(label=e(k), users=e(', '.join(v)))}</li>"
        for k, v in M["restrict"].items()
    )
    extra_note = (
        f"<li>{T['cav_extra'].format(extra=e(', '.join(M.get('extra_stages') or [])))}</li>"
        if M.get("extra_stages")
        else ""
    )
    jql_note = f"<li>{T['cav_jql'].format(jql=e(M['jql']))}</li>" if M.get("jql") else ""
    sum_cats = sum(d["cats"][c]["total"] for c in CATS)
    inflight = sum(A["counts"][ST.index(t)] for t in M["track"] if t in ST and t != DONE)
    tl = "".join(f"--st{i}:{c};" for i, c in enumerate(L))
    td = "".join(f"--st{i}:{c};" for i, c in enumerate(DK))
    ring_desc = T["by_label_desc_mono" if a.palette == "mono" else "by_label_desc"]
    keylegend = "".join(
        f'<div><span class="sw" style="background:var(--st{i})"></span>{e(s)}</div>'
        for i, s in enumerate(ST)
    )
    th = "".join(f"<th>{e(x)}</th>" for x in T["th"])
    board = f" · board {M['board']}" if M.get("board") else ""

    # First tag in the file, and it has to be: the page is written as UTF-8 but
    # carries no HTTP header when it is opened off disk, which is the whole point
    # of a self-contained report. Without this the browser falls back to its
    # locale default — windows-1252 on most machines — and every multi-byte
    # character breaks. Not just the Russian: the typographic quotes, the em
    # dashes and the middots in the English page go too, and <title> is parsed
    # before the encoding settles, so the tab name breaks with them.
    HTML = f"""<meta charset="utf-8">
<title>{e(title)}</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500;600&display=swap">
<style>
:root {{
  --plane:#f9f9f7; --surface:#fcfcfb; --ink:#0b0b0b; --ink2:#52514e; --muted:#898781;
  --line:#e1e0d9; --ring:rgba(11,11,11,.10); --accent:#48698d; --chipbg:rgba(72,105,141,.10);
  {tl} color-scheme:light;
}}
@media (prefers-color-scheme:dark) {{
  :root:not([data-theme="light"]) {{
    --plane:#0d0d0d; --surface:#1a1a19; --ink:#fff; --ink2:#c3c2b7; --muted:#898781;
    --line:#2c2c2a; --ring:rgba(255,255,255,.10); --accent:#82a2c6; --chipbg:rgba(130,162,198,.14);
    {td} color-scheme:dark;
  }}
}}
:root[data-theme="dark"] {{
  --plane:#0d0d0d; --surface:#1a1a19; --ink:#fff; --ink2:#c3c2b7; --muted:#898781;
  --line:#2c2c2a; --ring:rgba(255,255,255,.10); --accent:#82a2c6; --chipbg:rgba(130,162,198,.14);
  {td} color-scheme:dark;
}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--plane);color:var(--ink);
  font:400 15px/1.55 "IBM Plex Sans",system-ui,-apple-system,sans-serif;-webkit-font-smoothing:antialiased}}
.wrap{{max-width:1120px;margin:0 auto;padding:44px 24px 80px;display:flex;flex-direction:column;gap:40px}}
.eyebrow{{font:500 11px/1 "IBM Plex Mono",ui-monospace,monospace;letter-spacing:.13em;
  text-transform:uppercase;color:var(--muted)}}
h1{{font:600 clamp(27px,4vw,38px)/1.15 "IBM Plex Sans",sans-serif;margin:10px 0 0;
  letter-spacing:-.02em;text-wrap:balance}}
.sub{{color:var(--ink2);margin:12px 0 0;max-width:62ch}}
h2{{font:600 19px/1.3 "IBM Plex Sans",sans-serif;margin:0;letter-spacing:-.01em}}
.sechead{{display:flex;flex-direction:column;gap:6px;margin-bottom:20px}}
.sechead p{{margin:0;color:var(--ink2);font-size:14px;max-width:64ch}}
.kpis{{display:grid;grid-template-columns:repeat(auto-fit,minmax(178px,1fr));gap:14px}}
.kpi{{background:var(--surface);border:1px solid var(--ring);border-radius:4px;padding:18px 20px;
  display:flex;flex-direction:column;gap:5px}}
.kpi b{{font:600 34px/1 "IBM Plex Sans",sans-serif;letter-spacing:-.03em}}
.kpi span{{font:500 11px/1.3 "IBM Plex Mono",monospace;letter-spacing:.09em;
  text-transform:uppercase;color:var(--muted)}}
.kpi.hero b{{color:var(--st{di})}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(272px,1fr));gap:16px}}
.card{{background:var(--surface);border:1px solid var(--ring);border-radius:4px;padding:20px;
  display:flex;flex-direction:column;gap:14px}}
.ch{{display:flex;align-items:baseline;justify-content:space-between;gap:10px;
  padding-bottom:12px;border-bottom:1px solid var(--line)}}
.ch h3{{margin:0;font:600 15px/1 "IBM Plex Mono",monospace;letter-spacing:-.01em}}
.tot{{font:400 12px/1 "IBM Plex Mono",monospace;color:var(--muted)}}
.dwrap{{position:relative;display:flex;justify-content:center;padding:4px 0}}
.dwrap svg .seg{{transition:opacity .13s}}
.dwrap:hover svg .seg{{opacity:.42}}
.dwrap svg .seg:hover{{opacity:1}}
.center{{position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;
  justify-content:center;pointer-events:none;gap:1px}}
.center strong{{font:600 38px/1 "IBM Plex Sans",sans-serif;letter-spacing:-.035em;
  font-variant-numeric:tabular-nums;display:flex;align-items:flex-start;gap:1px}}
.pctsign{{font-size:20px;font-weight:500;color:var(--ink2);line-height:1.35}}
.center span{{font:500 10px/1 "IBM Plex Mono",monospace;letter-spacing:.11em;
  text-transform:uppercase;color:var(--muted)}}
.legend{{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:7px}}
.legend li{{display:grid;grid-template-columns:9px 1fr auto auto;align-items:center;gap:9px;
  font-size:13px;color:var(--ink2)}}
.sw{{width:9px;height:9px;border-radius:2px;box-shadow:0 0 0 1px var(--ring) inset;flex:none}}
.legend .ct{{font:500 13px/1 "IBM Plex Mono",monospace;color:var(--ink);font-variant-numeric:tabular-nums}}
.legend .pc{{font:400 12px/1 "IBM Plex Mono",monospace;color:var(--muted);
  font-variant-numeric:tabular-nums;min-width:30px;text-align:right}}
.smalln{{margin:0;font-size:12px;color:var(--muted);border-top:1px solid var(--line);padding-top:10px}}
.stack{{background:var(--surface);border:1px solid var(--ring);border-radius:4px;padding:22px 24px;
  display:flex;flex-direction:column;gap:11px}}
.srow{{display:grid;grid-template-columns:minmax(90px,140px) 1fr 44px;align-items:center;gap:14px}}
.srow.total{{border-top:1px solid var(--line);padding-top:13px;margin-top:4px}}
.sname{{font:500 12px/1 "IBM Plex Mono",monospace;color:var(--ink2);overflow:hidden;text-overflow:ellipsis}}
.srow.total .sname{{color:var(--ink);font-weight:600}}
.sbar{{display:flex;height:15px;border-radius:3px;overflow:hidden;gap:2px}}
.sseg{{min-width:3px;transition:opacity .13s}}
.sbar:hover .sseg{{opacity:.42}}
.sbar .sseg:hover{{opacity:1}}
.sdone{{font:500 13px/1 "IBM Plex Mono",monospace;text-align:right;
  font-variant-numeric:tabular-nums;color:var(--ink)}}
.skey{{display:flex;flex-wrap:wrap;gap:14px;margin-top:6px;padding-top:14px;border-top:1px solid var(--line)}}
.skey div{{display:flex;align-items:center;gap:7px;font-size:12px;color:var(--ink2)}}
.tbox{{background:var(--surface);border:1px solid var(--ring);border-radius:4px;overflow-x:auto}}
table{{width:100%;border-collapse:collapse;font-size:13px;min-width:720px}}
th{{text-align:left;font:500 10px/1 "IBM Plex Mono",monospace;letter-spacing:.1em;
  text-transform:uppercase;color:var(--muted);padding:14px 16px;border-bottom:1px solid var(--line);
  position:sticky;top:0;background:var(--surface)}}
td{{padding:9px 16px;border-bottom:1px solid var(--line);vertical-align:middle}}
tr:last-child td{{border-bottom:0}}
.k a{{font:500 12px/1 "IBM Plex Mono",monospace;color:var(--accent);text-decoration:none}}
.k a:hover{{text-decoration:underline}}
.sm{{color:var(--ink2);max-width:330px}}
.as{{font:400 12px/1 "IBM Plex Mono",monospace;color:var(--ink2)}}
.nt{{font-size:12px;color:var(--muted)}}
.chip{{display:inline-block;font:500 10px/1 "IBM Plex Mono",monospace;padding:3px 6px;
  border-radius:3px;background:var(--chipbg);color:var(--accent);margin-right:4px}}
.dot{{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:8px;
  box-shadow:0 0 0 1px var(--ring) inset}}
.notes{{display:grid;grid-template-columns:repeat(auto-fit,minmax(290px,1fr));gap:16px}}
.note{{background:var(--surface);border:1px solid var(--ring);border-radius:4px;padding:20px 22px}}
.note h3{{margin:0 0 12px;font:600 13px/1 "IBM Plex Mono",monospace;letter-spacing:.02em}}
.note ul,.note ol{{margin:0;padding-left:19px;display:flex;flex-direction:column;gap:7px;
  font-size:13px;color:var(--ink2)}}
.note a{{color:var(--accent);text-decoration:none;font-family:"IBM Plex Mono",monospace;font-size:12px}}
.note a:hover{{text-decoration:underline}}
.note em{{color:var(--muted);font-style:normal;font-size:12px}}
.note code{{font:400 12px/1 "IBM Plex Mono",monospace;background:var(--chipbg);
  padding:2px 4px;border-radius:3px;word-break:break-word}}
a:focus-visible{{outline:2px solid var(--accent);outline-offset:2px}}
@media (prefers-reduced-motion:reduce){{*{{transition:none!important}}}}
</style>

<div class="wrap">
<header>
  <p class="eyebrow">{e(proj)}{board} · {fmt(w0)} — {fmt(w1)}</p>
  <h1>{e(heading)}</h1>
  <p class="sub">{T["sub"].format(total=AT, track=tracklist, parked=e(M["parked"]))}</p>
</header>

<section class="kpis">
  <div class="kpi hero"><b>{A["counts"][di] / AT * 100:.0f}%</b>
  <span>{T["kpi_closed"].format(done=e(DONE))}</span></div>
  <div class="kpi"><b>{AT}</b><span>{T["kpi_total"]}</span></div>
  <div class="kpi"><b>{inflight}</b><span>{T["kpi_mid"]}</span></div>
  <div class="kpi"><b>{len(d["parked_list"])}</b>
  <span>{T["kpi_parked"].format(parked=e(M["parked"]))}</span></div>
</section>

<section>
  <div class="sechead"><h2>{T["by_label"]}</h2><p>{ring_desc}</p></div>
  <div class="grid">{cards()}</div>
</section>

<section>
  <div class="sechead"><h2>{T["compare"]}</h2><p>{T["compare_desc"]}</p></div>
  <div class="stack">{stacked()}<div class="skey">{keylegend}</div></div>
</section>

<section>
  <div class="sechead"><h2>{T["all_issues"].format(total=AT)}</h2><p>{T["all_desc"]}</p></div>
  <div class="tbox"><table><thead><tr>{th}</tr></thead><tbody>{tbl()}</tbody></table></div>
</section>

<section>
  <div class="sechead"><h2>{T["how"]}</h2></div>
  <div class="notes">
    <div class="note"><h3>{T["rules"]}</h3><ol>
      <li>{T["rule_1"].format(track=tracklist, d0=fmt(w0), d1=fmt(w1))}</li>
      <li>{T["rule_2"].format(parked=e(M["parked"]), cutoff=e(M["parked_cutoff"]))}</li>
      {rules}
      <li>{T["rule_now"]}</li>
    </ol></div>
    <div class="note"><h3>{T["parked_head"].format(parked=e(M["parked"]))}</h3><ul>{parked}</ul></div>
    {exc_block}
    <div class="note"><h3>{T["caveats"]}</h3><ul>
      <li>{T["cav_multi"].format(sum=sum_cats, total=AT)}</li>
      <li>{T["cav_alias"]}</li>
      <li>{T["cav_live"]}</li>
      {extra_note}
      {jql_note}
    </ul></div>
  </div>
</section>
</div>
"""
    with open(a.out, "w", encoding="utf-8") as fh:
        fh.write(HTML)
    print(f"{a.out} written ({len(HTML)} bytes)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
