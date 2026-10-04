"""Build the quant note, note/pricing_the_print.pdf, from the results files. Every number is read from results.

  python note/build_note.py --results results --team "Name One, Name Two"
  python note/build_note.py --results reproduced --team "..."      # after python run_all.py, from a clone

Needs reportlab, pypdf and pdfplumber (note/requirements.txt) and Times New Roman / Arial TrueType fonts
(Windows has them; elsewhere set NOTE_FONT_DIR to a folder with times*.ttf and arial*.ttf). Besides the
results folder it reads derived/kalshi_liquidity_t0.csv, derived/note_inputs.json and
derived/liquidity_per_release.csv (summarized into the results folder). The dashboards are
not embedded; they live in dashboards/ in the repository. After building, the script checks the page count
of the main body, the smallest font size and the margins.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from reportlab.lib import colors  # noqa: E402
from reportlab.lib.enums import TA_CENTER  # noqa: E402
from reportlab.lib.pagesizes import letter  # noqa: E402
from reportlab.lib.styles import ParagraphStyle  # noqa: E402
from reportlab.lib.units import inch  # noqa: E402
from reportlab.pdfbase import pdfmetrics  # noqa: E402
from reportlab.pdfbase.ttfonts import TTFont  # noqa: E402
from reportlab.platypus import (Image, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer,  # noqa: E402
                                Table, TableStyle)

TITLE = "Pricing the Print: Do Prediction Markets Tell You When to Sell CPI-Day Volatility?"
TRACK = "Track 03: Systematic Trading · Gator Quant Hacks 2026"
REPO = "https://github.com/shmoney2/kalshi-cpi-prereg"
TEAM_PLACEHOLDER = "[TEAM NAMES]"
MAIN_PAGE_LIMIT = 5
MIN_FONT_PT = 11.0
BODY_PT = 11
FIG_H = 2.2          # figure height in inches (width 6.5)

SHORT = {"Always sell": "Always sell", "Kalshi filter (CPI uncertainty)": "Kalshi filter (CPI SD)",
         "Kalshi news x sensitivity": "News × sensitivity", "CPI uncertainty IQR (reported only)": "CPI IQR (rep.)",
         "Fed liveness (reported only)": "Fed liveness (rep.)", "Option price only (VIX1D)": "Option price (VIX1D)",
         "VIX only": "VIX only", "Kalshi filter (Fed liveness)": "Kalshi filter (liveness)"}


# ---------------------------------------------------------------- fonts and styles
def register_fonts():
    folder = os.environ.get("NOTE_FONT_DIR", r"C:\Windows\Fonts")
    files = {"TNR": "times.ttf", "TNR-B": "timesbd.ttf", "TNR-I": "timesi.ttf", "TNR-BI": "timesbi.ttf",
             "AR-B": "arialbd.ttf"}
    for name, f in files.items():
        path = os.path.join(folder, f)
        if not os.path.exists(path):
            raise SystemExit(f"Font {path} not found; set NOTE_FONT_DIR to a folder with Times New Roman and Arial.")
        pdfmetrics.registerFont(TTFont(name, path))
    pdfmetrics.registerFontFamily("TNR", normal="TNR", bold="TNR-B", italic="TNR-I", boldItalic="TNR-BI")


def styles():
    body = ParagraphStyle("body", fontName="TNR", fontSize=BODY_PT, leading=13.2, spaceAfter=3.5)
    return {
        "head": ParagraphStyle("head", fontName="TNR-B", fontSize=BODY_PT, leading=13.2, spaceAfter=4,
                               textColor=colors.HexColor("#444444")),
        "title": ParagraphStyle("title", fontName="AR-B", fontSize=15.5, leading=19, spaceAfter=3),
        "sub": ParagraphStyle("sub", parent=body, fontName="TNR-I", spaceAfter=6),
        "h1": ParagraphStyle("h1", fontName="AR-B", fontSize=12.5, leading=15, spaceBefore=6, spaceAfter=2.5, keepWithNext=1),
        "h2": ParagraphStyle("h2", fontName="TNR-B", fontSize=BODY_PT, leading=13.2, spaceBefore=3, spaceAfter=1.5, keepWithNext=1),
        "body": body,
        "bullet": ParagraphStyle("bullet", parent=body, leftIndent=13, bulletIndent=2, spaceAfter=1.5,
                                 bulletFontName="TNR", bulletFontSize=BODY_PT),
        "cap": ParagraphStyle("cap", parent=body, fontName="TNR-I", spaceBefore=1, spaceAfter=5),
        "cell": ParagraphStyle("cell", fontName="TNR", fontSize=BODY_PT, leading=12.4),
        "cellb": ParagraphStyle("cellb", fontName="TNR-B", fontSize=BODY_PT, leading=12.4),
        "foot": ParagraphStyle("foot", fontName="TNR", fontSize=BODY_PT, alignment=TA_CENTER),
    }


def table(rows, widths, st, header_rows=1, align_from=1, zebra=False):
    data = [[Paragraph(str(c), st["cellb"] if i < header_rows else st["cell"]) for c in r] for i, r in enumerate(rows)]
    t = Table(data, colWidths=widths, repeatRows=header_rows, hAlign="LEFT")
    cmds = [("VALIGN", (0, 0), (-1, -1), "BOTTOM"), ("TOPPADDING", (0, 0), (-1, -1), 0.6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 1.4), ("LEFTPADDING", (0, 0), (-1, -1), 2.5),
            ("RIGHTPADDING", (0, 0), (-1, -1), 2.5),
            ("LINEABOVE", (0, 0), (-1, 0), 0.8, colors.black), ("LINEBELOW", (0, header_rows - 1), (-1, header_rows - 1), 0.5, colors.black),
            ("LINEBELOW", (0, -1), (-1, -1), 0.8, colors.black)]
    if zebra:
        for i in range(header_rows, len(rows)):
            if (i - header_rows) % 4 in (2, 3):
                cmds.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor("#F1F3F2")))
    t.setStyle(TableStyle(cmds))
    for i in range(len(rows)):
        for j in range(align_from, len(rows[0])):
            data[i][j].style = ParagraphStyle(f"r{i}{j}", parent=data[i][j].style, alignment=2)
    return t


# ---------------------------------------------------------------- data
def load(results):
    j = lambda f: json.load(open(os.path.join(results, f)))
    d = {"s1": j("results.json"), "s2": j("stage2_results.json"), "tr": j("track_results.json"),
         "ev": pd.read_csv(os.path.join(results, "stage2_events.csv")),
         "st1": json.load(open(os.path.join(ROOT, "PREREG_STAMP.json"))),
         "st2": json.load(open(os.path.join(ROOT, "PREREG_STAMP.stage2.json"))),
         "st3": json.load(open(os.path.join(ROOT, "PREREG_STAMP.liquidity.json")))}
    liq = os.path.join(ROOT, "derived", "kalshi_liquidity_t0.csv")
    d["liq"] = pd.read_csv(liq) if os.path.exists(liq) else None
    d["inputs"] = json.load(open(os.path.join(ROOT, "derived", "note_inputs.json")))
    from liquidity_measure import summarize          # pre-registered liquidity measurement, from committed metrics
    lpr = os.path.join(ROOT, "derived", "liquidity_per_release.csv")
    d["lq"] = summarize(lpr, results)
    d["lq"]["crossing_share_max"] = float(pd.read_csv(lpr)["crossing_share_of_straddle"].max())
    d["x"] = extras(d)
    return d


def extras(d):
    """Numbers computed for the note from the per-release data: contract economics at the median release,
    operating-rule drawdowns, correlations with the index move, and the Sharpe ratio's standard error."""
    import math
    from stage2_lite import fly_pnl
    from track_report import COSTS, period_metrics, skip_column, trade_record
    ev = d["ev"].sort_values("release_date").reset_index(drop=True)
    spx = d["inputs"]["median_spy_close_on_release_eves"] * d["inputs"]["spx_approx_multiplier"]
    sig = float(ev["sigma_implied"].median())
    fly = fly_pnl(sig, 0.0, cost_frac=0.03)
    cost_pct = 0.03 * fly["straddle"]                      # entry cost, % of index notional
    max_loss_pts = fly["max_loss"] / 100 * spx
    x = {"spx": spx, "sigma": sig, "straddle_pct": fly["straddle"], "wing_pct": fly["wing"],
         "cost_bps": 100 * cost_pct, "cost_pts": cost_pct / 100 * spx, "cost_pts_leg": cost_pct / 100 * spx / 4,
         "max_loss_pts": max_loss_pts, "max_loss_usd": 100 * max_loss_pts, "capital_usd": 100 * max_loss_pts / 0.01,
         "xsp_max_loss_usd": 10 * max_loss_pts, "xsp_capital_usd": 10 * max_loss_pts / 0.01}
    dd = {}
    for cost in COSTS:                                     # full-sample drawdown, worst strategy, per cost
        recs = [trade_record(s, r, cost) for s, r in zip(ev["sigma_implied"], ev["r_close"])]
        rets = np.array([z["ret"] for z in recs]); prem = np.array([z["premium_traded"] for z in recs])
        dd[cost] = max(period_metrics(rets, prem, ev[skip_column(n)].astype(bool).to_numpy())["max_drawdown_pct"]
                       for n in d["s2"]["strategies"])
    x["max_dd"] = dd
    rets3 = np.array([trade_record(s, r, 0.03)["ret"] for s, r in zip(ev["sigma_implied"], ev["r_close"])])
    x["corr_r"] = float(np.corrcoef(rets3, ev["r_close"])[0, 1])
    x["corr_abs_r"] = float(np.corrcoef(rets3, ev["r_close"].abs())[0, 1])
    n_oos = d["tr"]["stage2_split"]["n_out_of_sample"]
    sr_oos = next(r["sharpe"] for r in d["tr"]["stage2_split"]["rows"]
                  if r["strategy"] == "Always sell" and r["period"] == "out_of_sample" and r["cost"] == 0.03)
    x["sharpe_se_iid"] = math.sqrt(12 / n_oos)
    x["sharpe_oos"] = sr_oos
    x["sharpe_se_lo"] = math.sqrt((1 + (sr_oos / math.sqrt(12)) ** 2 / 2) / n_oos) * math.sqrt(12)
    return x


def f(x, dp=2, pct=False, sign=False):
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return "n/a"
    s = f"{x:+.{dp}f}" if sign else f"{x:.{dp}f}"
    return s.replace("-", "−") + ("%" if pct else "")


def equity_figure(d, path, cost=0.03):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from track_report import skip_column, trade_record
    plt.rcParams.update({"font.family": "Times New Roman", "font.size": 11, "axes.unicode_minus": False})
    ev = d["ev"].sort_values("release_date").reset_index(drop=True)
    rets = np.array([trade_record(s, r, cost)["ret"] for s, r in zip(ev["sigma_implied"], ev["r_close"])])
    x = pd.to_datetime(ev["release_date"])
    cutoff = pd.Timestamp(d["tr"]["stage2_split"]["cutoff"])
    fig, ax = plt.subplots(figsize=(6.5, FIG_H))
    ax.axvspan(cutoff, x.iloc[-1] + pd.Timedelta(days=20), color="#9a9a9a", alpha=0.22, lw=0)
    ax.text(cutoff + pd.Timedelta(days=12), 0.04, "Out of\nsample", transform=ax.get_xaxis_transform(), va="bottom", fontsize=11)
    names = [n for n in d["s2"]["strategies"] if n.startswith(("Always", "Kalshi filter", "Option price"))]
    style = {"Always sell": ("#1b1b1b", "-", 2.2), "Option price only (VIX1D)": ("#7a7a7a", "--", 1.6)}
    for n in names:
        skip = ev[skip_column(n)].astype(bool).to_numpy()
        eq = np.cumprod(1 + np.where(skip, 0.0, rets))
        c, ls, lw = style.get(n, ("#0b7a5c", "-", 2.0))
        ax.plot(x, 100 * (eq - 1), color=c, ls=ls, lw=lw, label=SHORT.get(n, n))
    ax.axhline(0, color="#444444", lw=0.7)
    ax.set_ylabel("Cumulative return (%)")
    ax.legend(loc="upper left", frameon=False, fontsize=11, ncol=3, bbox_to_anchor=(0, -0.16))
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(path, dpi=300)
    plt.close(fig)


# ---------------------------------------------------------------- content
def story(d, st, fig_path, team):
    s1, s2, tr, p, x = d["s1"], d["s2"], d["tr"], d["s1"]["primary"], d["x"]
    mech, prem = s1["mechanism"], s2["premium"]
    sp1, sp2 = tr["stage1_split"], tr["stage2_split"]
    i1, o1 = sp1["periods"]["in_sample"], sp1["periods"]["out_of_sample"]
    S = s2["strategies"]
    kname = next(k for k in S if k.startswith("Kalshi filter"))
    ev = d["ev"]
    n_tail = int((ev["move_ratio"] > 2).sum())
    fly_win = float((ev["pnl_points"] > 0).mean())
    rows_by = {(r["strategy"], r["period"], r["cost"]): r for r in sp2["rows"]}
    tsens = {(r["pricing"], r["cost"]): r for r in tr["t_sensitivity"]}
    c1, c2 = d["st1"], d["st2"]
    B, P, H1, H2, CAP = st["body"], st["bullet"], st["h1"], st["h2"], st["cap"]
    para = lambda t, s=B: Paragraph(t, s)
    bullet = lambda t: Paragraph(t, P, bulletText="•")
    st1_date, st2_date = c1["sent_at_utc"][:16].replace("T", " "), c2["sent_at_utc"][:16].replace("T", " ")
    always_is3, always_oos3 = rows_by[("Always sell", "in_sample", 0.03)], rows_by[("Always sell", "out_of_sample", 0.03)]
    out = []

    out += [para(f"{team} · {TRACK}", st["head"]),
            para(TITLE, st["title"]),
            para(f"Quant research note · October 2026 · Code and data: <link href='{REPO}' color='blue'>{REPO}</link>", st["sub"])]

    # Summary (1/4 page)
    out += [para("Summary", H1), para(
        "Selling S&amp;P 500 options into a CPI release collects an event premium, but a few releases produce moves "
        "large enough to erase months of gains. We tested whether Kalshi prediction markets tell a seller when to stand "
        f"aside. Both tests were pre-registered and timestamped on Solana mainnet. <b>Stage 1</b> ({s1['n']} releases, "
        f"{s1['date_range'][0][:7]} to {s1['date_range'][1][:7]}): Kalshi's uncertainty about the next FOMC decision does "
        f"not reliably predict how hard stocks react to CPI surprises (<b>NO-GO</b>). <b>Stage 2-lite</b> ({s2['n']} releases, "
        f"VIX1D as the option price): the realized move was smaller than implied on {prem['share_premium_positive']:.0%} of "
        "releases, yet the average variance premium is about zero, a defined-risk butterfly is flat in sample, and neither "
        "Kalshi filter improved timing. The CPI-day premium looks like fair compensation for tail risk; we would not "
        "trade it, and the next step is real option quotes. What is distinctive is the design: Kalshi's CPI and Fed "
        "ladders map onto a news-times-sensitivity view of event premia, both plans were fixed and timestamped on a public "
        "blockchain before the outcome data, and every number reproduces from one command.")]

    # Hypothesis (1/2 page)
    out += [para("Hypothesis", H1), para(
        "An announcement's market impact is the news it releases times the market's sensitivity to that news "
        "(Knox, Londono, Samadi and Vissing-Jorgensen, \"Equity Premium Events\"). Kalshi's CPI ladders price the news; "
        "its Fed ladders say whether the next FOMC meeting is \"live\", which should raise sensitivity. "
        "<b>H1:</b> in r = a + b·S + c·(S×L) + d·L + e·VIX, where r is the S&amp;P 500 move from the prior close to "
        "09:35 ET, S the core CPI surprise against Kalshi's 08:25 expectation and L Fed liveness the evening before, "
        "c &lt; 0: a hot print hurts more when the meeting is live. <b>H2 (mechanism):</b> CPI moves Kalshi's expected "
        "Fed rate more when the meeting is live. <b>Stage 2 hypothesis:</b> skipping releases where a Kalshi input is in "
        "the top third of its history avoids the releases where selling loses, better than random skips and better "
        "than filtering on the option price."),
        para("<b>Who is on the other side.</b> Buyers of CPI-day options are largely hedgers paying for protection against a "
             "jump on the print. A premium above expected losses could persist because few investors are willing to hold "
             "jump risk, so those who do are paid for it. The trade fails if the premium only pays for the tail risk itself: "
             "sellers then break even on average once the rare large moves arrive, and no timing filter can rescue it. "
             "Stage 2 tests exactly this failure condition. A Kalshi filter could add to the option price because VIX1D "
             "prices how large a move to expect but not why: Kalshi's CPI ladder gives the distribution of the print, and "
             "its Fed ladder shows whether a surprise would change the next policy decision, the channel that should make "
             "some releases riskier than their implied volatility suggests."),
        para(f"<b>Pre-registration.</b> Stage 1's plan and code were frozen in commit <font name='TNR'>{c1['git_commit'][:7]}</font> "
             f"and stamped on Solana mainnet at {st1_date} UTC (<link href='{c1['explorer']}' color='blue'>transaction "
             f"{c1['signature'][:10]}…</link>) before any release-day data were downloaded. Stage 2-lite was frozen in "
             f"<font name='TNR'>{c2['git_commit'][:7]}</font> and stamped at {st2_date} UTC (<link href='{c2['explorer']}' "
             f"color='blue'>transaction {c2['signature'][:10]}…</link>) before VIX1D was downloaded, but after Stage 1's "
             "returns had been computed; its plan says so. Each memo holds the SHA-256 of a manifest hashing every frozen "
             "file, and <font name='TNR'>timestamp_solana.py verify</font> rechecks it.")]

    # Data (1/2 page)
    liq = d["liq"]
    if liq is not None:                                     # the releases in the Stage 1 sample
        liq = liq[liq["release_date"].isin(set(s1["sample_dates"]))]
    med = lambda role, col: float(liq.loc[liq.role == role, col].median()) if liq is not None else float("nan")
    out += [para("Data", H1),
            bullet("<b>Kalshi public API</b>: core and headline CPI ladders (KXCPI, KXCPICORE) and next-meeting Fed ladders "
                   "(KXFED), 2021–2026, snapshots at 15:45 ET the evening before (t0), 08:25 and 10:00 on release day. "
                   "Price rule: last trade within 24 hours, else the bid-ask midpoint if the spread is at most $0.10; "
                   "ladders need at least 4 usable strikes."),
            bullet("<b>Massive (formerly Polygon.io)</b>: SPY daily and minute bars and dividends. SPY replaces the index, "
                   "which the data plan lacked; the switch was fixed before the freeze. Dividends are added back on ex-dates."),
            bullet("<b>Cboe</b>: VIX and VIX1D daily history (free files). From 16:00 to 16:15 VIX1D uses only next-day "
                   "SPX options, so its close on a release eve prices release-day risk; values before its April 2023 "
                   "launch are Cboe back-calculations, starting May 2022."),
            bullet("<b>BLS</b> CPI release calendar: September 2025 CPI (moved by the shutdown after Kalshi's markets had "
                   "closed) and October 2025 CPI (never published) are excluded."),
            para(f"Samples: {s1['n']} releases with complete Stage 1 data ({s1['date_range'][0]} to {s1['date_range'][1]}); "
                 f"{s2['n']} with VIX1D for Stage 2 (from {s2['date_range'][0]}). Three data-plumbing fixes made after the "
                 "freeze (matching events to the BLS calendar, a standing-quote lookback, reading a non-numeric settlement "
                 "value) were committed with tests before the test was run; Appendix E lists them with two parsing fixes "
                 "made before the freeze.")]

    # Methodology (1 page)
    tc = {k: 0 for k in ("s1p", "s1d", "s2p", "post")}
    dec = {k: 0 for k in tc}
    for r in tr["test_count"]:
        k = {"Stage 1": "s1p", "Stage 2": "s2p", "Post hoc": "post"}[r["stage"]]
        if r["stage"] == "Stage 1" and r["category"] == "Data diagnostic":
            k = "s1d"
        tc[k] += r["specifications"]
    out += [para("Methodology", H1),
            para("<b>Stage 1.</b> H1 is estimated by OLS with HC3 standard errors and one-sided tests; L is the standard "
                 "deviation of Kalshi's distribution for the next meeting's upper bound, standardized; VIX is the prior close. "
                 "GO requires all five of: c &lt; 0; HC3 p &lt; 0.10; within-year permutation p &lt; 0.10 (10,000 draws); the "
                 "same sign in at least 90% of leave-one-out fits; and c &lt; 0 without 2022. Eight robustness variants and H2 "
                 "are reported but never decide."),
            para("<b>Stage 2-lite.</b> The implied daily move is σ = VIX1D/√252 and the variance premium σ² − r², with r the "
                 "close-to-close SPY return; positive means a variance seller earned money. The tradeable proxy is a short "
                 "at-the-money butterfly with wings two implied moves out, priced from a normal distribution with standard "
                 "deviation σ, with entry cost at 3% of the straddle (0% and 6% also run) and 1% of capital at risk per release. "
                 f"The 3% cost is an assumption: at the median release (σ = {x['sigma']:.2f}%, straddle {x['straddle_pct']:.2f}% "
                 f"of the index, SPX ≈ {x['spx']:,.0f}) it equals {x['cost_bps']:.1f} bps of index notional, about "
                 f"{x['cost_pts']:.1f} index points for the position or {x['cost_pts_leg']:.2f} points per leg across four legs. "
                 "A filter skips a release when its input is above the two-thirds point of all earlier values, after a "
                 "6-release burn-in, so every decision uses only the past. \"Kalshi improved the decision\" needs all three: "
                 "skipped releases earn a lower premium than kept ones; a random skip set of the same size does as well in "
                 "under 10% of 10,000 draws; and the filter beats one built on VIX1D alone. After Stage 1's NO-GO the primary "
                 "input is Kalshi's core CPI uncertainty (ladder standard deviation); Fed liveness, CPI uncertainty measured "
                 "by interquartile range, news × sensitivity, VIX1D and VIX filters are reported."),
            para("<b>Track additions (post hoc, logged as dated deviations).</b> Out of sample is the most recent 20% of each "
                 "sample's date span. Annualized figures assume 12 releases a year and count skipped releases as zero; "
                 "turnover is option premium traded per year as a multiple of capital. Full-sample results were seen before "
                 "the split, which follows the track's mechanical rule. A pricing sensitivity reprices the butterfly under "
                 "Student-t distributions scaled to VIX1D's variance."),
            para("<b>Multiple testing.</b> Every test, variant, strategy and cost level run is counted in Table 1 "
                 "(itemized in Appendix D). Only the Stage 1 primary model and the Stage 2 primary filter can produce a "
                 "positive verdict."),
            table([["Group", "Specifications", "Can decide"],
                   ["Stage 1, pre-registered", tc["s1p"], "6 (primary model, 5 conditions)"],
                   ["Stage 1, data diagnostics", tc["s1d"], "none"],
                   ["Stage 2, pre-registered", tc["s2p"], "3 checks on the primary filter"],
                   ["Post hoc (split, pricing sensitivity)", tc["post"], "none"],
                   ["Total", tr["test_count_total"], ""]],
                  [2.75 * inch, 1.05 * inch, 2.6 * inch], st, align_from=1),
            para("Table 1. Specifications run on real data. Resampling draws count once per test.", CAP)]

    # Results (1 1/4 pages)
    s1rows = [["Sample", "n", "c", "HC3 SE", "p (HC3)", "p (perm.)"],
              ["Full sample (decision)", s1["n"], f(p["c"]), f(p["se_c"]), f(p["p_hc3"], 3), f(p["p_perm"], 3)],
              [f"In sample, to {sp1['cutoff']}", i1["n"], f(i1["c"]), f(i1["se_hc3"]), f(i1["p_hc3"], 3), f(i1["p_perm"], 3)],
              ["Out of sample (descriptive)", o1["n"], f(o1["c"]), f(o1["se_hc3"]), f(o1["p_hc3"], 3), f(o1["p_perm"], 3)]]
    out += [para("Results", H1),
            KeepTogether([table(s1rows, [2.25 * inch, 0.45 * inch, 0.75 * inch, 0.8 * inch, 0.85 * inch, 0.9 * inch], st),
                          para("Table 2. Stage 1 primary model; c is per 1 SD of liveness, % per percentage point of surprise. "
                               "About 10 releases cannot support inference.", CAP)]),
            para(f"<b>Stage 1: NO-GO.</b> The interaction has the predicted sign: a core print 0.1 point hotter than Kalshi "
                 f"expected moved SPY {f(p['sens_settled'], 2)}% when the next meeting looked settled and "
                 f"{f(p['sens_live'], 2)}% when it looked live. But it fails three of five conditions (Table 2): the HC3 and "
                 f"permutation p-values are {f(p['p_hc3'], 2)} and {f(p['p_perm'], 2)}, and without 2022 the sign reverses "
                 f"(c = {f(p['c_ex2022'])}), so the effect rests on 2022's hiking cycle. The mechanism does hold: CPI moves "
                 f"Kalshi's expected Fed rate more when the meeting is live (H2, c = {f(mech['c'])}, p = {f(mech['p'], 3)}), "
                 "partly by construction since a wider distribution has more room to move. The market's odds react; stock "
                 "sensitivity does not reliably follow."),
            para(f"<b>Stage 2-lite: no evidence that Kalshi helps.</b> Realized variance was below VIX1D-implied variance on "
                 f"{prem['share_premium_positive']:.0%} of releases (the average move was {prem['mean_move_ratio']:.2f} implied "
                 f"standard deviations), yet the mean variance premium is {f(prem['mean_var_premium'], 2)} (90% interval "
                 f"{f(prem['ci90'][0], 2)} to {f(prem['ci90'][1], 2)}): {n_tail} releases with moves above two implied standard "
                 f"deviations offset the many small wins. After costs and wing premium the butterfly made money on "
                 f"{fly_win:.0%} of releases. The CPI-uncertainty filter skipped releases that were worse for sellers and kept "
                 f"better ones than the VIX1D filter, but random skips did as well {s2['p_perm']:.0%} of the time (p = "
                 f"{f(s2['p_perm'], 3)}), so it fails the decision rule. Always selling was flat in sample "
                 f"({f(always_is3['ann_return_pct'], 2)}% a year at 3% cost) and positive only over the "
                 f"{sp2['n_out_of_sample']} out-of-sample releases ({f(always_oos3['ann_return_pct'], 2)}% a year; Table 3, "
                 f"Figure 1). With {sp2['n_out_of_sample']} monthly observations an annualized Sharpe ratio has a standard error "
                 f"of about √(12/{sp2['n_out_of_sample']}) ≈ {x['sharpe_se_iid']:.1f} ({x['sharpe_se_lo']:.1f} at the observed "
                 f"{x['sharpe_oos']:.2f}, by Lo's formula), so the out-of-sample Sharpe ratios rest on very little data. This is "
                 "the Hypothesis's failure condition: the premium appears to pay for the tails rather than exceed them.")]
    t3 = [["Cost", "Strategy", "Per.", "Trades", "Ann. ret.", "Ann. vol.", "Sharpe", "Max DD", "Turnover"]]
    for cost in (0.03, 0.06):
        for name in ("Always sell", kname, "Option price only (VIX1D)"):
            for per, lab in (("in_sample", "IS"), ("out_of_sample", "OOS")):
                r = rows_by[(name, per, cost)]
                t3.append([f"{cost:.0%}", SHORT.get(name, name), lab, r["trades"], f(r["ann_return_pct"], 2, True),
                           f(r["ann_vol_pct"], 2, True), f(r["sharpe"], 2), f(r["max_drawdown_pct"], 2, True),
                           f"{r['turnover_x_capital']:.2f}×"])
    out += [KeepTogether([Image(fig_path, width=6.5 * inch, height=FIG_H * inch),
                          para("Figure 1. Growth of capital at 3% entry cost; the shaded region is out of sample.", CAP)]),
            KeepTogether([table(t3, [0.42 * inch, 1.55 * inch, 0.42 * inch, 0.58 * inch, 0.7 * inch, 0.7 * inch, 0.58 * inch,
                                     0.66 * inch, 0.74 * inch], st, align_from=3, zebra=True),
                          para(f"Table 3. In sample (IS, {sp2['n_in_sample']} releases) and out of sample (OOS, "
                               f"{sp2['n_out_of_sample']} releases from {sp2['first_oos']}), 1% of capital at risk per release. "
                               "All seven strategies are in Appendix A.", CAP)])]

    # Risk (1/2 page)
    tt = [["Butterfly pricing", "3%: mean/trade", "3%: total", "6%: mean/trade", "6%: total"]]
    for lab in ("Normal (pre-registered)", "Student-t, 6 df", "Student-t, 4 df"):
        a, b = tsens[(lab, 0.03)], tsens[(lab, 0.06)]
        tt.append([lab, f(a["mean_return_pct"], 3, True, True), f(a["total_return_pct"], 2, True, True),
                   f(b["mean_return_pct"], 3, True, True), f(b["total_return_pct"], 2, True, True)])
    rk = tr["risk"]
    fb = {r["factor"]: r for r in rk["factors"]}
    fac = lambda k: fb[k]
    sc = rk["scenarios"]
    w3 = sc["worst_releases"][:3]
    reg = [["Regime (always sell, 3% cost)", "n", "Mean/trade", "Total", "Worst", "Hit rate"]] + \
          [[r["regime"].replace("2023 to 2026", "2023–2026"), r["n"], f(r["mean_return_pct"], 3, True, True),
            f(r["total_return_pct"], 2, True, True), f(r["worst_pct"], 2, True), f"{r['hit_rate']:.0%}"] for r in rk["regimes"]]
    out += [para("Risk", H1),
            para(f"The payoff is short tail risk with a hard cap: the worst release loses the full 1% at risk, which happened "
                 f"whenever the move passed a wing. All strategies share the same {f(always_is3['max_drawdown_pct'], 2)}% "
                 "in-sample drawdown from the burn-in releases of mid-2022. The largest risk is model risk: the proxy prices "
                 "options with a normal distribution, while equity moves on news days have fat tails. Repricing the same "
                 "butterfly under Student-t distributions with the same variance (Table 4) turns always-sell's small profit "
                 "into a loss, because fatter tails make the wings worth more and the credit smaller."),
            KeepTogether([table(tt, [2.1 * inch, 1.05 * inch, 0.95 * inch, 1.05 * inch, 0.95 * inch], st),
                          para(f"Table 4. Always sell, all {s2['n']} releases; post-hoc sensitivity, reported only.", CAP)]),
            para(f"<b>Factor exposure.</b> Regressing always-sell's per-release return (% of capital) on SPY's release-day "
                 "return, its absolute value, the release-day VIX change and VIX1D on the eve (HC3 errors, R² = "
                 f"{rk['r2']:.2f}) gives a market beta of {f(fac('SPY release-day return (%)')['beta'], 2)} (t = "
                 f"{f(fac('SPY release-day return (%)')['t'], 1)}) and {f(fac('Absolute SPY return (%)')['beta'], 2)} per 1% "
                 f"absolute move (t = {f(fac('Absolute SPY return (%)')['t'], 1)}); the VIX change adds nothing (t = "
                 f"{f(fac('VIX change on release day (pts)')['t'], 1)}), and returns rise with the VIX1D level (t = "
                 f"{f(fac('VIX1D on release eve (pts)')['t'], 1)}). Raw correlations with SPY's return and its absolute value "
                 f"are {f(x['corr_r'], 2)} and {f(x['corr_abs_r'], 2)}: the position is short the size of the move, not the market."),
            para(f"<b>Regimes and stress.</b> The 2022 hiking cycle was the bad regime (Table 5). The three worst releases, "
                 + ", ".join(f"{w['release_date']} (SPY {f(w['spy_return_pct'], 2, True, True)})" for w in w3) +
                 ", each lost the full 1%, and any move past the wings, whether 3 or 5 implied standard deviations, loses "
                 f"exactly 1%, so a crash loss is bounded by construction. Maximum losses hit {sc['max_loss_count']} of "
                 f"{rk['n']} releases and never twice in a row (longest losing run {sc['longest_losing_run']}); "
                 f"{sc['losses_to_halve']} maximum losses in a row would trigger the halve-size rule and {sc['losses_to_stop']} "
                 "the stop."),
            KeepTogether([table(reg, [2.45 * inch, 0.4 * inch, 0.95 * inch, 0.85 * inch, 0.75 * inch, 0.8 * inch], st),
                          para("Table 5. Always sell by regime; VIX regimes split at the median prior close.", CAP)]),
            para("<b>Exposure limits and operating rules</b> (set after the backtest, not pre-registered): one position at a "
                 "time, since each butterfly expires the day after it is opened; at most 1% of capital lost per release and "
                 "12% at risk in a year; skip any release whose date moves after the position is planned, as September 2025 "
                 "did; halve position size after a 6% drawdown and stop trading at 10%. None would have triggered: the worst "
                 f"drawdown of any strategy was {x['max_dd'][0.03]:.2f}% at 3% cost ({x['max_dd'][0.06]:.2f}% at 6%).")]

    # Liquidity and capacity (2/3 page)
    lq, c3 = d["lq"], d["st3"]
    out += [para("Liquidity and capacity", H1),
            para(f"The Kalshi inputs are read, not traded, so Kalshi liquidity limits signal quality rather than capacity. At "
                 f"t0 the median 24-hour volume was about {med('cpi_core', 'vol_24h_contracts'):,.0f} contracts across the "
                 f"core CPI ladder and {med('fed', 'vol_24h_contracts'):,.0f} across the Fed ladder, with median quoted spreads "
                 f"of ${med('cpi_core', 'median_spread'):.2f} and ${med('fed', 'median_spread'):.2f}; thin far strikes still "
                 "shape the ladder's standard deviation (see Limitations). On the options side, the strategy trades SPX "
                 "options expiring the next day, about once a month. At 1% of capital at risk per release it trades option "
                 f"premium worth roughly {rows_by[('Always sell', 'in_sample', 0.03)]['turnover_x_capital']:.2f}× capital a "
                 f"year, so capacity is unlikely to bind before the edge does. At the median release one SPX butterfly ($100 "
                 f"multiplier) can lose about {x['max_loss_pts']:.1f} index points, or ${x['max_loss_usd']:,.0f}, so risking 1% "
                 f"per release implies about ${round(x['capital_usd'], -3):,.0f} of capital per contract; XSP, one-tenth the size, "
                 f"brings this to ${x['xsp_max_loss_usd']:,.0f} and about ${round(x['xsp_capital_usd'], -2):,.0f}. Moving the entry-cost assumption from 3% "
                 "to 6% lowers always-sell's mean return per trade from "
                 f"{f(tsens[('Normal (pre-registered)', 0.03)]['mean_return_pct'], 3)}% to "
                 f"{f(tsens[('Normal (pre-registered)', 0.06)]['mean_return_pct'], 3)}%."),
            para(f"<b>Measured SPXW costs.</b> Measured after the main results were known, under a separate plan stamped on "
                 f"Solana before any release-eve option quotes were downloaded (<link href='{c3['explorer']}' color='blue'>transaction</link>), we read real SPXW quotes and volume from 15:45 "
                 f"to 16:15 on each of the {lq['n_releases']} release eves. It computes no returns. "
                 f"All four legs had usable quotes on {lq['n_usable']} eves; on the other {lq['n_releases'] - lq['n_usable']} "
                 "the call-wing strike was never quoted, and missing quotes were not filled in. Crossing all four spreads cost "
                 f"a median {lq['crossing_share_median']:.1%} of the straddle (90th percentile {lq['crossing_share_p90']:.1%}, "
                 f"highest {lq['crossing_share_max']:.1%}), or {lq['crossing_pts_median']:.2f} index points against "
                 f"{lq['assumed_cost_pts_median']:.2f} under the 3% assumption, so 3% was conservative and 6% is a remote stress. "
                 f"Depth is the tighter limit: the thinnest top-of-book size was a median {lq['min_top_size_median']:.0f} "
                 "contracts, so larger orders would walk the book. Trading at most 10% of the thinnest leg's eve volume "
                 f"(median {lq['min_leg_volume_median']:,.0f} contracts) allows a median {lq['capacity_contracts_median']:.0f} "
                 f"butterflies, about ${lq['capacity_capital_median'] / 1e6:.0f} million of capital at 1% risk, and "
                 f"{lq['capacity_contracts_min']:.0f} on the thinnest eve. At 16:15 real straddle mids were a median "
                 f"{lq['straddle_ratio_median']:.2f} of the normal-model price from VIX1D (IQR {lq['straddle_ratio_q25']:.2f}–"
                 f"{lq['straddle_ratio_q75']:.2f}) and wing mids {lq['wings_ratio_median']:.2f} "
                 f"({lq['wings_ratio_q25']:.2f}–{lq['wings_ratio_q75']:.2f}).")]

    # Limitations (1/2 page)
    out += [para("Limitations and what didn't work", H1),
            para("About 50 releases give low power: \"NO-GO\" and \"no evidence\" do not prove the effects are absent, and "
                 "Stage 1's pre-registered power table shows effects smaller than a doubling of sensitivity are often missed. "
                 "The ladder standard deviation used for liveness and CPI uncertainty partly measures how widely Kalshi lists "
                 "strikes (correlation 0.76 with ladder span for liveness). The Stage 2 returns are proxies from VIX1D and a "
                 "pricing model, the close-to-close window includes the whole release day, and pre-2023 VIX1D values are "
                 "back-calculated. The out-of-sample split came after the full-sample results."),
            bullet("Fed liveness as a gauge of stock sensitivity to CPI (Stage 1 NO-GO; the sign reverses without 2022)."),
            bullet(f"A Kalshi CPI-uncertainty filter (random-skip p = {f(s2['p_perm'], 2)}); Fed liveness and IQR variants did no better than always selling."),
            bullet("The always-sell premium under fat-tailed pricing, and in sample at a 6% entry cost."),
            bullet("Index and futures data: the data plan had no SPX index data, and a futures reaction window was dropped because "
                   "minute data could not be exported with verifiable timestamps."),
            para("<b>Conclusion.</b> In 2022–2026 the CPI-day premium in S&amp;P 500 options looks like fair compensation for "
                 "tail risk, and Kalshi's odds do not identify the releases to avoid. We would not trade this strategy. The "
                 "next step is Stage 2 with real SPXW prices at entry and settlement, written and stamped "
                 "before those data are downloaded.")]
    return out


def references(st):
    B, H1 = st["body"], st["h1"]
    refs = [
        "Bureau of Labor Statistics. Consumer Price Index release schedule and news release archive. "
        "https://www.bls.gov/schedule/news_release/cpi.htm; https://www.bls.gov/bls/news-release/cpi.htm",
        "Bürgi, C., Deng, W. and Whelan, K. (2026). \"Makers and Takers: The Economics of the Kalshi Prediction Market.\" "
        "CEPR Discussion Paper 20631; CESifo Working Paper 12122.",
        "Cboe Global Markets. Cboe Volatility Index Mathematics Methodology. "
        "https://cdn.cboe.com/resources/indices/Cboe_Volatility_Index_Mathematics_Methodology.pdf",
        "Cboe Global Markets. \"What the VIX and VIX1D Indices Attempt to Measure and How They Differ\" (VIX1D calculation, "
        "including the 4:00 to 4:15 p.m. next-day-only period). "
        "https://www.cboe.com/insights/posts/what-the-vix-and-vix-1-d-indices-attempt-to-measure-and-how-they-differ",
        "Cboe Global Markets. VIX historical data, VIX_History.csv. "
        "https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv",
        "Cboe Global Markets. VIX1D historical data, VIX1D_History.csv. "
        "https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX1D_History.csv",
        "Diercks, A. M., Katz, J. D. and Wright, J. H. (2026). \"Kalshi and the Rise of Macro Markets.\" Finance and "
        "Economics Discussion Series 2026-010, Board of Governors of the Federal Reserve System; NBER Working Paper 34702.",
        "Kalshi. Trade API v2, public market data (series KXCPI, KXCPICORE, KXFED). "
        "https://api.elections.kalshi.com/trade-api/v2",
        "Knox, B., Londono, J. M., Samadi, M. and Vissing-Jorgensen, A. \"Equity Premium Events.\" Federal Reserve Board working paper.",
        "Lo, A. W. (2002). \"The Statistics of Sharpe Ratios.\" Financial Analysts Journal 58(4), 36–52.",
        "Massive (formerly Polygon.io). Stocks aggregates and reference dividends for SPY. https://api.massive.com",
        "Solana mainnet memo transactions of the two pre-registrations (see Hypothesis) and the liquidity measurement "
        "plan (see Liquidity and capacity); verifiable with "
        "timestamp_solana.py verify.",
        f"Project repository, code and derived data: {REPO}",
    ]
    return [PageBreak(), Paragraph("References", H1)] + [Paragraph(r, B) for r in refs]


def appendix(d, st):
    s1, s2, tr = d["s1"], d["s2"], d["tr"]
    B, H1, H2, CAP, P = st["body"], st["h1"], st["h2"], st["cap"], st["bullet"]
    out = [PageBreak(), Paragraph("Appendix", H1)]
    for cost in (0.03, 0.06):
        rows = [["Strategy", "Per.", "Trades", "Ann. ret.", "Ann. vol.", "Sharpe", "Max DD", "Turnover"]]
        for r in [r for r in tr["stage2_split"]["rows"] if r["cost"] == cost]:
            rows.append([SHORT.get(r["strategy"], r["strategy"]), "IS" if r["period"] == "in_sample" else "OOS", r["trades"],
                         f(r["ann_return_pct"], 2, True), f(r["ann_vol_pct"], 2, True), f(r["sharpe"], 2),
                         f(r["max_drawdown_pct"], 2, True), f"{r['turnover_x_capital']:.2f}×"])
        out += [Paragraph(f"A{'1' if cost == 0.03 else '2'}. All Stage 2 strategies, in and out of sample, {cost:.0%} entry cost", H2),
                table(rows, [1.75 * inch, 0.5 * inch, 0.55 * inch, 0.75 * inch, 0.75 * inch, 0.6 * inch, 0.7 * inch, 0.8 * inch],
                      st, align_from=2, zebra=True), Spacer(1, 6)]
    out.append(Paragraph("\"rep.\" marks reported-only variants. Annualized at 12 releases a year; skipped releases count as zero.", CAP))

    rows = [["Variant", "n", "c", "SE", "p"]] + [[r["label"], r["n"], f(r["c"]), f(r["se"]), f(r["p"], 3)] for r in s1["robustness"]]
    m, pl = s1["mechanism"], s1["placebo"]
    out += [Paragraph("B. Stage 1 decision conditions, robustness, mechanism and placebo", H2),
            table([["Condition", "Passed", "Detail"]] + [[c["name"], "yes" if c["passed"] else "no", c["detail"]] for c in s1["checks"]],
                  [3.6 * inch, 0.7 * inch, 1.9 * inch], st, align_from=3), Spacer(1, 6),
            table(rows, [3.7 * inch, 0.5 * inch, 0.7 * inch, 0.7 * inch, 0.7 * inch], st), Spacer(1, 4),
            Paragraph(f"Mechanism (H2): c = {f(m['c'])} (SE {f(m['se'])}), one-sided p = {f(m['p'], 3)}, n = {m['n']}. "
                      f"Placebo: ordinary-day volatility on liveness, coefficient {f(pl['coef'], 3)} (SE {f(pl['se'], 3)}), n = {pl['n']}. "
                      f"90% wild-bootstrap interval for c: {f(s1['primary']['ci90'][0])} to {f(s1['primary']['ci90'][1])}.", B)]

    rows = [["Strategy", "Trades", "Mean var. prem.", "Mean ret./trade", "Total", "Max DD"]]
    for n, mm in s2["strategies"].items():
        rows.append([SHORT.get(n, n), mm["trades"], f(mm["mean_var_premium"], 3), f(mm["mean_return_pct"], 2, True),
                     f(mm["total_return_pct"], 1, True), f(mm["max_drawdown_pct"], 1, True)])
    out += [Paragraph("C. Stage 2-lite full-sample strategies and decision checks (3% cost)", H2),
            table(rows, [1.9 * inch, 0.6 * inch, 1.1 * inch, 1.1 * inch, 0.75 * inch, 0.75 * inch], st), Spacer(1, 6),
            table([["Check", "Passed", "Detail"]] + [[c["name"], "yes" if c["passed"] else "no", c["detail"]] for c in s2["checks"]],
                  [3.6 * inch, 0.7 * inch, 1.9 * inch], st, align_from=3), Spacer(1, 6),
            table([["Cost", "Strategy", "Mean return per trade"]] +
                  [[f"{c['cost']:.0%}", SHORT.get(c["strategy"], c["strategy"]), f(c["mean_return_pct"], 2, True)] for c in s2["cost_sensitivity"]],
                  [0.7 * inch, 2.6 * inch, 1.8 * inch], st, align_from=2)]

    rows = [["Stage", "Category", "Item", "Specs", "Decides"]] + [[r["stage"], r["category"], r["item"], r["specifications"], r["decision"]]
                                                               for r in tr["test_count"]]
    rows.append(["Total", "", "", tr["test_count_total"], ""])
    out += [Paragraph("D. Every test, variant, strategy and cost level run", H2),
            table(rows, [0.7 * inch, 1.05 * inch, 3.3 * inch, 0.5 * inch, 0.75 * inch], st, align_from=3)]

    out += [Paragraph("E. Disclosures, deviations and data-plumbing fixes", H2),
            Paragraph("Disclosed before the Stage 1 freeze (PREREGISTRATION.md):", B),
            Paragraph("The author viewed the 2022-06-10 CPI reaction in a thinkorswim replay while checking futures data; that "
                      "release is outside the primary sample. Access checks requested SPY bars for two CPI days and printed only row counts.", P, bulletText="•"),
            Paragraph("Parsing fixes made before the freeze, part of the frozen code (commit 1c084b5):", B),
            Paragraph("Strikes read from ticker suffixes for pre-2023 Kalshi contracts without strike fields; CPI events that "
                      "closed the evening before a release dated to the release morning.", P, bulletText="•"),
            Paragraph("Fixed after the freeze, each committed with a test before the test was run:", B)]
    for t in ("Kalshi events matched to the official BLS calendar; the two shutdown releases excluded (commit fd9e61c).",
              "Standing Kalshi quotes found with a 120-day daily-candle lookback, since Kalshi emits candles only for "
              "active periods (commit a3e3199).",
              "A settled value read from contract results when Kalshi's settlement field was not numeric (commit a3e3199)."):
        out.append(Paragraph(t, P, bulletText="•"))
    out += [Paragraph("Logged deviations (2026-10-03, after full-sample results were seen; reporting only, no decision rule changed): "
                      "the out-of-sample split, the Student-t pricing sensitivity, the specification count and the reproduction "
                      "script. Stage 2-lite added two reported-only filters before its stamp. The liquidity measurement (planned "
                      "2026-10-03, stamped 2026-10-04 before any release-eve quotes were downloaded) is a logged exception to the "
                      "rule that options data wait for a Stage 1 GO; it computes no returns.", B),
            Paragraph("F. Dashboards", H2),
            Paragraph("The interactive Stage 1 and Stage 2-lite dashboards are in the repository as dashboards/report.html and "
                      f"dashboards/stage2_report.html (<link href='{REPO}/tree/main/dashboards' color='blue'>{REPO}/tree/main/dashboards</link>). "
                      "Download them and open them in a browser.", B)]
    return out


# ---------------------------------------------------------------- build and check
def build(results, out_pdf, team):
    register_fonts()
    st = styles()
    d = load(results)
    fig = os.path.join(HERE, "_figure_equity.png")
    equity_figure(d, fig)

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("TNR", BODY_PT)
        canvas.drawCentredString(letter[0] / 2, 0.55 * inch, str(doc.page))
        canvas.restoreState()

    doc = SimpleDocTemplate(out_pdf, pagesize=letter, leftMargin=inch, rightMargin=inch, topMargin=inch,
                            bottomMargin=inch, title=TITLE, author=team)
    doc.build(story(d, st, fig, team) + references(st) + appendix(d, st), onFirstPage=footer, onLaterPages=footer)
    from pypdf import PdfReader
    return len(PdfReader(out_pdf).pages)


def check(out_pdf, n_body):
    import pdfplumber
    with pdfplumber.open(out_pdf) as pdf:
        pages = pdf.pages
        ref_page = next(i for i, pg in enumerate(pages[:n_body])
                        if any(l.strip() == "References" for l in (pg.extract_text() or "").splitlines()))
        sizes = [round(c["size"], 2) for pg in pages[:n_body] for c in pg.chars]
        w, h = letter
        out_of_margin = sum(1 for pg in pages for c in pg.chars
                            if c["x0"] < inch - 1 or c["x1"] > w - inch + 1 or (c["top"] < inch - 1 and c["text"].strip()))
        imgs_ok = all(im["x0"] >= inch - 1 and im["x1"] <= w - inch + 1 for pg in pages for im in pg.images)
        fonts = sorted({c["fontname"].split("+")[-1] for pg in pages for c in pg.chars})
        placeholder = TEAM_PLACEHOLDER in (pages[0].extract_text() or "")
    print(f"Main body: {ref_page} pages (limit {MAIN_PAGE_LIMIT}) -> {'OK' if ref_page <= MAIN_PAGE_LIMIT else 'TOO LONG'}")
    print(f"Total pages (body, references, appendix): {n_body}")
    print(f"Smallest font on any page: {min(sizes)} pt (minimum {MIN_FONT_PT}) -> {'OK' if min(sizes) >= MIN_FONT_PT - 0.01 else 'TOO SMALL'}")
    print(f"Characters outside 1-inch margins, all pages: {out_of_margin}; images within margins: {imgs_ok}")
    print(f"Fonts: {', '.join(fonts)}")
    if placeholder:
        print(f"WARNING: header still shows {TEAM_PLACEHOLDER}; pass --team with the team names before submitting.")
    return ref_page <= MAIN_PAGE_LIMIT and min(sizes) >= MIN_FONT_PT - 0.01 and out_of_margin == 0 and imgs_ok


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--results", default=os.path.join(ROOT, "results"))
    ap.add_argument("--out", default=os.path.join(HERE, "pricing_the_print.pdf"))
    ap.add_argument("--team", default=TEAM_PLACEHOLDER, help="team names for the header")
    args = ap.parse_args()
    n_body = build(args.results, args.out, args.team)
    ok = check(args.out, n_body)
    print(f"Wrote {os.path.relpath(args.out, ROOT)}")
    if not ok:
        raise SystemExit("Layout checks failed")


if __name__ == "__main__":
    main()
