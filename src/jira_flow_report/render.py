#!/usr/bin/env python3
"""Step 3: report.json -> a self-contained HTML page.

Standalone by design: stdlib only, no imports from this package, no network.

Colour: workflow stages are an ORDERED scale, so this uses an ordinal
single-hue ramp rather than categorical hues. The 5-stage default is validated
in both light and dark modes (monotone lightness, visible step gaps, the step
nearest the surface still clearing 2:1); dark mode reverses the ramp so the
closing stage is the lightest step on a dark ground. Other stage counts fall
back to even spacing over the same ramp — revalidate if you change --stages.
"""

from __future__ import annotations

import argparse
import html
import json
import math
import sys

RAMP_L = [
    "#86b6ef",
    "#6da7ec",
    "#5598e7",
    "#3987e5",
    "#2a78d6",
    "#256abf",
    "#1c5cab",
    "#184f95",
    "#104281",
    "#0d366b",
]
RAMP_D = [
    "#cde2fb",
    "#b7d3f6",
    "#9ec5f4",
    "#86b6ef",
    "#6da7ec",
    "#5598e7",
    "#3987e5",
    "#2a78d6",
    "#256abf",
    "#1c5cab",
    "#184f95",
]
VALIDATED_L = ["#86b6ef", "#5598e7", "#2a78d6", "#1c5cab", "#104281"]
VALIDATED_D = ["#184f95", "#256abf", "#3987e5", "#86b6ef", "#b7d3f6"]

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


def ramp(n: int):
    if n == 5:
        return VALIDATED_L, VALIDATED_D

    def pick(steps):
        return [steps[round(i * (len(steps) - 1) / max(n - 1, 1))] for i in range(n)]

    return pick(RAMP_L), list(reversed(pick(RAMP_D)))


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
    p.add_argument("--title", default=None, help="page <title>: a short noun phrase")
    p.add_argument("--heading", default=None, help="the h1 on the page")
    return p


def main(argv: list[str] | None = None) -> int:
    a = build_parser().parse_args(argv)
    try:
        with open(a.report) as fh:
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
    L, DK = ramp(len(ST))
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
    keylegend = "".join(
        f'<div><span class="sw" style="background:var(--st{i})"></span>{e(s)}</div>'
        for i, s in enumerate(ST)
    )
    th = "".join(f"<th>{e(x)}</th>" for x in T["th"])
    board = f" · board {M['board']}" if M.get("board") else ""

    HTML = f"""<title>{e(title)}</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500;600&display=swap">
<style>
:root {{
  --plane:#f9f9f7; --surface:#fcfcfb; --ink:#0b0b0b; --ink2:#52514e; --muted:#898781;
  --line:#e1e0d9; --ring:rgba(11,11,11,.10); --accent:#1c5cab; --chipbg:rgba(28,92,171,.09);
  {tl} color-scheme:light;
}}
@media (prefers-color-scheme:dark) {{
  :root:not([data-theme="light"]) {{
    --plane:#0d0d0d; --surface:#1a1a19; --ink:#fff; --ink2:#c3c2b7; --muted:#898781;
    --line:#2c2c2a; --ring:rgba(255,255,255,.10); --accent:#86b6ef; --chipbg:rgba(134,182,239,.13);
    {td} color-scheme:dark;
  }}
}}
:root[data-theme="dark"] {{
  --plane:#0d0d0d; --surface:#1a1a19; --ink:#fff; --ink2:#c3c2b7; --muted:#898781;
  --line:#2c2c2a; --ring:rgba(255,255,255,.10); --accent:#86b6ef; --chipbg:rgba(134,182,239,.13);
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
.kpi.hero b{{color:var(--accent)}}
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
  <div class="sechead"><h2>{T["by_label"]}</h2><p>{T["by_label_desc"]}</p></div>
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
    with open(a.out, "w") as fh:
        fh.write(HTML)
    print(f"{a.out} written ({len(HTML)} bytes)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
