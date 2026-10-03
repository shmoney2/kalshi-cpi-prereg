"""Build results/stage2_report.html from stage2_lite.py's outputs. Self-contained; works offline.

  python report_stage2.py --results results --data data
"""
from __future__ import annotations

import argparse
import html
import json
import os

import pandas as pd

MONTHS = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()


def fdate(s):
    y, m, d = (int(x) for x in str(s)[:10].split("-"))
    return f"{d} {MONTHS[m - 1]} {y}"


def signed(x, dp=2, suffix=""):
    if x is None:
        return "n/a"
    return ("+" if x > 0 else "\u2212" if x < 0 else "") + f"{abs(x):.{dp}f}{suffix}"


def equity_svg(dates, series, width=1000, height=380):
    """series: list of (label, css_var, values, dashed). Values are equity multiples starting near 1."""
    ml, mr, mt, mb = 64, 190, 16, 44
    allv = [v for _, _, vals, _ in series for v in vals] + [1.0]
    lo, hi = min(allv), max(allv)
    pad = (hi - lo) * 0.08 or 0.01
    lo, hi = lo - pad, hi + pad
    n = len(dates)
    X = lambda i: ml + (i / max(n - 1, 1)) * (width - ml - mr)
    Y = lambda v: mt + (hi - v) / (hi - lo) * (height - mt - mb)
    parts = [f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="Growth of capital by strategy">']
    step = 0.01 if hi - lo < 0.08 else 0.02 if hi - lo < 0.2 else 0.05
    t = round(lo / step) * step
    while t <= hi:
        if t >= lo:
            parts.append(f'<line x1="{ml}" x2="{width - mr}" y1="{Y(t):.1f}" y2="{Y(t):.1f}" class="{"zero" if abs(t - 1) < 1e-9 else "grid"}"/>')
            parts.append(f'<text x="{ml - 8}" y="{Y(t) + 4:.1f}" text-anchor="end" class="tick">{html.escape(signed((t - 1) * 100, 0, "%") if abs(t - 1) > 1e-9 else "0%")}</text>')
        t = round(t + step, 10)
    for i in (0, n - 1):
        parts.append(f'<text x="{X(i):.1f}" y="{height - mb + 20}" text-anchor="{"start" if i == 0 else "end"}" class="tick">{fdate(dates[i])}</text>')
    labels = []
    for label, var, vals, dashed in series:
        pts = " ".join(f"{X(i):.1f},{Y(v):.1f}" for i, v in enumerate(vals))
        dash = ' stroke-dasharray="6 5"' if dashed else ""
        parts.append(f'<polyline points="{pts}" fill="none" stroke="var({var})" stroke-width="3" stroke-linejoin="round"{dash}/>')
        labels.append([Y(vals[-1]), label, var, vals[-1]])
    labels.sort()
    for i in range(1, len(labels)):
        if labels[i][0] - labels[i - 1][0] < 32:
            labels[i][0] = labels[i - 1][0] + 32
    for y, label, var, last in labels:
        parts.append(f'<text x="{width - mr + 10}" y="{y + 4:.1f}" class="lab" fill="var({var})">{html.escape(label)}</text>')
        parts.append(f'<text x="{width - mr + 10}" y="{y + 19:.1f}" class="sub">{signed((last - 1) * 100, 1, "%")} total</text>')
    parts.append("</svg>")
    return "".join(parts)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--results", default="results")
    ap.add_argument("--data", default="data")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    res = json.load(open(os.path.join(args.results, "stage2_results.json")))
    rel_path = os.path.join(args.data, "releases.csv")
    synthetic = False
    if os.path.exists(rel_path):
        ev = pd.read_csv(rel_path)["headline_event"].dropna().astype(str)
        synthetic = bool(len(ev)) and ev.iloc[0].startswith("SYN")
    stamp = None
    for p in ("PREREG_STAMP.stage2.json", "PREREG_STAMP.json"):
        if os.path.exists(p):
            stamp = (p, json.load(open(p)))
            break

    S = res["strategies"]
    kname = next(k for k in S if k.startswith("Kalshi filter"))
    always, kal, price = S["Always sell"], S[kname], S["Option price only (VIX1D)"]
    improved = res["verdict"] == "IMPROVED"
    chart = equity_svg(res["dates"], [("Always sell", "--settled", always["equity"], False),
                                      ("Kalshi filter", "--live", kal["equity"], False),
                                      ("Option price only", "--muted", price["equity"], True)])
    checks = "".join(
        f'<li><span class="mark {"pass" if c["passed"] else "fail"}">{"&#10003;" if c["passed"] else "&#10007;"}</span>'
        f'<span>{html.escape(c["name"])}</span><span class="detail">{html.escape(c["detail"])}</span></li>' for c in res["checks"])
    rows = "".join(
        f'<tr><td>{html.escape(n)}</td><td>{m["trades"]}</td><td>{m["mean_var_premium"]:.3f}</td>'
        f'<td>{signed(m["mean_return_pct"], 2, "%")}</td><td>{signed(m["total_return_pct"], 1, "%")}</td>'
        f'<td>{m["max_drawdown_pct"]:.1f}%</td><td>{signed(m["worst_release_pct"], 2, "%")}</td>'
        f'<td>{"n/a" if m["sharpe_annual"] is None else f"{m["sharpe_annual"]:.2f}"}</td></tr>' for n, m in S.items())
    skipped = "".join(
        f'<tr><td>{fdate(r["release_date"])}</td><td>{r["move_ratio"]:.2f}</td><td>{signed(r["var_prem"], 3)}</td></tr>'
        for r in res["skipped_by_kalshi"]) or '<tr><td colspan="3">None</td></tr>'
    costs = "".join(f'<tr><td>{c["cost"]:.0%}</td><td>{html.escape(c["strategy"])}</td><td>{signed(c["mean_return_pct"], 2, "%")}</td></tr>'
                    for c in res["cost_sensitivity"])
    prem = res["premium"]
    sentence = (f"Selling every release returned {signed(always['total_return_pct'], 1, '%')} in total with a "
                f"{always['max_drawdown_pct']:.1f}% worst drawdown. Skipping the {kal['skipped']} releases Kalshi flagged "
                f"returned {signed(kal['total_return_pct'], 1, '%')} with a {kal['max_drawdown_pct']:.1f}% worst drawdown.")
    banner = ('<p class="banner">These are synthetic test data generated to check the pipeline. They are not real results.</p>'
              if synthetic else "")
    stamp_html = (f'<div>Plan timestamped on Solana {html.escape(stamp[1].get("network", ""))}: '
                  f'<a href="{html.escape(stamp[1].get("explorer", "#"))}" target="_blank" rel="noopener">view the transaction</a>'
                  f' ({html.escape(stamp[0])}).</div>' if stamp else "")
    page = TEMPLATE
    for k, v in {"__BANNER__": banner, "__CHIP__": "go" if improved else "nogo",
                 "__CHIPTEXT__": "Kalshi helped" if improved else "No evidence yet",
                 "__N__": str(res["n"]), "__RANGE__": f'{fdate(res["date_range"][0])} to {fdate(res["date_range"][1])}',
                 "__INPUT__": html.escape(res["primary_input"]), "__SENTENCE__": html.escape(sentence),
                 "__CHART__": chart, "__CHECKS__": checks, "__VERDICT__": html.escape(res["verdict_text"]),
                 "__ROWS__": rows, "__SKIPPED__": skipped, "__COSTS__": costs,
                 "__PREM__": f'{prem["mean_var_premium"]:.3f}', "__PCI__": f'{prem["ci90"][0]:.3f} to {prem["ci90"][1]:.3f}',
                 "__RATIO__": f'{prem["mean_move_ratio"]:.2f}', "__POS__": f'{prem["share_premium_positive"]:.0%}',
                 "__GEN__": html.escape(res["generated_at"]), "__STAMP__": stamp_html}.items():
        page = page.replace(k, v)
    out = args.out or os.path.join(args.results, "stage2_report.html")
    open(out, "w", encoding="utf-8").write(page)
    print(f"Wrote {out}{' using SYNTHETIC data' if synthetic else ''}")


TEMPLATE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Does Kalshi help decide when to sell CPI-day volatility?</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Public+Sans:wght@400;600;700;800&display=swap" rel="stylesheet">
<style>
:root{--paper:#F3F5F1;--panel:#E8ECE6;--ink:#18302B;--muted:#5B6E68;--rule:#D3DBD5;--grid:#E1E6E0;--live:#0B7A5C;--settled:#97A69F;
--warn:#8A5A00;--bad:#A3322B;color-scheme:light;box-sizing:border-box;padding-top:env(safe-area-inset-top,0px);padding-bottom:env(safe-area-inset-bottom,0px);}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){--paper:#13201D;--panel:#1A2A26;--ink:#E4ECE7;--muted:#9BAEA6;--rule:#2B3D38;--grid:#21332E;--live:#40C79A;--settled:#6E817A;--warn:#E3A93E;--bad:#F08A80;color-scheme:dark;}}
:root[data-theme="dark"]{--paper:#13201D;--panel:#1A2A26;--ink:#E4ECE7;--muted:#9BAEA6;--rule:#2B3D38;--grid:#21332E;--live:#40C79A;--settled:#6E817A;--warn:#E3A93E;--bad:#F08A80;color-scheme:dark;}
html{scroll-padding-top:env(safe-area-inset-top,0px);} *,*::before,*::after{box-sizing:inherit;}
body{margin:0;background:var(--paper);color:var(--ink);font-family:"Public Sans",system-ui,-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;font-size:16px;line-height:1.55;font-variant-numeric:tabular-nums;}
main{max-width:1080px;margin:0 auto;padding:36px 24px 80px;} a{color:inherit}
.banner{border:2px solid var(--warn);color:var(--warn);font-weight:600;padding:10px 14px;border-radius:8px;margin:0 0 28px;max-width:72ch;}
h1{font-size:clamp(2rem,4.6vw,3.3rem);line-height:1.05;letter-spacing:-0.025em;font-weight:800;margin:0 0 18px;max-width:18ch;}
h2{font-size:1.4rem;line-height:1.2;font-weight:700;margin:0 0 6px;} section{margin-top:56px;}
.status{display:flex;flex-wrap:wrap;gap:10px 16px;align-items:center;color:var(--muted);margin:0 0 24px;}
.chip{font-weight:800;padding:3px 12px;border-radius:999px;color:var(--paper);background:var(--muted);} .chip.go{background:var(--live);}
.answer{font-size:clamp(1.1rem,2.2vw,1.35rem);line-height:1.45;max-width:52ch;margin:20px 0 0;}
svg{display:block;width:100%;height:auto;} .grid{stroke:var(--grid);} .zero{stroke:var(--muted);} .tick{fill:var(--muted);font-size:12.5px;}
.lab{font-weight:700;font-size:14px;} .sub{fill:var(--muted);font-size:12px;}
.lede{color:var(--muted);margin:0 0 16px;max-width:68ch;}
.checks{list-style:none;padding:0;margin:0;max-width:820px;} .checks li{display:grid;grid-template-columns:1.6rem 1fr auto;gap:10px;padding:10px 0;border-bottom:1px solid var(--rule);align-items:baseline;}
.mark{font-weight:800;} .pass{color:var(--live);} .fail{color:var(--bad);} .detail{color:var(--muted);font-size:.92rem;}
.tablewrap{overflow-x:auto;} table{border-collapse:collapse;width:100%;min-width:640px;font-size:.92rem;}
th,td{padding:8px 10px;border-bottom:1px solid var(--rule);text-align:right;} th:first-child,td:first-child{text-align:left;} th{color:var(--muted);font-weight:600;font-size:.82rem;}
.two{display:grid;grid-template-columns:1fr 1fr;gap:36px;} .two table{min-width:0;}
.note{color:var(--muted);font-size:.9rem;max-width:72ch;}
footer{margin-top:64px;padding-top:16px;border-top:1px solid var(--rule);color:var(--muted);font-size:.85rem;}
@media (max-width:820px){.two{grid-template-columns:1fr;} main{padding:24px 16px 64px;}}
</style></head><body><main>
__BANNER__
<h1>Does Kalshi help decide when to sell CPI-day volatility?</h1>
<div class="status"><span class="chip __CHIP__">__CHIPTEXT__</span><span>__N__ CPI releases</span><span>__RANGE__</span><span>Kalshi input: __INPUT__</span></div>
__CHART__
<p class="answer">__SENTENCE__</p>
<section><h2>The three conditions</h2><p class="lede">All three must hold. They were fixed in STAGE2_PREREGISTRATION.md before the VIX1D data were downloaded.</p>
<ul class="checks">__CHECKS__</ul><p class="note" style="margin-top:14px"><strong>__VERDICT__</strong></p></section>
<section><h2>Is there an event premium at all?</h2>
<p class="lede">On the average release, VIX1D-implied variance exceeded realized variance by __PREM__ (90% interval __PCI__). Realized moves averaged __RATIO__ implied standard deviations, and sellers earned the premium on __POS__ of releases.</p></section>
<section><h2>Every strategy</h2><p class="lede">Returns use a butterfly priced from VIX1D with an assumed entry cost; each release risks 1% of capital.</p>
<div class="tablewrap"><table><tr><th>Strategy</th><th>Trades</th><th>Mean variance premium</th><th>Mean return per trade</th><th>Total return</th><th>Max drawdown</th><th>Worst release</th><th>Sharpe (annual)</th></tr>__ROWS__</table></div></section>
<section class="two">
<div><h2 style="font-size:1.1rem">Releases Kalshi skipped</h2><p class="note">Move ratio above 1 means the market moved more than implied; a negative premium means sellers lost.</p>
<div class="tablewrap"><table><tr><th>Release</th><th>Move ratio</th><th>Variance premium</th></tr>__SKIPPED__</table></div></div>
<div><h2 style="font-size:1.1rem">Sensitivity to costs</h2><p class="note">Mean return per trade at three assumed entry costs.</p>
<div class="tablewrap"><table><tr><th>Cost</th><th>Strategy</th><th>Mean return</th></tr>__COSTS__</table></div></div>
</section>
<section><h2 style="font-size:1.1rem">How to read this</h2><p class="note">VIX1D at 4:15 p.m. the day before a release is computed only from options expiring on release day, so it is the market's own price for that day. These are proxies, not traded prices: there are no actual bid-ask quotes, and real straddles can be priced differently from the normal approximation. With about 50 releases, a result of "no evidence" does not prove Kalshi is useless.</p></section>
<footer><div>Generated __GEN__.</div>__STAMP__</footer>
</main></body></html>
"""

if __name__ == "__main__":
    main()
