#!/usr/bin/env python3
"""
미장 테마 스캐너 — 자기완결형 HTML 대시보드 생성기

탭으로 테마를 열고, 종목을 누르면 차트가 뜨는 단일 HTML 파일을 만든다.
외부 요청 없이 동작하도록 시세 데이터를 파일 안에 함께 심는다.

사용법:
  python build_dashboard.py                      # 실데이터 (yfinance 필요)
  python build_dashboard.py --demo               # 샘플 데이터 (레이아웃 확인용)
  python build_dashboard.py -o docs/index.html
"""
import argparse
import json
import math
import random
import sys
import time
from datetime import datetime, timedelta, timezone

import pandas as pd

from stock_report import US_THEMES, THEME_GROUPS, get_name

KST = timezone(timedelta(hours=9))
SPINE = "^GSPC"      # 거래일 기준선
DAYS = 252           # 담을 거래일 수


# ───────────────────────── 데이터 수집 ─────────────────────────

def _series(raw, sym, field):
    try:
        if isinstance(raw.columns, pd.MultiIndex):
            return raw[(sym, field)].dropna()
        return raw[field].dropna()
    except Exception:
        return pd.Series(dtype=float)


def fetch_real(symbols, chunk_size=80):
    """yfinance로 종목별 종가/거래량 시계열 수집. 거래일 축은 S&P500 기준."""
    import yfinance as yf

    spine_raw = yf.download(SPINE, period="1y", interval="1d",
                            progress=False, auto_adjust=False)
    if spine_raw is None or spine_raw.empty:
        raise RuntimeError("거래일 기준선(^GSPC) 데이터를 받지 못했습니다")
    spine = _series(spine_raw, SPINE, "Close").index[-DAYS:]

    out = {}
    uniq = sorted(set(symbols))
    print(f"  {len(uniq)}개 종목 수집 시작 (거래일 {len(spine)}일)", file=sys.stderr)

    for start in range(0, len(uniq), chunk_size):
        chunk = uniq[start:start + chunk_size]
        raw = None
        for attempt in range(3):
            try:
                raw = yf.download(chunk, period="1y", interval="1d", group_by="ticker",
                                  progress=False, threads=True, auto_adjust=False)
                if raw is not None and not raw.empty:
                    break
            except Exception:
                pass
            time.sleep(2 * (attempt + 1))
        if raw is None or raw.empty:
            print(f"  ... {start+1}-{start+len(chunk)} 실패, 건너뜀", file=sys.stderr)
            continue

        for sym in chunk:
            closes = _series(raw, sym, "Close")
            if len(closes) < 30:
                continue
            opens = _series(raw, sym, "Open")
            highs = _series(raw, sym, "High")
            lows = _series(raw, sym, "Low")
            vols = _series(raw, sym, "Volume")

            kc = closes.reindex(spine).ffill()
            if kc.dropna().empty:
                continue
            ko = opens.reindex(spine).ffill()
            kh = highs.reindex(spine).ffill()
            kl = lows.reindex(spine).ffill()
            kv = vols.reindex(spine).ffill()

            k, od, hd, ld, v = [], [], [], [], []
            for i in range(len(spine)):
                c = kc.iloc[i]
                if pd.isna(c):
                    k.append(None); od.append(0); hd.append(0); ld.append(0); v.append(0)
                    continue
                c = float(c)
                o = float(ko.iloc[i]) if not pd.isna(ko.iloc[i]) else c
                h = float(kh.iloc[i]) if not pd.isna(kh.iloc[i]) else max(o, c)
                l = float(kl.iloc[i]) if not pd.isna(kl.iloc[i]) else min(o, c)
                k.append(round(c, 2))
                od.append(round(o - c, 2))
                hd.append(round(max(h, o, c) - c, 2))
                ld.append(round(min(l, o, c) - c, 2))
                vv = kv.iloc[i]
                v.append(0 if pd.isna(vv) else int(round(float(vv) / 1000)))

            out[sym] = dict(
                k=k, od=od, hd=hd, ld=ld, v=v,
                h52=float(highs.max()) if len(highs) else max(x for x in k if x is not None),
                l52=float(lows.min()) if len(lows) else min(x for x in k if x is not None),
            )
        print(f"  ... {min(start+chunk_size, len(uniq))}/{len(uniq)}", file=sys.stderr)

    if not out:
        raise RuntimeError("수집된 종목이 없습니다")
    return out, [d.strftime("%Y-%m-%d") for d in spine]


def fetch_demo(symbols):
    """레이아웃 확인용 합성 시계열. 실제 시세가 아니다."""
    rng = random.Random(20260808)
    today = datetime.now(KST).date()
    dates, d = [], today - timedelta(days=1)
    while len(dates) < DAYS:
        if d.weekday() < 5:
            dates.append(d.strftime("%Y-%m-%d"))
        d -= timedelta(days=1)
    dates.reverse()

    theme_drift = {t: rng.gauss(0.0004, 0.0016) for t in US_THEMES}
    sym_theme = {}
    for t, syms in US_THEMES.items():
        for s in syms:
            sym_theme.setdefault(s, t)

    out = {}
    for sym in sorted(set(symbols)):
        drift = theme_drift[sym_theme[sym]]
        vol = rng.uniform(0.012, 0.045)
        close = rng.uniform(9, 520)
        base_vol = rng.uniform(4e5, 4e7)
        ks, od, hd, ld, vs = [], [], [], [], []
        hi_all, lo_all = -1e9, 1e9
        for _ in range(DAYS):
            prev = close
            op = max(0.6, prev * (1 + rng.gauss(0, vol * 0.35)))
            close = max(0.6, prev * (1 + rng.gauss(drift, vol)))
            wick = max(op, close) * rng.uniform(0.002, 0.02)
            hi = max(op, close) + wick * rng.uniform(0.2, 1.0)
            lo = min(op, close) - wick * rng.uniform(0.2, 1.0)
            ks.append(round(close, 2))
            od.append(round(op - close, 2))
            hd.append(round(hi - close, 2))
            ld.append(round(lo - close, 2))
            vs.append(int(base_vol * rng.uniform(0.45, 2.3) / 1000))
            hi_all, lo_all = max(hi_all, hi), min(lo_all, lo)
        out[sym] = dict(k=ks, od=od, hd=hd, ld=ld, v=vs,
                        h52=hi_all * rng.uniform(1.0, 1.05),
                        l52=lo_all * rng.uniform(0.95, 1.0))
    return out, dates


# ───────────────────────── 집계 ─────────────────────────

def build_payload(series, dates, demo):
    stocks, sym_theme = {}, {}
    for theme, syms in US_THEMES.items():
        for s in syms:
            sym_theme.setdefault(s, theme)

    for sym, d in series.items():
        k = [x for x in d["k"] if x is not None]
        if len(k) < 5:
            continue
        price, prev = k[-1], k[-2]
        c5 = k[-6] if len(k) >= 6 else prev
        c20 = k[-21] if len(k) >= 21 else k[0]
        vs = d["v"][-21:-1]
        avg_v = sum(vs) / len(vs) if vs else 0
        h52 = max(d["h52"], price)
        stocks[sym] = dict(
            n=get_name(sym), t=sym_theme.get(sym, "-"),
            p=round(price, 2),
            c=round((price / prev - 1) * 100, 2) if prev else 0.0,
            c5=round((price / c5 - 1) * 100, 2) if c5 else 0.0,
            c20=round((price / c20 - 1) * 100, 2) if c20 else 0.0,
            h=round(h52, 2), l=round(d["l52"], 2),
            ph=round(price / h52 * 100, 1) if h52 else 0.0,
            vr=round(d["v"][-1] / avg_v, 2) if avg_v else 1.0,
            k=d["k"], od=d["od"], hd=d["hd"], ld=d["ld"], v=d["v"],
        )

    themes = {}
    for theme, syms in US_THEMES.items():
        have = [s for s in syms if s in stocks]
        if not have:
            continue
        rows = [stocks[s] for s in have]
        themes[theme] = dict(
            syms=sorted(have, key=lambda s: stocks[s]["c"], reverse=True),
            avg=round(sum(r["c"] for r in rows) / len(rows), 2),
            avg5=round(sum(r["c5"] for r in rows) / len(rows), 2),
            avg20=round(sum(r["c20"] for r in rows) / len(rows), 2),
            up=sum(1 for r in rows if r["c"] > 0),
            n=len(rows),
            near=sum(1 for r in rows if r["ph"] >= 98),
            lead=max(have, key=lambda s: stocks[s]["c"]),
        )

    groups = {g: [t for t in ts if t in themes] for g, ts in THEME_GROUPS.items()}
    groups = {g: ts for g, ts in groups.items() if ts}

    now = datetime.now(KST)
    return dict(
        demo=demo, dates=dates, asof=dates[-1] if dates else "",
        generated=now.strftime("%Y-%m-%d %H:%M KST"),
        stocks=stocks, themes=themes, groups=groups,
    )


# ───────────────────────── 렌더링 ─────────────────────────

PAGE = r"""<title>미장 테마 스캐너</title>
<style>
:root{
  --bg:#eceff4; --panel:#ffffff; --panel-2:#f5f7fa; --panel-3:#eaeef4;
  --ink:#141821; --ink-2:#48525f; --ink-3:#78838f;
  --line:#d3dae3; --line-2:#e4e9f0;
  --up:#d0342c; --down:#1f5ed0; --flat:#78838f;
  --gold:#9a6f10; --gold-bg:#f6ecd0; --gold-line:#c99b28;
  --shadow:0 1px 2px rgba(18,26,42,.06), 0 10px 28px -14px rgba(18,26,42,.22);
  --sans:'Apple SD Gothic Neo','Pretendard','Malgun Gothic','Noto Sans KR',system-ui,-apple-system,'Segoe UI',sans-serif;
  --mono:ui-monospace,'SF Mono',SFMono-Regular,'JetBrains Mono',Menlo,Consolas,'Liberation Mono',monospace;
}
@media (prefers-color-scheme:dark){
  :root:not([data-theme="light"]){
    --bg:#0c1016; --panel:#141a22; --panel-2:#1a212b; --panel-3:#212a35;
    --ink:#e6ebf3; --ink-2:#a4aebd; --ink-3:#6e7887;
    --line:#242d39; --line-2:#1c232c;
    --up:#ff5b46; --down:#5c9dff; --flat:#6e7887;
    --gold:#e2ac36; --gold-bg:#33280f; --gold-line:#c9962a;
    --shadow:0 1px 2px rgba(0,0,0,.5), 0 12px 32px -16px rgba(0,0,0,.7);
  }
}
:root[data-theme="dark"]{
  --bg:#0c1016; --panel:#141a22; --panel-2:#1a212b; --panel-3:#212a35;
  --ink:#e6ebf3; --ink-2:#a4aebd; --ink-3:#6e7887;
  --line:#242d39; --line-2:#1c232c;
  --up:#ff5b46; --down:#5c9dff; --flat:#6e7887;
  --gold:#e2ac36; --gold-bg:#33280f; --gold-line:#c9962a;
  --shadow:0 1px 2px rgba(0,0,0,.5), 0 12px 32px -16px rgba(0,0,0,.7);
}
*{box-sizing:border-box}
body{
  margin:0; background:var(--bg); color:var(--ink);
  font-family:var(--sans); font-size:14px; line-height:1.5;
  -webkit-font-smoothing:antialiased;
}
.wrap{max-width:1440px; margin:0 auto; padding:0 20px 64px}

/* 헤더 */
.head{
  position:sticky; top:0; z-index:30; background:var(--bg);
  padding:20px 0 0; border-bottom:1px solid var(--line);
}
.head-in{display:flex; flex-wrap:wrap; align-items:flex-end; gap:16px 24px}
.brand h1{
  margin:0; font-size:22px; font-weight:800; letter-spacing:-.02em;
  text-wrap:balance;
}
.eyebrow{
  font-family:var(--mono); font-size:10.5px; font-weight:600;
  letter-spacing:.14em; text-transform:uppercase; color:var(--ink-3);
  margin:0 0 3px;
}
.brand .sub{margin:2px 0 0; color:var(--ink-2); font-size:12.5px;
  font-family:var(--mono); font-variant-numeric:tabular-nums}
.head-tools{margin-left:auto; display:flex; gap:8px; align-items:center}
.search{
  display:flex; align-items:center; gap:7px; background:var(--panel);
  border:1px solid var(--line); border-radius:7px; padding:7px 10px;
  min-width:210px; box-shadow:var(--shadow);
}
.search svg{flex:none; color:var(--ink-3)}
.search input{
  border:0; background:none; color:var(--ink); font-family:var(--sans);
  font-size:13px; width:100%; outline:none;
}
.search input::placeholder{color:var(--ink-3)}

/* 배너 */
.banner{
  margin:16px 0 0; padding:11px 14px; border-radius:8px;
  background:var(--gold-bg); border:1px solid var(--gold-line);
  color:var(--gold); font-size:12.5px; font-weight:600;
  display:flex; gap:9px; align-items:flex-start;
}
.banner b{font-weight:800}
.banner span{color:var(--ink-2); font-weight:500}

/* 탭 */
.tabs{
  display:flex; gap:2px; overflow-x:auto; margin-top:14px;
  scrollbar-width:none;
}
.tabs::-webkit-scrollbar{display:none}
.tab{
  flex:none; border:0; background:none; cursor:pointer; color:var(--ink-2);
  font-family:var(--sans); font-size:13.5px; font-weight:600;
  padding:9px 13px 11px; border-bottom:2px solid transparent;
  white-space:nowrap; border-radius:5px 5px 0 0;
}
.tab:hover{color:var(--ink); background:var(--panel-2)}
.tab[aria-selected="true"]{color:var(--ink); border-bottom-color:var(--ink)}
.tab:focus-visible{outline:2px solid var(--gold-line); outline-offset:-2px}

/* 테마 칩 */
.chips{
  display:flex; flex-wrap:wrap; gap:6px; padding:16px 0 4px;
}
.chip{
  border:1px solid var(--line); background:var(--panel); cursor:pointer;
  border-radius:20px; padding:6px 12px; font-family:var(--sans);
  font-size:12.5px; font-weight:600; color:var(--ink-2);
  display:inline-flex; gap:7px; align-items:baseline;
}
.chip:hover{border-color:var(--ink-3); color:var(--ink)}
.chip[aria-selected="true"]{
  background:var(--ink); border-color:var(--ink); color:var(--bg);
}
.chip[aria-selected="true"] .pct{color:var(--bg); opacity:.92}
.chip:focus-visible{outline:2px solid var(--gold-line); outline-offset:2px}
.chip .pct{font-family:var(--mono); font-variant-numeric:tabular-nums; font-size:11.5px}

/* 레이아웃 */
.cols{display:grid; grid-template-columns:minmax(0,1.32fr) minmax(0,1fr);
  gap:18px; margin-top:12px; align-items:start}
@media (max-width:1000px){.cols{grid-template-columns:1fr}}
.card{
  background:var(--panel); border:1px solid var(--line);
  border-radius:11px; box-shadow:var(--shadow); overflow:hidden;
}
.card-head{
  padding:13px 16px; border-bottom:1px solid var(--line-2);
  display:flex; align-items:baseline; gap:12px; flex-wrap:wrap;
}
.card-head h2{margin:0; font-size:15px; font-weight:800; letter-spacing:-.01em}
.card-head .meta{
  margin-left:auto; font-family:var(--mono); font-size:11.5px;
  color:var(--ink-3); font-variant-numeric:tabular-nums;
}

/* 표 */
.t-scroll{overflow-x:auto}
table{width:100%; border-collapse:collapse; font-variant-numeric:tabular-nums}
th{
  font-family:var(--mono); font-size:10px; font-weight:700;
  letter-spacing:.1em; text-transform:uppercase; color:var(--ink-3);
  text-align:right; padding:9px 10px; border-bottom:1px solid var(--line-2);
  background:var(--panel-2); white-space:nowrap; cursor:pointer;
  position:sticky; top:0;
}
th:first-child, th.l{text-align:left}
th:hover{color:var(--ink)}
th .ar{opacity:.5; font-size:9px}
td{
  padding:8px 10px; text-align:right; border-bottom:1px solid var(--line-2);
  white-space:nowrap; font-size:13px;
}
td:first-child, td.l{text-align:left}
tbody tr{cursor:pointer}
tbody tr:hover{background:var(--panel-2)}
tbody tr[aria-selected="true"]{background:var(--panel-3)}
tbody tr:focus-visible{outline:2px solid var(--gold-line); outline-offset:-2px}
tbody tr:last-child td{border-bottom:0}
.tk{font-family:var(--mono); font-weight:700; font-size:12.5px}
.nm{color:var(--ink-2); font-size:12.5px}
.num{font-family:var(--mono); font-size:12.5px}
.up{color:var(--up); font-weight:700}
.down{color:var(--down); font-weight:700}
.flat{color:var(--flat)}
.star{color:var(--gold); font-size:11px}
.bar-cell{width:74px}
.bar{height:5px; border-radius:3px; background:var(--panel-3); overflow:hidden; min-width:44px}
.bar i{display:block; height:100%; border-radius:3px; background:var(--gold-line)}

/* 차트 */
.chart-wrap{padding:14px 16px 18px}
.chart-hd{display:flex; align-items:flex-start; gap:14px; flex-wrap:wrap; margin-bottom:10px}
.chart-hd .who h3{margin:0; font-size:17px; font-weight:800; letter-spacing:-.01em}
.chart-hd .who p{margin:2px 0 0; color:var(--ink-3); font-size:12px; font-family:var(--mono)}
.chart-hd .px{margin-left:auto; text-align:right}
.chart-hd .px .p{font-family:var(--mono); font-size:21px; font-weight:800; font-variant-numeric:tabular-nums}
.chart-hd .px .c{font-family:var(--mono); font-size:13px; font-weight:700; font-variant-numeric:tabular-nums}
.ranges{display:flex; gap:4px; margin:0 0 10px}
.rg{
  border:1px solid var(--line); background:var(--panel); cursor:pointer;
  border-radius:6px; padding:4px 10px; font-family:var(--mono);
  font-size:11px; font-weight:700; color:var(--ink-2);
}
.rg:hover{color:var(--ink); border-color:var(--ink-3)}
.rg[aria-selected="true"]{background:var(--ink); border-color:var(--ink); color:var(--bg)}
.rg:focus-visible{outline:2px solid var(--gold-line); outline-offset:2px}
.cv-box{position:relative; width:100%}
canvas{display:block; width:100%; height:auto; touch-action:none}
.tip{
  position:absolute; pointer-events:none; opacity:0; transition:opacity .1s;
  background:var(--panel); color:var(--ink); border:1px solid var(--line);
  border-radius:6px; box-shadow:var(--shadow);
  padding:6px 9px; font-family:var(--mono); font-size:11px; line-height:1.5;
  font-variant-numeric:tabular-nums; white-space:nowrap; z-index:5;
}
.tip b{font-weight:800}
.stats{
  display:grid; grid-template-columns:repeat(auto-fit,minmax(88px,1fr));
  gap:1px; margin-top:14px; background:var(--line-2);
  border:1px solid var(--line-2); border-radius:8px; overflow:hidden;
}
.stat{background:var(--panel); padding:9px 11px}
.stat dt{
  font-family:var(--mono); font-size:9.5px; font-weight:700;
  letter-spacing:.1em; text-transform:uppercase; color:var(--ink-3); margin:0;
}
.stat dd{margin:3px 0 0; font-family:var(--mono); font-size:13.5px;
  font-weight:700; font-variant-numeric:tabular-nums}
.empty{padding:52px 20px; text-align:center; color:var(--ink-3); font-size:13px}
.empty p{margin:0}
.empty .k{font-family:var(--mono); font-size:11.5px; margin-top:7px; color:var(--ink-3)}

/* 요약 */
.sum-grid{display:grid; grid-template-columns:repeat(auto-fit,minmax(320px,1fr)); gap:18px}
.rank{padding:6px 0}
.rank-row{
  display:grid; grid-template-columns:22px 1fr 62px 58px; gap:10px;
  align-items:center; padding:7px 16px; border:0; background:none;
  width:100%; cursor:pointer; text-align:left; font-family:var(--sans);
  color:var(--ink); border-bottom:1px solid var(--line-2);
}
.rank-row:last-child{border-bottom:0}
.rank-row:hover{background:var(--panel-2)}
.rank-row:focus-visible{outline:2px solid var(--gold-line); outline-offset:-2px}
.rank-row .no{font-family:var(--mono); font-size:11px; color:var(--ink-3)}
.rank-row .nmx{font-size:13px; font-weight:600; overflow:hidden; text-overflow:ellipsis; white-space:nowrap}
.rank-row .nmx em{display:block; font-style:normal; font-size:11px; color:var(--ink-3);
  font-family:var(--mono); overflow:hidden; text-overflow:ellipsis}
.rank-row .v{font-family:var(--mono); font-size:13px; font-weight:700; text-align:right;
  font-variant-numeric:tabular-nums}
.rank-row .track{height:6px; border-radius:3px; background:var(--panel-3); position:relative; overflow:hidden}
.rank-row .track i{position:absolute; top:0; bottom:0; border-radius:3px}
.hi-grid{
  display:grid; grid-template-columns:repeat(auto-fill,minmax(196px,1fr));
  gap:1px; background:var(--line-2);
}
.hi{
  background:var(--panel); border:0; cursor:pointer; text-align:left;
  padding:10px 13px; font-family:var(--sans); color:var(--ink);
  display:flex; flex-direction:column; gap:2px;
}
.hi:hover{background:var(--panel-2)}
.hi:focus-visible{outline:2px solid var(--gold-line); outline-offset:-2px}
.hi .r1{display:flex; align-items:baseline; gap:7px}
.hi .r2{display:flex; align-items:baseline; gap:8px; font-family:var(--mono); font-size:11.5px}
.hi .th{color:var(--ink-3); font-size:10.5px; font-family:var(--mono);
  overflow:hidden; text-overflow:ellipsis; white-space:nowrap}
.note{
  margin-top:20px; color:var(--ink-3); font-size:12px; line-height:1.65;
  border-top:1px solid var(--line); padding-top:16px;
}
.note b{color:var(--ink-2)}
.legend{display:flex; gap:16px; flex-wrap:wrap; margin-bottom:8px;
  font-family:var(--mono); font-size:11px; color:var(--ink-3)}
@media (prefers-reduced-motion:reduce){*{transition:none!important; animation:none!important}}
</style>

<div class="wrap">
  <header class="head">
    <div class="head-in">
      <div class="brand">
        <p class="eyebrow">US Theme Scanner</p>
        <h1>미장 테마 스캐너</h1>
        <p class="sub" id="sub"></p>
      </div>
      <div class="head-tools">
        <label class="search">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor"
               stroke-width="2.4" aria-hidden="true">
            <circle cx="11" cy="11" r="7"></circle><path d="M20 20l-3.6-3.6"></path>
          </svg>
          <input id="q" type="search" placeholder="종목 검색 (MU, 엔비디아…)"
                 autocomplete="off" aria-label="종목 검색">
        </label>
      </div>
    </div>
    <div class="tabs" role="tablist" aria-label="테마 그룹" id="tabs"></div>
  </header>

  <div id="banner"></div>
  <div class="chips" role="tablist" aria-label="세부 테마" id="chips"></div>
  <div id="view"></div>

  <p class="note" id="note"></p>
</div>

<script type="application/json" id="payload">__DATA__</script>
<script>
(function(){
"use strict";
var D = JSON.parse(document.getElementById("payload").textContent);
var S = D.stocks, T = D.themes, G = D.groups, DATES = D.dates;
var GROUPS = Object.keys(G);
var state = {group:"요약", theme:null, sym:null, range:126, sort:"c", dir:-1};

var $ = function(id){ return document.getElementById(id); };
var esc = function(s){ return String(s).replace(/[&<>"]/g, function(c){
  return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]; }); };
var cls = function(v){ return v > 0 ? "up" : v < 0 ? "down" : "flat"; };
var sgn = function(v, d){ return (v > 0 ? "+" : "") + v.toFixed(d === undefined ? 2 : d) + "%"; };
var money = function(v){ return "$" + v.toLocaleString("en-US",
  {minimumFractionDigits:2, maximumFractionDigits:2}); };

/* ── 헤더 ── */
var nStocks = Object.keys(S).length, nThemes = Object.keys(T).length;
$("sub").textContent = DATES.length
  ? D.asof + " 종가 기준 · " + nStocks + "종목 · " + nThemes + "테마"
  : "데이터 없음";

if (D.demo) {
  $("banner").innerHTML = '<div class="banner"><b>샘플 데이터</b>'
    + '<span>화면 구성을 보기 위한 가상 수치입니다. 실제 시세가 아니며 '
    + '투자 판단에 사용할 수 없습니다.</span></div>';
}

$("note").innerHTML = '<b>★</b> 52주 고가 대비 98% 이상 (신고가권) · '
  + '<b>◆</b> 95% 이상 · <b>거래량</b>은 20일 평균 대비 배수. '
  + '테마 등락률은 소속 종목 등락률의 단순 평균입니다. '
  + '차트는 일봉이며 <b>양봉(종가≥시가)은 빨강</b>, <b>음봉은 파랑</b>, '
  + '그 아래는 거래량입니다. 봉에 커서를 올리면 시·고·저·종가가 나옵니다.<br>'
  + '생성 시각 ' + esc(D.generated) + ' · 자동 생성 자료이며 투자 권유가 아닙니다.';

/* ── 탭 ── */
var tabs = ["요약"].concat(GROUPS);
$("tabs").innerHTML = tabs.map(function(g){
  return '<button class="tab" role="tab" data-g="' + esc(g) + '" aria-selected="false">'
    + esc(g) + '</button>';
}).join("");

/* ── 차트 ── */
var cv = null, ctx = null, cvSym = null, cvPts = null, hoverI = -1;

function themeColors(){
  var s = getComputedStyle(document.documentElement);
  var g = function(n){ return s.getPropertyValue(n).trim(); };
  return {ink:g("--ink"), ink3:g("--ink-3"), line:g("--line-2"), panel:g("--panel"),
          up:g("--up"), down:g("--down"), gold:g("--gold-line"), p3:g("--panel-3")};
}

function drawChart(){
  if (!cv || !cvSym) return;
  var st = S[cvSym], C = themeColors();
  var n = Math.min(state.range, st.k.length);
  var ks = st.k.slice(-n), vs = st.v.slice(-n), ds = DATES.slice(-n);
  var od = st.od.slice(-n), hd = st.hd.slice(-n), ld = st.ld.slice(-n);
  var O = function(i){ return ks[i] + od[i]; };
  var Hi = function(i){ return ks[i] + hd[i]; };
  var Lo = function(i){ return ks[i] + ld[i]; };

  var pts = [];
  for (var i = 0; i < ks.length; i++) if (ks[i] !== null) pts.push(i);
  if (pts.length < 2) return;

  var dpr = window.devicePixelRatio || 1;
  var W = cv.clientWidth, H = Math.max(230, Math.round(W * 0.52));
  cv.width = Math.round(W * dpr); cv.height = Math.round(H * dpr);
  cv.style.height = H + "px";
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, W, H);

  var padL = 8, padR = 54, padT = 10;
  var volH = Math.round(H * 0.19), gap = 12;
  var priceH = H - padT - volH - gap - 20;
  var plotW = W - padL - padR;

  var lo = Infinity, hi = -Infinity;
  pts.forEach(function(i){
    if (Lo(i) < lo) lo = Lo(i);
    if (Hi(i) > hi) hi = Hi(i);
  });
  /* 52주 고가선은 화면 고점에 가까울 때만 (멀면 봉이 눌려서 안 보인다) */
  var showH52 = st.h && st.h <= hi * 1.08 && st.h >= lo;
  if (showH52) hi = Math.max(hi, st.h);
  var span = (hi - lo) || 1; lo -= span * 0.08; hi += span * 0.08; span = hi - lo;

  var X = function(i){ return padL + (i / (ks.length - 1)) * plotW; };
  var Y = function(v){ return padT + priceH - ((v - lo) / span) * priceH; };

  /* 격자 + 축 */
  ctx.font = '500 10px ui-monospace, SFMono-Regular, Menlo, monospace';
  ctx.textBaseline = "middle";
  for (var t = 0; t <= 4; t++) {
    var vy = lo + (span * t / 4), yy = Y(vy);
    ctx.strokeStyle = C.line; ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(padL, Math.round(yy) + .5);
    ctx.lineTo(padL + plotW, Math.round(yy) + .5); ctx.stroke();
    ctx.fillStyle = C.ink3; ctx.textAlign = "left";
    ctx.fillText(vy.toFixed(vy < 10 ? 2 : 0), padL + plotW + 7, yy);
  }

  /* 52주 고가선 */
  if (showH52) {
    ctx.save(); ctx.setLineDash([4, 4]); ctx.strokeStyle = C.gold; ctx.lineWidth = 1.2;
    ctx.beginPath(); ctx.moveTo(padL, Y(st.h)); ctx.lineTo(padL + plotW, Y(st.h));
    ctx.stroke(); ctx.restore();
    ctx.fillStyle = C.gold; ctx.textAlign = "right";
    ctx.fillText("52주 고가", padL + plotW - 4, Y(st.h) - 8);
  }

  /* 봉차트 */
  var cw = plotW / ks.length;
  var bw = Math.max(1, Math.min(13, cw * 0.68));
  var thin = bw < 2.6;                     /* 봉이 좁으면 몸통만 */
  pts.forEach(function(i){
    var c = ks[i], o = O(i), h = Hi(i), l = Lo(i);
    var up = c >= o, col = up ? C.up : C.down;
    var x = X(i), rx = Math.round(x) + .5;

    if (!thin) {                            /* 꼬리 */
      ctx.strokeStyle = col; ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo(rx, Y(h)); ctx.lineTo(rx, Y(l)); ctx.stroke();
    }
    var yTop = Y(Math.max(o, c)), yBot = Y(Math.min(o, c));
    var bh = Math.max(1, yBot - yTop);
    ctx.fillStyle = col;
    if (thin) ctx.fillRect(rx - bw / 2, Y(h), Math.max(1, bw), Math.max(1, Y(l) - Y(h)));
    else ctx.fillRect(x - bw / 2, yTop, bw, bh);
  });

  /* 거래량 */
  var vTop = padT + priceH + gap, vMax = Math.max.apply(null, vs) || 1;
  for (var j = 0; j < vs.length; j++) {
    if (ks[j] === null) continue;
    var vh = (vs[j] / vMax) * volH;
    var upv = ks[j] >= O(j);
    ctx.fillStyle = (upv ? C.up : C.down) + "66";
    ctx.fillRect(X(j) - bw / 2, vTop + volH - vh, Math.max(1, bw), vh);
  }
  ctx.fillStyle = C.ink3; ctx.textAlign = "left";
  ctx.fillText("거래량", padL + plotW + 7, vTop + volH / 2);

  /* 날짜 축 */
  ctx.fillStyle = C.ink3; ctx.textAlign = "center";
  var ticks = 5;
  for (var m = 0; m < ticks; m++) {
    var idx = Math.round(m * (ks.length - 1) / (ticks - 1));
    var lab = (ds[idx] || "").slice(2).replace(/-/g, ".");
    var tx = Math.min(Math.max(X(idx), 30), padL + plotW - 26);
    ctx.fillText(lab, tx, vTop + volH + 13);
  }

  /* 십자선 */
  if (hoverI >= 0 && hoverI < ks.length && ks[hoverI] !== null) {
    var hx = Math.round(X(hoverI)) + .5;
    ctx.save(); ctx.setLineDash([3, 3]); ctx.strokeStyle = C.ink3; ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(hx, padT); ctx.lineTo(hx, vTop + volH); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(padL, Math.round(Y(ks[hoverI])) + .5);
    ctx.lineTo(padL + plotW, Math.round(Y(ks[hoverI])) + .5); ctx.stroke();
    ctx.restore();
  }
  cvPts = {X:X, Y:Y, ks:ks, od:od, hd:hd, ld:ld, ds:ds, vs:vs,
           n:ks.length, padL:padL, plotW:plotW, priceH:priceH, padT:padT};
}

function chartMarkup(sym){
  var st = S[sym];
  var ranges = [[21,"1M"],[63,"3M"],[126,"6M"],[252,"1Y"]];
  var mark = st.ph >= 98 ? ' <span class="star">★ 신고가권</span>'
           : st.ph >= 95 ? ' <span class="star">◆ 고가 근접</span>' : "";
  return '<div class="card"><div class="chart-wrap">'
    + '<div class="chart-hd"><div class="who"><h3>' + esc(st.n) + mark + '</h3>'
    + '<p>' + esc(sym) + ' · ' + esc(st.t) + '</p></div>'
    + '<div class="px"><div class="p">' + money(st.p) + '</div>'
    + '<div class="c ' + cls(st.c) + '">' + sgn(st.c) + '</div></div></div>'
    + '<div class="ranges" role="tablist" aria-label="기간">'
    + ranges.map(function(r){
        return '<button class="rg" role="tab" data-r="' + r[0] + '" aria-selected="'
          + (state.range === r[0]) + '">' + r[1] + '</button>'; }).join("")
    + '</div>'
    + '<div class="cv-box"><canvas id="cv" role="img" aria-label="'
    + esc(st.n) + ' 주가 추이"></canvas><div class="tip" id="tip"></div></div>'
    + '<dl class="stats">'
    + stat("5일", sgn(st.c5), cls(st.c5)) + stat("20일", sgn(st.c20), cls(st.c20))
    + stat("52주 고가", money(st.h), "") + stat("52주 저가", money(st.l), "")
    + stat("고가대비", st.ph.toFixed(1) + "%", st.ph >= 98 ? "up" : "")
    + stat("거래량", st.vr.toFixed(2) + "x", st.vr >= 2 ? "up" : "")
    + '</dl></div></div>';
}
function stat(k, v, c){
  return '<div class="stat"><dt>' + k + '</dt><dd class="' + (c || "") + '">' + v + '</dd></div>';
}

function mountChart(){
  cv = $("cv"); if (!cv) return;
  ctx = cv.getContext("2d"); cvSym = state.sym; hoverI = -1;
  drawChart();

  var tip = $("tip");
  var move = function(ev){
    if (!cvPts) return;
    var r = cv.getBoundingClientRect();
    var x = (ev.touches ? ev.touches[0].clientX : ev.clientX) - r.left;
    var i = Math.round((x - cvPts.padL) / cvPts.plotW * (cvPts.n - 1));
    i = Math.max(0, Math.min(cvPts.n - 1, i));
    if (i === hoverI) return;
    hoverI = i; drawChart();
    var k = cvPts.ks[i]; if (k === null) { tip.style.opacity = 0; return; }
    var pv = i > 0 && cvPts.ks[i-1] !== null ? cvPts.ks[i-1] : k;
    var ch = pv ? (k / pv - 1) * 100 : 0;
    var o = k + cvPts.od[i], h = k + cvPts.hd[i], l = k + cvPts.ld[i];
    var f = function(v){ return v.toFixed(v < 10 ? 3 : 2); };
    tip.innerHTML = esc(cvPts.ds[i])
      + ' <span class="' + cls(ch) + '">' + sgn(ch) + '</span><br>'
      + '시 ' + f(o) + '  고 ' + f(h) + '<br>'
      + '저 ' + f(l) + '  종 <b>' + f(k) + '</b><br>'
      + '<span style="opacity:.7">거래량 '
      + (cvPts.vs[i] * 1000).toLocaleString("en-US") + '</span>';
    tip.style.opacity = 1;
    var tw = tip.offsetWidth, th = tip.offsetHeight, px = cvPts.X(i);
    tip.style.left = Math.max(2, Math.min(cv.clientWidth - tw - 2, px - tw / 2)) + "px";
    /* 봉을 가리지 않도록 커서 반대쪽에 붙인다 */
    var mid = cvPts.padT + cvPts.priceH / 2;
    tip.style.top = (cvPts.Y(k) > mid
      ? cvPts.padT + 4
      : cvPts.padT + cvPts.priceH - th - 4) + "px";
  };
  cv.addEventListener("mousemove", move);
  cv.addEventListener("touchmove", function(e){ move(e); }, {passive:true});
  cv.addEventListener("mouseleave", function(){
    hoverI = -1; tip.style.opacity = 0; drawChart(); });

  Array.prototype.forEach.call(document.querySelectorAll(".rg"), function(b){
    b.addEventListener("click", function(){
      state.range = +b.dataset.r;
      Array.prototype.forEach.call(document.querySelectorAll(".rg"), function(x){
        x.setAttribute("aria-selected", x === b); });
      drawChart();
    });
  });
}

/* ── 표 ── */
var COLS = [
  {k:"sym", t:"종목", l:true}, {k:"c", t:"당일"}, {k:"c5", t:"5일"},
  {k:"c20", t:"20일"}, {k:"p", t:"종가"}, {k:"ph", t:"52H"}, {k:"vr", t:"거래량"}
];

function tableMarkup(syms, title, meta){
  var dir = state.dir, key = state.sort;
  var rows = syms.slice().sort(function(a, b){
    var va = key === "sym" ? a : S[a][key], vb = key === "sym" ? b : S[b][key];
    if (typeof va === "string") return dir * va.localeCompare(vb);
    return dir * (va - vb);
  });

  var head = COLS.map(function(c){
    var on = state.sort === c.k;
    return '<th class="' + (c.l ? "l" : "") + '" data-k="' + c.k + '" title="정렬">'
      + c.t + (on ? ' <span class="ar">' + (dir < 0 ? "▼" : "▲") + '</span>' : '') + '</th>';
  }).join("");

  var body = rows.map(function(s){
    var r = S[s];
    var mk = r.ph >= 98 ? '<span class="star">★</span>'
           : r.ph >= 95 ? '<span class="star">◆</span>' : '';
    var vb = Math.min(100, r.vr / 3 * 100);
    return '<tr tabindex="0" data-s="' + esc(s) + '" aria-selected="'
      + (state.sym === s) + '">'
      + '<td class="l"><span class="tk">' + esc(s) + '</span> '
      + '<span class="nm">' + esc(r.n) + '</span> ' + mk + '</td>'
      + '<td class="num ' + cls(r.c) + '">' + sgn(r.c) + '</td>'
      + '<td class="num ' + cls(r.c5) + '">' + sgn(r.c5) + '</td>'
      + '<td class="num ' + cls(r.c20) + '">' + sgn(r.c20) + '</td>'
      + '<td class="num">' + money(r.p) + '</td>'
      + '<td class="num' + (r.ph >= 98 ? ' up' : '') + '">' + r.ph.toFixed(1) + '</td>'
      + '<td class="bar-cell"><div class="bar" title="' + r.vr.toFixed(2)
      + '배"><i style="width:' + vb + '%"></i></div></td></tr>';
  }).join("");

  return '<div class="card"><div class="card-head"><h2>' + esc(title) + '</h2>'
    + '<span class="meta">' + esc(meta) + '</span></div>'
    + '<div class="t-scroll"><table><thead><tr>' + head + '</tr></thead>'
    + '<tbody>' + body + '</tbody></table></div></div>';
}

/* ── 요약 ── */
function rankList(list, worst){
  var max = Math.max.apply(null, list.map(function(x){ return Math.abs(T[x].avg); })) || 1;
  return '<div class="rank">' + list.map(function(t, i){
    var s = T[t], w = Math.abs(s.avg) / max * 100;
    return '<button class="rank-row" data-t="' + esc(t) + '">'
      + '<span class="no">' + (i + 1) + '</span>'
      + '<span class="nmx">' + esc(t)
      + '<em>' + esc(S[s.lead] ? S[s.lead].n : "") + ' ' + sgn(S[s.lead] ? S[s.lead].c : 0, 1)
      + ' · 상승 ' + s.up + '/' + s.n + '</em></span>'
      + '<span class="track"><i class="" style="width:' + w + '%;'
      + (worst ? 'right:0;' : 'left:0;')
      + 'background:var(--' + (s.avg > 0 ? 'up' : s.avg < 0 ? 'down' : 'flat') + ')"></i></span>'
      + '<span class="v ' + cls(s.avg) + '">' + sgn(s.avg) + '</span></button>';
  }).join("") + '</div>';
}

function summaryMarkup(){
  var ts = Object.keys(T).sort(function(a, b){ return T[b].avg - T[a].avg; });
  var strong = ts.slice(0, 12), weak = ts.slice(-12).reverse();
  var hi = Object.keys(S).filter(function(s){ return S[s].ph >= 98; })
    .sort(function(a, b){ return S[b].ph - S[a].ph; });

  var out = '<div class="sum-grid">'
    + '<div class="card"><div class="card-head"><h2>강세 테마</h2>'
    + '<span class="meta">당일 등락률 상위 12</span></div>' + rankList(strong, false) + '</div>'
    + '<div class="card"><div class="card-head"><h2>약세 테마</h2>'
    + '<span class="meta">당일 등락률 하위 12</span></div>' + rankList(weak, true) + '</div>'
    + '</div>';

  out += '<div class="cols" style="grid-template-columns:1fr; margin-top:18px">'
    + '<div class="card"><div class="card-head"><h2>52주 신고가권</h2>'
    + '<span class="meta">' + hi.length + '종목 · 고가 대비 98% 이상</span></div>';
  out += hi.length
    ? '<div class="hi-grid">' + hi.map(function(s){
        var r = S[s];
        return '<button class="hi" data-s="' + esc(s) + '">'
          + '<span class="r1"><span class="tk">' + esc(s) + '</span>'
          + '<span class="nm">' + esc(r.n) + '</span></span>'
          + '<span class="r2">' + money(r.p) + '<span class="' + cls(r.c) + '">'
          + sgn(r.c) + '</span><span class="star">' + r.ph.toFixed(1) + '%</span></span>'
          + '<span class="th">' + esc(r.t) + '</span></button>';
      }).join("") + '</div>'
    : '<div class="empty"><p>오늘은 신고가권 종목이 없습니다.</p></div>';
  out += '</div></div>';
  return out;
}

/* ── 렌더 ── */
function render(){
  Array.prototype.forEach.call(document.querySelectorAll(".tab"), function(b){
    b.setAttribute("aria-selected", b.dataset.g === state.group);
  });

  if (state.group === "요약") {
    $("chips").innerHTML = "";
    $("view").innerHTML = summaryMarkup();
    bindSummary();
    return;
  }

  var list = G[state.group] || [];
  if (!state.theme || list.indexOf(state.theme) < 0) state.theme = list[0];

  $("chips").innerHTML = list.map(function(t){
    var s = T[t];
    return '<button class="chip" role="tab" data-t="' + esc(t) + '" aria-selected="'
      + (t === state.theme) + '">' + esc(t)
      + '<span class="pct ' + (t === state.theme ? "" : cls(s.avg)) + '">'
      + sgn(s.avg) + '</span></button>';
  }).join("");

  var th = T[state.theme];
  var syms = th ? th.syms : [];
  if (syms.length && (!state.sym || syms.indexOf(state.sym) < 0)) state.sym = syms[0];

  var meta = th ? "평균 " + sgn(th.avg) + " · 상승 " + th.up + "/" + th.n
    + (th.near ? " · 신고가권 " + th.near : "") : "";

  $("view").innerHTML = '<div class="cols">'
    + tableMarkup(syms, state.theme, meta)
    + (state.sym ? chartMarkup(state.sym)
        : '<div class="card"><div class="empty"><p>종목을 선택하세요.</p></div></div>')
    + '</div>';

  bindTable();
  if (state.sym) mountChart();
}

function bindTable(){
  Array.prototype.forEach.call(document.querySelectorAll("tbody tr"), function(tr){
    var pick = function(){ state.sym = tr.dataset.s; render(); };
    tr.addEventListener("click", pick);
    tr.addEventListener("keydown", function(e){
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); pick(); }
      else if (e.key === "ArrowDown" && tr.nextElementSibling) {
        e.preventDefault(); tr.nextElementSibling.focus(); }
      else if (e.key === "ArrowUp" && tr.previousElementSibling) {
        e.preventDefault(); tr.previousElementSibling.focus(); }
    });
  });
  Array.prototype.forEach.call(document.querySelectorAll("th[data-k]"), function(th){
    th.addEventListener("click", function(){
      var k = th.dataset.k;
      if (state.sort === k) state.dir = -state.dir;
      else { state.sort = k; state.dir = k === "sym" ? 1 : -1; }
      render();
    });
  });
}

function bindSummary(){
  Array.prototype.forEach.call(document.querySelectorAll(".rank-row"), function(b){
    b.addEventListener("click", function(){ goTheme(b.dataset.t); });
  });
  Array.prototype.forEach.call(document.querySelectorAll(".hi"), function(b){
    b.addEventListener("click", function(){ goSym(b.dataset.s); });
  });
}

function goTheme(theme){
  for (var i = 0; i < GROUPS.length; i++) {
    if (G[GROUPS[i]].indexOf(theme) >= 0) {
      state.group = GROUPS[i]; state.theme = theme; state.sym = null; render();
      window.scrollTo({top:0, behavior:"smooth"});
      return;
    }
  }
}
function goSym(sym){
  var st = S[sym]; if (!st) return;
  state.sym = sym;
  for (var i = 0; i < GROUPS.length; i++) {
    if (G[GROUPS[i]].indexOf(st.t) >= 0) { state.group = GROUPS[i]; state.theme = st.t; break; }
  }
  render();
  window.scrollTo({top:0, behavior:"smooth"});
}

/* ── 이벤트 ── */
Array.prototype.forEach.call(document.querySelectorAll(".tab"), function(b){
  b.addEventListener("click", function(){
    state.group = b.dataset.g; state.theme = null; state.sym = null; render();
  });
});
$("chips").addEventListener("click", function(e){
  var c = e.target.closest(".chip"); if (!c) return;
  state.theme = c.dataset.t; state.sym = null; render();
});
$("q").addEventListener("keydown", function(e){
  if (e.key !== "Enter") return;
  var v = e.target.value.trim().toLowerCase(); if (!v) return;
  var keys = Object.keys(S);
  var hit = keys.find(function(s){ return s.toLowerCase() === v; })
    || keys.find(function(s){ return s.toLowerCase().indexOf(v) === 0; })
    || keys.find(function(s){ return S[s].n.toLowerCase().indexOf(v) >= 0; });
  if (hit) { goSym(hit); e.target.blur(); }
});

var rt;
window.addEventListener("resize", function(){
  clearTimeout(rt); rt = setTimeout(drawChart, 120);
});
if (window.matchMedia) {
  var mq = window.matchMedia("(prefers-color-scheme: dark)");
  if (mq.addEventListener) mq.addEventListener("change", function(){ drawChart(); });
}

render();
})();
</script>
"""


def render_html(payload):
    data = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    data = data.replace("<", "\\u003c").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    return PAGE.replace("__DATA__", data)


def main():
    ap = argparse.ArgumentParser(description="미장 테마 스캐너 HTML 대시보드 생성")
    ap.add_argument("--demo", action="store_true", help="샘플 데이터로 생성 (레이아웃 확인용)")
    ap.add_argument("--output", "-o", default="dashboard.html", help="출력 HTML 경로")
    args = ap.parse_args()

    symbols = [s for syms in US_THEMES.values() for s in syms]

    if args.demo:
        series, dates = fetch_demo(symbols)
    else:
        series, dates = fetch_real(symbols)

    payload = build_payload(series, dates, args.demo)
    html = render_html(payload)

    with open(args.output, "w", encoding="utf-8") as f:
        f.write(html)

    size_mb = len(html.encode("utf-8")) / 1e6
    print(f"  생성 완료: {args.output} ({size_mb:.2f} MB, "
          f"{len(payload['stocks'])}종목 / {len(payload['themes'])}테마)", file=sys.stderr)


if __name__ == "__main__":
    main()
