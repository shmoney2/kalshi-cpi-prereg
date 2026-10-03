"""Build report.html: a self-contained dashboard of the Fed-liveness test.

  python report.py --results results --data data --out results/report.html

Reads results/results.json, results/event_table.csv, results/distributions.json and
data/releases.csv. The HTML embeds all data, needs no server, and works offline.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import subprocess

import numpy as np
import pandas as pd

EVENT_COLS = ["release_date", "surprise_core", "fed_sd_t0_bp", "r_open", "r_open_source", "vix_prev",
              "core_actual", "core_mean_pre", "core_mean_t0", "fed_meeting_date", "days_to_meeting",
              "d_fed_mean_bp", "fed_mean_t0", "fed_mean_post", "n_core_strikes_t0", "n_fed_strikes_t0",
              "fomc_same_day"]


def clean(x):
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, (float, np.floating)):
        return None if math.isnan(x) else round(float(x), 6)
    if isinstance(x, (np.bool_,)):
        return bool(x)
    return x


def git_commit():
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], stderr=subprocess.DEVNULL,
                                       text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--results", default="results")
    ap.add_argument("--data", default="data")
    ap.add_argument("--out", default=None)
    ap.add_argument("--title", default="Does a live Fed meeting make stocks care more about CPI?")
    args = ap.parse_args()
    out = args.out or os.path.join(args.results, "report.html")

    res = json.load(open(os.path.join(args.results, "results.json")))
    table = pd.read_csv(os.path.join(args.results, "event_table.csv"))
    dists = json.load(open(os.path.join(args.results, "distributions.json")))
    rel_path = os.path.join(args.data, "releases.csv")
    rel = pd.read_csv(rel_path) if os.path.exists(rel_path) else pd.DataFrame()
    synthetic = bool(len(rel)) and str(rel["headline_event"].dropna().astype(str).iloc[0]).startswith("SYN")

    sample = set(res.get("sample_dates", []))
    events = []
    for r in table.to_dict("records"):
        e = {k: clean(r.get(k)) for k in EVENT_COLS}
        e["in_sample"] = str(r["release_date"]) in sample
        missing = [lab for col, lab in (("surprise_core", "core CPI forecast"), ("fed_sd_t0_bp", "Fed odds"),
                                         ("r_open", "S&P 500 move"), ("vix_prev", "VIX"))
                   if e.get(col) is None]
        e["excluded_reason"] = None if e["in_sample"] else ("missing " + ", ".join(missing) if missing else "excluded")
        events.append(e)

    lines = {}
    med = res.get("liveness_median")
    ins = [e for e in events if e["in_sample"]]
    if med is not None and ins:
        for name, keep in (("settled", lambda e: e["fed_sd_t0_bp"] < med), ("live", lambda e: e["fed_sd_t0_bp"] >= med)):
            grp = [e for e in ins if keep(e)]
            if len(grp) >= 3:
                slope, icpt = np.polyfit([g["surprise_core"] for g in grp], [g["r_open"] for g in grp], 1)
                lines[name] = {"intercept": float(icpt), "slope": float(slope), "n": len(grp)}

    stamp = None
    if os.path.exists("PREREG_STAMP.json"):
        st = json.load(open("PREREG_STAMP.json"))
        stamp = {k: st.get(k) for k in ("network", "explorer", "signature", "manifest_sha256")}
    payload = {"title": args.title, "synthetic": synthetic, "commit": git_commit(), "stamp": stamp,
               "results": res, "events": events, "dists": dists, "lines": lines}
    blob = json.dumps(payload, default=clean).replace("</", "<\\/")
    html = TEMPLATE.replace("__TITLE__", args.title).replace("__DATA__", blob)
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(html)
    print(f"Wrote {out} ({len(html) / 1024:.0f} KB){' using SYNTHETIC data' if synthetic else ''}")


TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>__TITLE__</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Public+Sans:ital,wght@0,400;0,500;0,600;0,700;0,800;1,400&display=swap" rel="stylesheet">
<style>
:root{
  --paper:#F3F5F1; --panel:#E8ECE6; --ink:#18302B; --muted:#5B6E68; --rule:#D3DBD5; --grid:#E1E6E0;
  --live:#0B7A5C; --settled:#97A69F; --warn:#8A5A00; --bad:#A3322B; --soft:#C9D3CC;
  color-scheme:light;
  box-sizing:border-box;
  padding-top:env(safe-area-inset-top,0px);
  padding-bottom:env(safe-area-inset-bottom,0px);
}
@media (prefers-color-scheme: dark){
  :root:not([data-theme="light"]){
    --paper:#13201D; --panel:#1A2A26; --ink:#E4ECE7; --muted:#9BAEA6; --rule:#2B3D38; --grid:#21332E;
    --live:#40C79A; --settled:#6E817A; --warn:#E3A93E; --bad:#F08A80; --soft:#34483F; color-scheme:dark;
  }
}
:root[data-theme="dark"]{
  --paper:#13201D; --panel:#1A2A26; --ink:#E4ECE7; --muted:#9BAEA6; --rule:#2B3D38; --grid:#21332E;
  --live:#40C79A; --settled:#6E817A; --warn:#E3A93E; --bad:#F08A80; --soft:#34483F; color-scheme:dark;
}
html{scroll-padding-top:env(safe-area-inset-top,0px);}
*,*::before,*::after{box-sizing:inherit;}
body{margin:0;background:var(--paper);color:var(--ink);
  font-family:"Public Sans",system-ui,-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
  font-size:16px;line-height:1.55;font-variant-numeric:tabular-nums;-webkit-font-smoothing:antialiased;}
main{max-width:1080px;margin:0 auto;padding:36px 24px 80px;}
a{color:inherit}
:focus-visible{outline:3px solid var(--live);outline-offset:2px;border-radius:4px;}
.banner{border:2px solid var(--warn);color:var(--warn);font-weight:600;padding:10px 14px;border-radius:8px;
  margin:0 0 28px;max-width:72ch;}
h1{font-size:clamp(2.1rem,5vw,3.6rem);line-height:1.04;letter-spacing:-0.025em;font-weight:800;
  margin:0 0 18px;max-width:17ch;}
h2{font-size:1.45rem;line-height:1.2;letter-spacing:-0.01em;font-weight:700;margin:0 0 6px;}
.lede{color:var(--muted);margin:0 0 18px;max-width:68ch;}
section{margin-top:64px;}
.status{display:flex;flex-wrap:wrap;align-items:center;gap:10px 16px;margin:0 0 26px;color:var(--muted);}
.chip{display:inline-block;font-weight:800;font-size:.95rem;letter-spacing:.01em;padding:3px 12px;border-radius:999px;
  color:var(--paper);background:var(--settled);}
.chip.go{background:var(--live);} .chip.nogo{background:var(--muted);} .chip.na{background:var(--warn);}
.answer{font-size:clamp(1.15rem,2.3vw,1.45rem);line-height:1.45;max-width:46ch;margin:22px 0 0;}
.answer strong{font-weight:800;}
.answer .live{color:var(--live);} .answer .settled{color:var(--muted);}
.figure{position:relative;margin:0;}
.figure svg{display:block;width:100%;height:auto;overflow:visible;}
.axis text,.tick text{fill:var(--muted);font-size:12.5px;}
.tooltip{position:absolute;pointer-events:none;background:var(--ink);color:var(--paper);padding:8px 10px;border-radius:6px;
  font-size:.85rem;line-height:1.35;max-width:240px;opacity:0;transform:translate(-50%,-115%);white-space:nowrap;}
.tooltip.on{opacity:1;}
.checks{list-style:none;padding:0;margin:0;display:grid;gap:2px;max-width:760px;}
.checks li{display:grid;grid-template-columns:1.6rem 1fr auto;gap:10px;align-items:baseline;padding:10px 0;
  border-bottom:1px solid var(--rule);}
.mark{font-weight:800;font-size:1.05rem;} .mark.pass{color:var(--live);} .mark.fail{color:var(--bad);}
.checks .detail{color:var(--muted);font-size:.92rem;}
.explorer{display:grid;grid-template-columns:minmax(290px,350px) 1fr;gap:28px;align-items:start;}
.list{max-height:620px;overflow:auto;border-top:1px solid var(--rule);}
.row{display:grid;grid-template-columns:6.8rem 1fr 1fr 1fr;gap:6px;width:100%;text-align:left;background:none;border:0;
  border-bottom:1px solid var(--rule);color:var(--ink);font:inherit;font-size:.9rem;padding:8px 6px;cursor:pointer;}
.row:hover{background:var(--panel);} .row[aria-selected="true"]{background:var(--panel);box-shadow:inset 3px 0 0 var(--live);}
.row.out{color:var(--muted);} .row .n{text-align:right;}
.listhead{display:grid;grid-template-columns:6.8rem 1fr 1fr 1fr;gap:6px;padding:6px 6px;font-size:.78rem;color:var(--muted);}
.listhead span:not(:first-child){text-align:right;}
.detail h3{font-size:1.25rem;margin:0 0 4px;font-weight:700;}
.facts{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:14px 22px;margin:14px 0 24px;}
.fact .k{color:var(--muted);font-size:.82rem;} .fact .v{font-weight:700;font-size:1.08rem;}
.ladders{display:grid;grid-template-columns:1fr 1fr;gap:28px;}
.ladder h4{margin:0 0 2px;font-size:1rem;font-weight:700;} .ladder p{margin:0 0 10px;color:var(--muted);font-size:.85rem;}
.lrow{display:grid;grid-template-columns:4.2rem 1fr 3.2rem;gap:8px;align-items:center;padding:3px 0;font-size:.86rem;}
.lrow .val{color:var(--muted);} .lrow.actual .val{color:var(--ink);font-weight:800;}
.lrow.actual{box-shadow:inset 0 -2px 0 var(--ink);}
.bars{display:grid;gap:2px;} .bar{height:7px;border-radius:2px;background:var(--soft);min-width:1px;}
.bar.later{background:var(--live);} .pct{text-align:right;color:var(--muted);}
.legend{display:flex;flex-wrap:wrap;gap:6px 16px;font-size:.82rem;color:var(--muted);margin:10px 0 0;}
.sw{display:inline-block;width:12px;height:7px;border-radius:2px;margin-right:6px;vertical-align:middle;}
.tablewrap{overflow-x:auto;}
table{border-collapse:collapse;width:100%;min-width:560px;font-size:.92rem;}
th,td{padding:8px 10px;border-bottom:1px solid var(--rule);text-align:right;}
th:first-child,td:first-child{text-align:left;} th{color:var(--muted);font-weight:600;font-size:.82rem;}
.two{display:grid;grid-template-columns:1fr 1fr;gap:36px;}
.note{color:var(--muted);font-size:.9rem;max-width:68ch;}
.audit{display:grid;grid-template-columns:repeat(auto-fill,minmax(190px,1fr));gap:16px 26px;margin-top:8px;}
footer{margin-top:72px;padding-top:18px;border-top:1px solid var(--rule);color:var(--muted);font-size:.85rem;}
@media (max-width:820px){
  .explorer,.ladders,.two{grid-template-columns:1fr;}
  .list{max-height:340px;}
  main{padding:24px 16px 64px;}
}
</style>
</head>
<body>
<main>
  <div id="banner"></div>
  <h1 id="title"></h1>
  <div class="status" id="status"></div>
  <figure class="figure" id="scatterFig"><div class="tooltip" id="tip" role="status"></div></figure>
  <p class="answer" id="answer"></p>

  <section aria-labelledby="h-checks">
    <h2 id="h-checks">The five conditions for a go</h2>
    <p class="lede">All five must hold. They were fixed in the pre-registration before any real data were analysed.</p>
    <ul class="checks" id="checks"></ul>
  </section>

  <section aria-labelledby="h-explorer">
    <h2 id="h-explorer">Every release</h2>
    <p class="lede">Select a release, or a point on the chart, to see what Kalshi expected and what happened next.</p>
    <div class="explorer">
      <div>
        <div class="listhead"><span>Release</span><span>Surprise</span><span>Fed SD</span><span>S&amp;P</span></div>
        <div class="list" id="list" role="listbox" aria-label="CPI releases"></div>
      </div>
      <div class="detail" id="detail" aria-live="polite"></div>
    </div>
  </section>

  <section aria-labelledby="h-robust">
    <h2 id="h-robust">Does it hold up?</h2>
    <p class="lede">Variations reported for transparency. They never change the verdict.</p>
    <div class="tablewrap"><table id="robust"></table></div>
    <div class="two" style="margin-top:34px">
      <div><h2 style="font-size:1.1rem">Do CPI surprises move Kalshi's Fed odds more?</h2><p class="note" id="mech"></p></div>
      <div><h2 style="font-size:1.1rem">Is liveness just a volatility gauge?</h2><p class="note" id="placebo"></p></div>
    </div>
  </section>

  <section aria-labelledby="h-infl">
    <h2 id="h-infl">Releases that move the result most</h2>
    <p class="lede">How much the interaction estimate changes when each release is left out.</p>
    <figure class="figure" id="inflFig"></figure>
  </section>

  <section aria-labelledby="h-audit">
    <h2 id="h-audit">Data checks</h2>
    <div class="audit" id="audit"></div>
    <p class="note" id="excluded"></p>
  </section>

  <footer id="footer"></footer>
</main>
<script type="application/json" id="data">__DATA__</script>
<script>
(function(){
const D = JSON.parse(document.getElementById('data').textContent);
const R = D.results || {}, P = R.primary || null, EV = D.events || [];
const $ = id => document.getElementById(id);
const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const MONTHS = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
const fmtDate = s => { if(!s) return 'n/a'; const [y,m,d]=s.split('-').map(Number); return d+' '+MONTHS[m-1]+' '+y; };
const signed = (x,dg=2,suf='') => x==null||isNaN(x) ? 'n/a' : (x>0?'+':x<0?'\u2212':'')+Math.abs(x).toFixed(dg)+suf;
const num = (x,dg=3) => x==null||isNaN(x) ? 'n/a' : (x<0?'\u2212':'')+Math.abs(x).toFixed(dg);
const el = (tag, attrs={}, text) => { const e=document.createElement(tag); for(const k in attrs){ if(k==='class') e.className=attrs[k]; else e.setAttribute(k,attrs[k]); } if(text!=null) e.textContent=text; return e; };
const svgEl = (tag, attrs={}) => { const e=document.createElementNS('http://www.w3.org/2000/svg',tag); for(const k in attrs) e.setAttribute(k,attrs[k]); return e; };

// ---------- header
document.title = D.title; $('title').textContent = D.title;
if (D.synthetic) $('banner').appendChild(el('p',{class:'banner'},'These are synthetic test data generated to check the pipeline. They are not real results.'));
const st = $('status');
const v = R.verdict || 'INSUFFICIENT';
st.appendChild(el('span',{class:'chip '+(v==='GO'?'go':v==='NO-GO'?'nogo':'na')}, v==='GO'?'Go':v==='NO-GO'?'No-go':'No verdict yet'));
if (R.n) st.appendChild(el('span',{}, R.n+' CPI releases'));
if (R.date_range) st.appendChild(el('span',{}, fmtDate(R.date_range[0])+' to '+fmtDate(R.date_range[1])));

const SRC = R.open_source_counts||{};
const AT = (R.n && (SRC['09:35 level']||0)===R.n) ? '9:35' : 'the open';
const ans = $('answer');
if (P) {
  ans.innerHTML = '';
  ans.append('When the next Fed meeting was settled, a core CPI print 0.1 point hotter than Kalshi expected moved the S&P 500 by ');
  ans.appendChild(el('strong',{class:'settled'}, signed(P.sens_settled,2,'%')));
  ans.append(' by '+AT+'. When the meeting was live, it moved it by ');
  ans.appendChild(el('strong',{class:'live'}, signed(P.sens_live,2,'%')));
  ans.append('.');
} else {
  ans.textContent = R.verdict_text || 'Run sensitivity_test.py to produce results.';
}

// ---------- scatter
const sample = EV.filter(e => e.in_sample && e.surprise_core!=null && e.r_open!=null);
const med = R.liveness_median;
let selected = null;
function drawScatter(){
  const fig = $('scatterFig'); fig.querySelectorAll('svg').forEach(s=>s.remove());
  if (!sample.length) return;
  const W = Math.max(320, fig.clientWidth), H = Math.round(Math.min(520, Math.max(300, W*0.52)));
  const m = {l:56, r: W<560?18:128, t:16, b:52};
  const xs = sample.map(e=>e.surprise_core), ys = sample.map(e=>e.r_open);
  const pad = (a,b,f=0.08)=>{const d=(b-a)||1; return [a-d*f,b+d*f];};
  const [x0,x1] = pad(Math.min(...xs,0),Math.max(...xs,0)), [y0,y1] = pad(Math.min(...ys,0),Math.max(...ys,0));
  const X = x=>m.l+(x-x0)/(x1-x0)*(W-m.l-m.r), Y = y=>m.t+(y1-y)/(y1-y0)*(H-m.t-m.b);
  const svg = svgEl('svg',{viewBox:`0 0 ${W} ${H}`,role:'img','aria-label':'Scatter of S&P 500 moves against core CPI surprises, split by Fed-meeting liveness'});
  const ticks=(a,b,n)=>{const s=Math.pow(10,Math.floor(Math.log10((b-a)/n))); const st=[1,2,2.5,5,10].map(k=>k*s).find(k=>(b-a)/k<=n)||s*10; const out=[]; for(let t=Math.ceil(a/st)*st;t<=b+1e-9;t+=st) out.push(+t.toFixed(10)); return out;};
  const g = svgEl('g',{class:'tick'});
  ticks(y0,y1,6).forEach(t=>{ g.appendChild(svgEl('line',{x1:m.l,x2:W-m.r,y1:Y(t),y2:Y(t),stroke:t===0?css('--muted'):css('--grid'),'stroke-width':t===0?1.2:1}));
    const tx=svgEl('text',{x:m.l-8,y:Y(t)+4,'text-anchor':'end'}); tx.textContent=(t>0?'+':t<0?'\u2212':'')+Math.abs(t)+'%'; g.appendChild(tx);});
  ticks(x0,x1,7).forEach(t=>{ g.appendChild(svgEl('line',{y1:m.t,y2:H-m.b,x1:X(t),x2:X(t),stroke:t===0?css('--muted'):css('--grid'),'stroke-width':t===0?1.2:1}));
    const tx=svgEl('text',{x:X(t),y:H-m.b+18,'text-anchor':'middle'}); tx.textContent=(t>0?'+':t<0?'\u2212':'')+Math.abs(t).toFixed(Math.abs(t)<1?1:0); g.appendChild(tx);});
  svg.appendChild(g);
  const ax = svgEl('g',{class:'axis'});
  const xl=svgEl('text',{x:m.l+(W-m.l-m.r)/2,y:H-8,'text-anchor':'middle'}); xl.textContent= W<560 ? 'Core CPI surprise (pp)' : 'Core CPI surprise vs Kalshi\u2019s expectation (percentage points)'; ax.appendChild(xl);
  const yl=svgEl('text',{x:-(m.t+(H-m.t-m.b)/2),y:14,transform:'rotate(-90)','text-anchor':'middle'}); yl.textContent='S&P 500, prior close to '+AT+' (%)'; ax.appendChild(yl);
  svg.appendChild(ax);
  const defs=svgEl('defs'), cp=svgEl('clipPath',{id:'plotclip'});
  cp.appendChild(svgEl('rect',{x:m.l,y:m.t,width:W-m.l-m.r,height:H-m.t-m.b})); defs.appendChild(cp); svg.appendChild(defs);
  const plot=svgEl('g',{'clip-path':'url(#plotclip)'}); svg.appendChild(plot);
  const labels=[];
  [['settled','--settled','Settled meeting'],['live','--live','Live meeting']].forEach(([k,c,lab])=>{
    const L = D.lines[k]; if(!L) return;
    const ya=L.intercept+L.slope*x0, yb=L.intercept+L.slope*x1;
    plot.appendChild(svgEl('line',{x1:X(x0),y1:Y(ya),x2:X(x1),y2:Y(yb),stroke:css(c),'stroke-width':3.5,'stroke-linecap':'round'}));
    const yEnd = Math.min(Math.max(Y(yb), m.t+10), H-m.b-26);
    labels.push({y:yEnd,c,lab,slope:L.slope});
  });
  if (W>=560){ labels.sort((a,b)=>a.y-b.y); for(let i=1;i<labels.length;i++) if(labels[i].y-labels[i-1].y<34) labels[i].y=labels[i-1].y+34;
    labels.forEach(l=>{ const t=svgEl('text',{x:W-m.r+10,y:l.y+4,fill:css(l.c),'font-weight':700,'font-size':13.5}); t.textContent=l.lab; svg.appendChild(t);
      const s=svgEl('text',{x:W-m.r+10,y:l.y+20,fill:css('--muted'),'font-size':12}); s.textContent=signed(l.slope*0.1,2,'% per 0.1pp'); svg.appendChild(s);}); }
  else { [['--live','Live meeting'],['--settled','Settled meeting']].forEach(([c,lab],i)=>{ const y=m.t+12+i*18, x=W-m.r-118;
      svg.appendChild(svgEl('rect',{x,y:y-8,width:14,height:4,rx:2,fill:css(c)}));
      const t=svgEl('text',{x:x+20,y,fill:css('--muted'),'font-size':12}); t.textContent=lab; svg.appendChild(t); }); }
  const tip=$('tip');
  sample.forEach(e=>{
    const live = med!=null && e.fed_sd_t0_bp>=med;
    const cx=X(e.surprise_core), cy=Y(e.r_open);
    const c=svgEl('circle',{cx,cy,r:e.release_date===selected?8:5.5,fill:css(live?'--live':'--settled'),stroke:e.release_date===selected?css('--ink'):css('--paper'),'stroke-width':e.release_date===selected?2.5:1.5,tabindex:0,
      'aria-label':`${fmtDate(e.release_date)}: surprise ${signed(e.surprise_core,2)} points, S&P ${signed(e.r_open,2,'%')}, ${live?'live':'settled'} meeting`});
    c.style.cursor='pointer';
    const show=()=>{ tip.innerHTML=''; tip.appendChild(el('div',{style:'font-weight:700'},fmtDate(e.release_date)));
      tip.appendChild(el('div',{},`Surprise ${signed(e.surprise_core,2)} pp, S&P ${signed(e.r_open,2,'%')}`));
      tip.appendChild(el('div',{},`Fed SD ${num(e.fed_sd_t0_bp,1)} bp, ${live?'live':'settled'}`));
      tip.style.left=Math.min(Math.max(cx,110),W-110)+'px'; tip.style.top=cy+'px'; tip.classList.add('on'); };
    const hide=()=>tip.classList.remove('on');
    c.addEventListener('mouseenter',show); c.addEventListener('focus',show);
    c.addEventListener('mouseleave',hide); c.addEventListener('blur',hide);
    c.addEventListener('click',()=>select(e.release_date,true));
    c.addEventListener('keydown',ev=>{ if(ev.key==='Enter'||ev.key===' '){ev.preventDefault(); select(e.release_date,true);} });
    plot.appendChild(c);
  });
  $('scatterFig').appendChild(svg);
}

// ---------- checks
(R.checks||[]).forEach(c=>{ const li=el('li');
  li.appendChild(el('span',{class:'mark '+(c.passed?'pass':'fail'),'aria-label':c.passed?'Passed':'Failed'},c.passed?'\u2713':'\u2717'));
  li.appendChild(el('span',{},c.name)); li.appendChild(el('span',{class:'detail'},c.detail)); $('checks').appendChild(li); });
if(!(R.checks||[]).length) $('checks').appendChild(el('li',{},'No checks yet: the sample is too small for a verdict.'));

// ---------- explorer
const list=$('list');
const ordered=[...EV].sort((a,b)=>a.release_date<b.release_date?1:-1);
ordered.forEach(e=>{
  const b=el('button',{class:'row'+(e.in_sample?'':' out'),role:'option','aria-selected':'false','data-date':e.release_date});
  b.appendChild(el('span',{},fmtDate(e.release_date)));
  b.appendChild(el('span',{class:'n'},signed(e.surprise_core,2)));
  b.appendChild(el('span',{class:'n'},num(e.fed_sd_t0_bp,1)));
  b.appendChild(el('span',{class:'n'},signed(e.r_open,2,'%')));
  b.addEventListener('click',()=>select(e.release_date,false));
  list.appendChild(b);
});
function ladder(title, sub, earlier, later, laterLabel, earlierLabel, actual, unit, dp){
  const box=el('div',{class:'ladder'}); box.appendChild(el('h4',{},title)); box.appendChild(el('p',{},sub));
  if(!earlier && !later){ box.appendChild(el('p',{},'No usable ladder for this release.')); return box; }
  const vals=new Set(); [earlier,later].forEach(d=>d&&d.values.forEach(x=>vals.add(+x.toFixed(4))));
  const sorted=[...vals].sort((a,b)=>b-a);
  const pmap=d=>{const o={}; if(d) d.values.forEach((x,i)=>o[+x.toFixed(4)]=d.probs[i]); return o;};
  const pe=pmap(earlier), pl=pmap(later);
  const mx=Math.max(0.0001,...Object.values(pe),...Object.values(pl));
  sorted.forEach(x=>{
    const isAct = actual!=null && Math.abs(x-actual)<1e-6;
    const row=el('div',{class:'lrow'+(isAct?' actual':'')});
    row.appendChild(el('span',{class:'val'},x.toFixed(dp)+unit+(isAct?' actual':'')));
    const bars=el('div',{class:'bars'});
    const b1=el('div',{class:'bar'}); b1.style.width=((pe[x]||0)/mx*100)+'%';
    const b2=el('div',{class:'bar later'}); b2.style.width=((pl[x]||0)/mx*100)+'%';
    bars.appendChild(b1); bars.appendChild(b2); row.appendChild(bars);
    row.appendChild(el('span',{class:'pct'},Math.round(((pl[x]??pe[x])||0)*100)+'%'));
    box.appendChild(row);
  });
  const lg=el('div',{class:'legend'});
  const s1=el('span'); s1.appendChild(el('span',{class:'sw',style:'background:var(--soft)'})); s1.append(earlierLabel);
  const s2=el('span'); s2.appendChild(el('span',{class:'sw',style:'background:var(--live)'})); s2.append(laterLabel);
  lg.appendChild(s1); lg.appendChild(s2); box.appendChild(lg);
  return box;
}
function select(date, scroll){
  selected=date;
  list.querySelectorAll('.row').forEach(r=>r.setAttribute('aria-selected', r.dataset.date===date?'true':'false'));
  const row=list.querySelector(`[data-date="${date}"]`); if(row && scroll) row.scrollIntoView({block:'nearest'});
  const e=EV.find(x=>x.release_date===date); const d=(D.dists||{})[date]||{};
  const box=$('detail'); box.innerHTML='';
  box.appendChild(el('h3',{},'CPI release, '+fmtDate(date)));
  if(!e.in_sample) box.appendChild(el('p',{class:'note'},'Not in the test sample: '+(e.excluded_reason||'excluded')+'.'));
  const facts=el('div',{class:'facts'});
  [['Core CPI print', e.core_actual==null?'n/a':e.core_actual.toFixed(1)+'%'],
   ['Kalshi expected at 8:25', e.core_mean_pre==null?'n/a':e.core_mean_pre.toFixed(2)+'%'],
   ['Surprise', signed(e.surprise_core,2,' pp')],
   [e.r_open_source==='09:35 level'?'S&P 500 to 9:35':'S&P 500 to the open', signed(e.r_open,2,'%')],
   ['Next Fed decision', e.fed_meeting_date?fmtDate(e.fed_meeting_date)+(e.days_to_meeting!=null?` (${e.days_to_meeting} days)`:''):'n/a'],
   ['Fed odds spread (SD)', num(e.fed_sd_t0_bp,1)+' bp'],
   ['Fed odds moved by 10:00', signed(e.d_fed_mean_bp,1,' bp')],
   ['VIX the day before', num(e.vix_prev,1)]].forEach(([k,vv])=>{ const f=el('div',{class:'fact'}); f.appendChild(el('div',{class:'k'},k)); f.appendChild(el('div',{class:'v'},vv)); facts.appendChild(f); });
  box.appendChild(facts);
  const lad=el('div',{class:'ladders'});
  const core=d.cpi_core||{};
  lad.appendChild(ladder('Kalshi\u2019s core CPI forecast','Probability of each month-over-month print',core.t0,core.pre,'Release day, 8:25 am','Day before, 3:45 pm',e.core_actual,'%',1));
  const fed=d.fed||{};
  lad.appendChild(ladder('Kalshi\u2019s odds for the next Fed meeting','Upper bound of the target range',fed.t0,fed.post,'Release day, 10:00 am','Day before, 3:45 pm',null,'%',2));
  box.appendChild(lad);
  drawScatter();
}

// ---------- robustness, mechanism, placebo
const rt=$('robust');
const head=el('tr'); ['Variant','Releases','Interaction','Std. error','One-sided p','Agrees'].forEach(h=>head.appendChild(el('th',{},h)));
rt.appendChild(head);
(R.robustness||[]).forEach(r=>{ const tr=el('tr');
  const agrees = r.c==null ? null : (r.direction==='neg' ? r.c<0 : r.c>0);
  [r.label, r.n||'n/a', num(r.c), num(r.se), num(r.p), agrees==null?'n/a':(agrees?'\u2713':'\u2717')].forEach((x,i)=>tr.appendChild(el('td',i===5&&agrees!=null?{style:'color:'+(agrees?'var(--live)':'var(--bad)')+';font-weight:800'}:{},String(x))));
  rt.appendChild(tr); });
const M=R.mechanism; $('mech').textContent = M ? `Across ${M.n} releases, a +0.1 point surprise moved Kalshi\u2019s expected Fed rate by ${signed(M.bp_per_tenth,2,' bp')} on average between 8:25 and 10:00. The extra move per standard deviation of liveness was ${num(M.c)} (one-sided p = ${num(M.p)}). A positive value supports the mechanism.` : 'Not available: the 10:00 Fed snapshots are missing.';
const PL=R.placebo; $('placebo').textContent = PL ? `Regressing the average absolute S&P move over the five ordinary days before each release on liveness and VIX gives a liveness coefficient of ${num(PL.coef)} (standard error ${num(PL.se)}). Near zero means liveness is not simply tracking general volatility.` : 'Not available.';

// ---------- influence
function drawInfl(){
  const fig=$('inflFig'); fig.innerHTML='';
  const L=(R.loo||[]).slice(0,10); if(!L.length) return;
  const W=Math.max(320,fig.clientWidth), rowH=28, H=L.length*rowH+30, ml=110, mr=60;
  const mx=Math.max(...L.map(d=>Math.abs(d.shift)),1e-9);
  const X=x=>ml+(x+mx)/(2*mx)*(W-ml-mr);
  const svg=svgEl('svg',{viewBox:`0 0 ${W} ${H}`,role:'img','aria-label':'Change in the interaction estimate when each release is left out'});
  svg.appendChild(svgEl('line',{x1:X(0),x2:X(0),y1:4,y2:H-20,stroke:css('--muted')}));
  L.forEach((d,i)=>{ const y=10+i*rowH;
    const t=svgEl('text',{x:ml-10,y:y+12,'text-anchor':'end',fill:css('--muted'),'font-size':12.5}); t.textContent=fmtDate(d.release_date); svg.appendChild(t);
    const a=X(Math.min(0,d.shift)), b=X(Math.max(0,d.shift));
    svg.appendChild(svgEl('rect',{x:a,y:y+2,width:Math.max(1,b-a),height:14,rx:2,fill:css('--settled')}));
    const v=svgEl('text',{x:d.shift<0?a-6:b+6,y:y+13,'text-anchor':d.shift<0?'end':'start',fill:css('--ink'),'font-size':12}); v.textContent=signed(d.shift,2); svg.appendChild(v); });
  const cap=svgEl('text',{x:X(0),y:H-4,'text-anchor':'middle',fill:css('--muted'),'font-size':12}); cap.textContent='Estimate with the release minus estimate without it'; svg.appendChild(cap);
  fig.appendChild(svg);
}

// ---------- audit
const audit=$('audit');
const ins=EV.filter(e=>e.in_sample);
const medOf=a=>{const s=[...a].filter(x=>x!=null).sort((x,y)=>x-y); return s.length?s[Math.floor(s.length/2)]:null;};
const src=R.open_source_counts||{};
[['Releases found',EV.length],['Used in the test',ins.length],
 ['Measured at 9:35',(src['09:35 level']||0)+' of '+ins.length],
 ['Median CPI strikes',medOf(ins.map(e=>e.n_core_strikes_t0))],
 ['Median Fed strikes',medOf(ins.map(e=>e.n_fed_strikes_t0))],
 ['Fed decision on CPI day',ins.filter(e=>e.fomc_same_day).length]].forEach(([k,vv])=>{ const f=el('div',{class:'fact'}); f.appendChild(el('div',{class:'k'},k)); f.appendChild(el('div',{class:'v'},vv==null?'n/a':String(vv))); audit.appendChild(f); });
const ex=EV.filter(e=>!e.in_sample);
$('excluded').textContent = ex.length ? 'Excluded: '+ex.map(e=>fmtDate(e.release_date)+' ('+e.excluded_reason+')').join('; ')+'.' : 'No releases were excluded.';

// ---------- footer
const ft=$('footer');
ft.appendChild(el('div',{},'Generated '+(R.generated_at? new Date(R.generated_at).toLocaleString() : 'n/a')+(D.commit?', code at commit '+D.commit:'')+'.'));
if(D.stamp && D.stamp.explorer){ const d=el('div'); d.append('Pre-registration timestamped on Solana '+(D.stamp.network||'')+': ');
  const a=el('a',{href:D.stamp.explorer,target:'_blank',rel:'noopener'},'view the transaction'); d.appendChild(a); d.append('.'); ft.appendChild(d); }
ft.appendChild(el('div',{},'Primary test: S&P 500 move on core CPI surprise, its interaction with Fed-meeting liveness, liveness and VIX, with HC3 errors. See PREREGISTRATION.md.'));

// ---------- go
const first=(ordered.find(e=>e.in_sample)||ordered[0]);
if(first) select(first.release_date,false); else drawScatter();
drawInfl();
let t; window.addEventListener('resize',()=>{clearTimeout(t); t=setTimeout(()=>{drawScatter(); drawInfl();},120);});
window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change',()=>{drawScatter(); drawInfl();});
})();
</script>
</body>
</html>
"""

if __name__ == "__main__":
    main()
