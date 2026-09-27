#!/usr/bin/env python3
"""
주간 시황 방송 자료 — 일요일 라이브용 자기완결형 HTML 생성기

한 주 동안 미장/국장에서 무슨 일이 있었는지, 돈이 어디로 갔는지를
방송 화면에 바로 띄울 수 있는 한 장짜리 페이지로 만든다.

  1. 오프닝       : 이번 주 핵심 요약 (자동 생성 문장)
  2. 주간 성적표   : 미/한 지수 + 환율·금리·유가·금·비트코인·VIX
  3. 미장 섹터     : 11개 섹터 ETF 주간 등락 + 거래대금 증감, 스타일(성장/가치, 대형/소형)
  4. 머니플로우 맵 : 87개 테마를 '주간 등락 x 거래대금 증감'으로 배치
  5. 미장 특징주   : 상승/하락 TOP, 거래대금 급증, 52주 신고가
  6. 국장 수급     : 투자자별 순매수, 외국인·기관 순매수 TOP, 업종 등락
  7. 국장 특징주   : 상승/하락 TOP, 거래대금 TOP
  8. 다음 주 체크  : 실적 발표 예정 + 직접 적는 메모

사용법:
  python weekly_brief.py                    # 실데이터 (yfinance + pykrx)
  python weekly_brief.py --demo             # 샘플 데이터 (레이아웃 확인용)
  python weekly_brief.py -o brief.html
  python weekly_brief.py --no-kr            # 국장 수급(pykrx) 생략
"""
import argparse
import json
import math
import os
import random
import sys
import time
from datetime import datetime, timedelta, timezone
from io import StringIO

import pandas as pd

from stock_report import US_THEMES, THEME_GROUPS, KOSPI, KOSDAQ, get_name

KST = timezone(timedelta(hours=9))

# ─── 지수 / 매크로 ───
INDICES = [
    # (심볼, 이름, 그룹)
    ("^GSPC", "S&P 500", "US"),
    ("^IXIC", "나스닥", "US"),
    ("^DJI", "다우", "US"),
    ("^RUT", "러셀2000", "US"),
    ("^SOX", "필라델피아 반도체", "US"),
    ("^KS11", "코스피", "KR"),
    ("^KQ11", "코스닥", "KR"),
]
MACRO = [
    # (심볼, 이름, 표시형식)
    ("KRW=X", "원/달러 환율", "fx"),
    ("^TNX", "미 10년물 금리", "yield"),
    ("DX-Y.NYB", "달러인덱스", "num"),
    ("^VIX", "VIX 공포지수", "num"),
    ("CL=F", "WTI 유가", "usd"),
    ("GC=F", "금", "usd"),
    ("BTC-USD", "비트코인", "usd0"),
]
SECTORS = [
    ("XLK", "기술"), ("XLC", "커뮤니케이션"), ("XLY", "경기소비재"),
    ("XLF", "금융"), ("XLI", "산업재"), ("XLE", "에너지"),
    ("XLB", "소재"), ("XLV", "헬스케어"), ("XLP", "필수소비재"),
    ("XLU", "유틸리티"), ("XLRE", "부동산"),
]
STYLES = [
    # (A, B, 이름, A라벨, B라벨)
    ("IWF", "IWD", "성장주 vs 가치주", "성장", "가치"),
    ("SPY", "IWM", "대형주 vs 소형주", "대형", "소형"),
    ("SPY", "RSP", "시총가중 vs 동일가중", "빅테크 쏠림", "골고루"),
    ("SPHB", "SPLV", "고베타 vs 저변동", "공격", "방어"),
]

# 국장 업종 대신 쓰는 테마 ETF — KRX 로그인 없이 yfinance로 받는다
KR_ETFS = [
    ("091160.KS", "반도체"), ("139260.KS", "IT(대형)"), ("305720.KS", "2차전지"),
    ("091180.KS", "자동차"), ("466920.KS", "조선"), ("139230.KS", "중공업"),
    ("449450.KS", "방산"), ("434730.KS", "원자력"), ("445290.KS", "로봇"),
    ("244580.KS", "바이오"), ("227540.KS", "헬스케어"), ("091170.KS", "은행"),
    ("102970.KS", "증권"), ("140700.KS", "보험"), ("117700.KS", "건설"),
    ("117680.KS", "철강"), ("117460.KS", "에너지화학"), ("140710.KS", "운송"),
    ("228790.KS", "화장품"), ("266410.KS", "필수소비재"), ("228810.KS", "미디어/엔터"),
    ("300950.KS", "게임"), ("157490.KS", "소프트웨어"),
]

US_MIN_DV = 20e6     # 특징주 최소 일평균 거래대금 ($)
KR_MIN_CAP = 3e11    # 국장 특징주 최소 시가총액 (3,000억)
TOP_N = 10


# ───────────────────────── 공통 ─────────────────────────

def week_split(dates):
    """마지막 거래일이 속한 주의 거래일 목록과, 그 직전 거래일을 돌려준다."""
    dates = pd.DatetimeIndex(dates)
    last = dates[-1]
    monday = (last - pd.Timedelta(days=last.weekday())).normalize()
    this_week = dates[dates >= monday]
    before = dates[dates < monday]
    return this_week, (before[-1] if len(before) else None)


def pct(a, b):
    return round((a / b - 1) * 100, 2) if b else 0.0


def _series(raw, sym, field):
    try:
        if isinstance(raw.columns, pd.MultiIndex):
            return raw[(sym, field)].dropna()
        return raw[field].dropna()
    except Exception:
        return pd.Series(dtype=float)


# ───────────────────────── 미장 수집 ─────────────────────────

def fetch_us(symbols, chunk_size=80):
    """심볼별 DataFrame(Close, High, Volume) 1년치."""
    import yfinance as yf

    out = {}
    uniq = sorted(set(symbols))
    print(f"  [미장] {len(uniq)}개 심볼 수집", file=sys.stderr)
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
            c = _series(raw, sym, "Close")
            if len(c) < 30:
                continue
            out[sym] = pd.DataFrame({
                "Close": c,
                "High": _series(raw, sym, "High").reindex(c.index),
                "Volume": _series(raw, sym, "Volume").reindex(c.index).fillna(0),
            })
        print(f"  ... {min(start+chunk_size, len(uniq))}/{len(uniq)}", file=sys.stderr)
    return out


def fetch_earnings(symbols, week_start, week_end):
    """다음 주 실적 발표 예정 종목."""
    import yfinance as yf

    rows = []
    for sym in symbols:
        try:
            cal = yf.Ticker(sym).calendar
            dates = cal.get("Earnings Date") if isinstance(cal, dict) else None
            if not dates:
                continue
            d = pd.Timestamp(dates[0]).date()
            if week_start <= d <= week_end:
                rows.append(dict(sym=sym, name=get_name(sym), date=d.strftime("%m/%d (%a)")))
        except Exception:
            continue
        time.sleep(0.1)
    return sorted(rows, key=lambda r: r["date"])


# ───────────────────────── 국장 수집 (pykrx) ─────────────────────────

def fetch_kr(kr_days, prev_day):
    """주간 투자자별 순매수, 순매수 상위, 업종, 종목 등락."""
    from pykrx import stock as krx

    fmt = lambda d: pd.Timestamp(d).strftime("%Y%m%d")
    start, end, base = fmt(kr_days[0]), fmt(kr_days[-1]), fmt(prev_day)
    print(f"  [국장] {start}~{end} 수급 조회", file=sys.stderr)
    kr = {"period": f"{start[4:6]}/{start[6:]}~{end[4:6]}/{end[6:]}"}

    # 투자자별 순매수 (시장 전체)
    inv = {}
    for mkt in ("KOSPI", "KOSDAQ"):
        try:
            df = krx.get_market_trading_value_by_investor(start, end, mkt)
            inv[mkt] = {k: float(df.loc[row, "순매수"])
                        for k, row in (("외국인", "외국인"), ("기관", "기관합계"), ("개인", "개인"))}
        except Exception as e:
            print(f"  투자자별 순매수({mkt}) 실패: {e}", file=sys.stderr)
    kr["investors"] = inv

    # 외국인 / 기관 순매수 상위
    for key, who in (("foreign", "외국인"), ("inst", "기관합계")):
        frames = []
        for mkt in ("KOSPI", "KOSDAQ"):
            try:
                df = krx.get_market_net_purchases_of_equities(start, end, mkt, who)
                frames.append(df[["종목명", "순매수거래대금"]])
            except Exception as e:
                print(f"  {who} 순매수({mkt}) 실패: {e}", file=sys.stderr)
            time.sleep(0.3)
        if frames:
            df = pd.concat(frames).sort_values("순매수거래대금", ascending=False)
            kr[key + "_buy"] = [dict(name=r["종목명"], amt=float(r["순매수거래대금"]))
                                for _, r in df.head(TOP_N).iterrows()]
            kr[key + "_sell"] = [dict(name=r["종목명"], amt=float(r["순매수거래대금"]))
                                 for _, r in df.tail(TOP_N).iloc[::-1].iterrows()]

    # 업종 지수 (코스피 업종)
    try:
        df = krx.get_index_price_change(base, end, "KOSPI")
        df = df[~df.index.str.contains("코스피|200|100|50|배당|고배당|레버리지")]
        kr["sectors"] = sorted(
            [dict(name=n, wk=round(float(r["등락률"]), 2)) for n, r in df.iterrows()],
            key=lambda r: r["wk"], reverse=True)
    except Exception as e:
        print(f"  업종 등락 실패: {e}", file=sys.stderr)

    # 종목 주간 등락: 직전 주 마지막 거래일 종가 대비
    try:
        snap_prev = krx.get_market_ohlcv_by_ticker(base, market="ALL")
        snap_end = krx.get_market_ohlcv_by_ticker(end, market="ALL")
        cap = krx.get_market_cap_by_ticker(end, market="ALL")["시가총액"]
        tv = None
        for d in kr_days:
            s = krx.get_market_ohlcv_by_ticker(fmt(d), market="ALL")["거래대금"]
            tv = s if tv is None else tv.add(s, fill_value=0)
            time.sleep(0.3)
        df = pd.DataFrame({
            "prev": snap_prev["종가"], "close": snap_end["종가"], "cap": cap, "tv": tv,
        }).dropna()
        df = df[(df["prev"] > 0) & (df["cap"] >= KR_MIN_CAP)]
        df["wk"] = (df["close"] / df["prev"] - 1) * 100

        def rows(sub):
            out = []
            for t, r in sub.iterrows():
                name = krx.get_market_ticker_name(t)
                if "스팩" in name:
                    continue
                out.append(dict(sym=t, name=name, close=float(r["close"]),
                                wk=round(float(r["wk"]), 2), tv=float(r["tv"]),
                                cap=float(r["cap"])))
            return out[:TOP_N]

        kr["up"] = rows(df.sort_values("wk", ascending=False).head(TOP_N + 5))
        kr["down"] = rows(df.sort_values("wk").head(TOP_N + 5))
        kr["tv_top"] = rows(df.sort_values("tv", ascending=False).head(TOP_N + 5))
    except Exception as e:
        print(f"  종목 등락 실패: {e}", file=sys.stderr)

    return kr


def _num(x):
    try:
        v = float(str(x).replace(",", "").replace("+", ""))
        return 0.0 if v != v else v
    except ValueError:
        return 0.0


def fetch_naver_investors(kr_days):
    """KRX 로그인 없이 네이버 증권 API로 투자자별 일별 순매수를 받아 주간 합계를 낸다. 단위: 원."""
    import requests

    out = {}
    for mkt in ("KOSPI", "KOSDAQ"):
        tot, got = {"외국인": 0.0, "기관": 0.0, "개인": 0.0}, 0
        for d in kr_days:
            day = pd.Timestamp(d).strftime("%Y%m%d")
            try:
                res = requests.get(f"https://m.stock.naver.com/api/index/{mkt}/trend",
                                   params={"bizdate": day}, timeout=10,
                                   headers={"User-Agent": "Mozilla/5.0", "Referer": "https://m.stock.naver.com/"})
                j = res.json()
                if j.get("bizdate") != day:     # 휴장일 등은 다른 날짜가 돌아온다
                    continue
                # 값은 억원 단위 문자열 ("+3,189")
                tot["외국인"] += _num(j.get("foreignValue"))
                tot["기관"] += _num(j.get("institutionalValue"))
                tot["개인"] += _num(j.get("personalValue"))
                got += 1
            except Exception as e:
                print(f"  [국장] 네이버 투자자별({mkt} {day}) 실패: {e}", file=sys.stderr)
            time.sleep(0.2)
        if got:
            out[mkt] = {k: v * 1e8 for k, v in tot.items()}
        print(f"  [국장] 네이버 투자자별({mkt}) {got}/{len(kr_days)}일 "
              + " ".join(f"{k} {v:+,.0f}억" for k, v in tot.items()), file=sys.stderr)
    return out


def kr_movers_from_frames(frames, kr_week, kr_prev):
    """KRX 로그인 없이 yfinance 시세로 코스피·코스닥 대형주 주간 등락 / 거래대금."""
    rows = []
    for sym in KOSPI + KOSDAQ:
        df = frames.get(sym)
        s = stats(df, kr_week, kr_prev) if df is not None else None
        if not s:
            continue
        wk = df.loc[df.index.isin(kr_week)]
        rows.append(dict(sym=sym, name=get_name(sym), close=s["close"], wk=s["wk"],
                         tv=float((wk["Close"] * wk["Volume"]).sum())))
    if not rows:
        return {}
    return dict(
        up=sorted(rows, key=lambda r: r["wk"], reverse=True)[:TOP_N],
        down=sorted(rows, key=lambda r: r["wk"])[:TOP_N],
        tv_top=sorted(rows, key=lambda r: r["tv"], reverse=True)[:TOP_N],
        movers_src=f"코스피·코스닥 대형주 {len(rows)}종목",
    )


# ───────────────────────── 샘플 데이터 ─────────────────────────

def demo_frames(symbols):
    """레이아웃 확인용 합성 시계열. 실제 시세가 아니다."""
    rng = random.Random(20260927)
    today = datetime.now(KST).date()
    dates, d = [], today - timedelta(days=1)
    while len(dates) < 252:
        if d.weekday() < 5:
            dates.append(pd.Timestamp(d))
        d -= timedelta(days=1)
    dates.reverse()
    idx = pd.DatetimeIndex(dates)

    theme_kick = {t: rng.gauss(0.002, 0.012) for t in US_THEMES}
    theme_flow = {t: rng.uniform(0.7, 1.9) for t in US_THEMES}
    sym_theme = {}
    for t, syms in US_THEMES.items():
        for s in syms:
            sym_theme.setdefault(s, t)

    start_px = {"^GSPC": 6600, "^IXIC": 22400, "^DJI": 46200, "^RUT": 2420, "^SOX": 6100,
                "^KS11": 3450, "^KQ11": 860, "KRW=X": 1392, "^TNX": 4.15, "DX-Y.NYB": 98.2,
                "^VIX": 16.5, "CL=F": 64.0, "GC=F": 3720, "BTC-USD": 109000}
    out = {}
    for sym in sorted(set(symbols)):
        t = sym_theme.get(sym)
        vol = 0.008 if sym.startswith("^") or "=" in sym or len(sym) <= 4 and sym.startswith("X") \
            else rng.uniform(0.012, 0.04)
        close = start_px.get(sym, rng.uniform(15, 480))
        base_v = rng.uniform(2e6, 3e7)
        cs, hs, vs = [], [], []
        for i in range(len(idx)):
            last_week = i >= len(idx) - 5
            drift = 0.0004 + (theme_kick[t] if (t and last_week) else 0)
            if not t and last_week:
                drift += rng.gauss(0, 0.004)
            close = max(0.5, close * (1 + rng.gauss(drift, vol)))
            cs.append(close)
            hs.append(close * (1 + abs(rng.gauss(0, vol / 2))))
            flow = theme_flow[t] if (t and last_week) else rng.uniform(0.8, 1.3) if last_week else 1
            vs.append(base_v * rng.uniform(0.6, 1.4) * flow)
        out[sym] = pd.DataFrame({"Close": cs, "High": hs, "Volume": vs}, index=idx)
    return out


def demo_kr():
    rng = random.Random(7)
    names = ["삼성전자", "SK하이닉스", "한화에어로스페이스", "현대차", "HD현대중공업",
             "두산에너빌리티", "알테오젠", "에코프로비엠", "NAVER", "카카오", "셀트리온",
             "KB금융", "LIG넥스원", "한미반도체", "삼성바이오로직스", "기아", "삼양식품",
             "HLB", "레인보우로보틱스", "리가켐바이오", "효성중공업", "LS ELECTRIC",
             "현대로템", "삼성중공업", "HD현대일렉트릭", "크래프톤", "펩트론", "이수페타시스"]

    def pick(n, lo, hi, amt=False):
        out = []
        for nm in rng.sample(names, n):
            v = rng.uniform(lo, hi)
            out.append(dict(name=nm, amt=v * 1e8) if amt else
                       dict(sym="000000", name=nm, close=round(rng.uniform(2e4, 9e5), -2),
                            wk=round(v, 2), tv=rng.uniform(3e11, 6e12), cap=rng.uniform(1e12, 4e14)))
        key = "amt" if amt else "wk"
        return sorted(out, key=lambda r: r[key], reverse=hi > 0)

    sectors = ["전기전자", "운송장비·부품", "기계·장비", "금융", "제약", "화학", "철강·금속",
               "건설", "IT 서비스", "유통", "통신", "음식료·담배", "증권", "보험", "전기·가스",
               "비금속", "섬유·의류", "종이·목재", "운송·창고", "오락·문화"]
    return dict(
        period="데모",
        investors={"KOSPI": {"외국인": 1.84e12, "기관": -4.1e11, "개인": -1.52e12},
                   "KOSDAQ": {"외국인": 2.3e11, "기관": 1.1e11, "개인": -3.6e11}},
        foreign_buy=pick(TOP_N, 150, 9000, True), foreign_sell=pick(TOP_N, -4000, -120, True),
        inst_buy=pick(TOP_N, 100, 3000, True), inst_sell=pick(TOP_N, -2500, -90, True),
        sectors=sorted([dict(name=s, wk=round(rng.gauss(0.6, 2.6), 2)) for s in sectors],
                       key=lambda r: r["wk"], reverse=True),
        up=pick(TOP_N, 8, 42), down=pick(TOP_N, -24, -5),
        tv_top=sorted(pick(TOP_N, -6, 18), key=lambda r: r["tv"], reverse=True),
    )


# ───────────────────────── 집계 ─────────────────────────

def stats(df, week, prev_day):
    """주간 등락, 거래대금 증감(이번 주 일평균 / 직전 20일 일평균), 신고가 여부."""
    c = df["Close"]
    if prev_day not in c.index or week[-1] not in c.index:
        return None
    close, base = float(c.loc[week[-1]]), float(c.loc[prev_day])
    dv = df["Close"] * df["Volume"]
    this = dv.loc[dv.index.isin(week)]
    before = dv.loc[dv.index <= prev_day].tail(20)
    avg_before = float(before.mean()) if len(before) else 0.0
    hi_before = float(df["High"].loc[df.index <= prev_day].tail(251).max())
    hi_week = float(df["High"].loc[df.index.isin(week)].max())
    spark = [round(float(x), 4) for x in c.tail(40)]
    return dict(
        close=close, wk=pct(close, base),
        m1=pct(close, float(c.iloc[-22])) if len(c) > 22 else 0.0,
        dv=float(this.mean()) if len(this) else 0.0,
        dvr=round(float(this.mean()) / avg_before, 2) if avg_before and len(this) else 1.0,
        nh=bool(hi_week >= hi_before) if hi_before == hi_before else False,
        spark=spark,
    )


def build_payload(frames, kr, earnings, demo):
    spine = frames["^GSPC"].index
    week, prev_day = week_split(spine)
    kr_week, kr_prev = week_split(frames["^KS11"].index) if "^KS11" in frames else (week, prev_day)

    def st(sym, wk=week, pv=prev_day):
        return stats(frames[sym], wk, pv) if sym in frames else None

    indices = []
    for sym, name, grp in INDICES:
        s = st(sym, *(kr_week, kr_prev) if grp == "KR" else (week, prev_day))
        if s:
            indices.append(dict(sym=sym, name=name, g=grp, last=s["close"], wk=s["wk"],
                                m1=s["m1"], spark=s["spark"]))
    macro = []
    for sym, name, kind in MACRO:
        s = st(sym)
        if s:
            base = s["close"] / (1 + s["wk"] / 100)
            macro.append(dict(sym=sym, name=name, kind=kind, last=s["close"], wk=s["wk"],
                              chg=s["close"] - base, spark=s["spark"]))

    sectors = []
    for sym, name in SECTORS:
        s = st(sym)
        if s:
            sectors.append(dict(sym=sym, name=name, wk=s["wk"], dvr=s["dvr"], m1=s["m1"]))
    sectors.sort(key=lambda r: r["wk"], reverse=True)

    kr_etfs = []
    for sym, name in KR_ETFS:
        s = st(sym, kr_week, kr_prev)
        if s:
            kr_etfs.append(dict(sym=sym.replace(".KS", ""), name=name, wk=s["wk"], dvr=s["dvr"]))
    kr_etfs.sort(key=lambda r: r["wk"], reverse=True)

    styles = []
    for a, b, name, la, lb in STYLES:
        sa, sb = st(a), st(b)
        if sa and sb:
            styles.append(dict(name=name, a=la, b=lb, aw=sa["wk"], bw=sb["wk"],
                               win=la if sa["wk"] >= sb["wk"] else lb,
                               gap=round(abs(sa["wk"] - sb["wk"]), 2)))

    # 종목 / 테마
    sym_theme = {}
    for t, syms in US_THEMES.items():
        for s in syms:
            sym_theme.setdefault(s, t)
    stocks = {}
    for sym in sym_theme:
        s = st(sym)
        if s:
            stocks[sym] = dict(sym=sym, name=get_name(sym), t=sym_theme[sym],
                               close=round(s["close"], 2), wk=s["wk"], dv=s["dv"],
                               dvr=s["dvr"], nh=s["nh"])

    group_of = {t: g for g, ts in THEME_GROUPS.items() for t in ts}
    themes = []
    for t, syms in US_THEMES.items():
        rows = [stocks[s] for s in syms if s in stocks]
        if len(rows) < 2:
            continue
        rets = sorted(r["wk"] for r in rows)
        dv_now = sum(r["dv"] for r in rows)
        dv_base = sum(r["dv"] / r["dvr"] for r in rows if r["dvr"])
        themes.append(dict(
            name=t, g=group_of.get(t, "기타"), n=len(rows),
            wk=round(sum(rets) / len(rets), 2),
            med=round(rets[len(rets) // 2], 2),
            up=round(sum(1 for x in rets if x > 0) / len(rets) * 100),
            dvr=round(dv_now / dv_base, 2) if dv_base else 1.0,
            lead=[r["sym"] for r in sorted(rows, key=lambda r: r["wk"], reverse=True)[:3]],
        ))
    themes.sort(key=lambda r: r["wk"], reverse=True)

    liquid = [s for s in stocks.values() if s["dv"] / max(s["dvr"], 0.01) >= US_MIN_DV]
    movers = dict(
        up=sorted(liquid, key=lambda r: r["wk"], reverse=True)[:TOP_N],
        down=sorted(liquid, key=lambda r: r["wk"])[:TOP_N],
        flow=sorted(liquid, key=lambda r: r["dvr"], reverse=True)[:TOP_N],
        nh=sorted([s for s in liquid if s["nh"]], key=lambda r: r["wk"], reverse=True)[:24],
    )
    nh_total = sum(1 for s in stocks.values() if s["nh"])

    p = dict(
        demo=demo,
        week_us=f"{week[0]:%m/%d}~{week[-1]:%m/%d}",
        week_kr=f"{kr_week[0]:%m/%d}~{kr_week[-1]:%m/%d}",
        title=f"{week[-1]:%Y}년 {week[-1].month}월 {(week[-1].day - 1) // 7 + 1}주차",
        generated=datetime.now(KST).strftime("%Y-%m-%d %H:%M KST"),
        indices=indices, macro=macro, sectors=sectors, styles=styles,
        themes=themes, movers=movers, nh_total=nh_total, universe=len(stocks),
        breadth=round(sum(1 for s in stocks.values() if s["wk"] > 0) / max(len(stocks), 1) * 100),
        kr=kr or {}, kr_etfs=kr_etfs, earnings=earnings or [],
    )
    p["summary"] = summarize(p)
    return p


def summarize(p):
    """방송 오프닝용 핵심 문장 (규칙 기반)."""
    lines = []
    idx = {i["sym"]: i for i in p["indices"]}
    sign = lambda v: f"{v:+.2f}%"

    us = [idx[s] for s in ("^GSPC", "^IXIC") if s in idx]
    krx = [idx[s] for s in ("^KS11", "^KQ11") if s in idx]
    if us:
        lines.append(("지수", " · ".join(f"{i['name']} {sign(i['wk'])}" for i in us + krx)))

    if p["sectors"]:
        top = [s for s in p["sectors"] if s["dvr"] >= 1.0][:2] or p["sectors"][:2]
        bot = p["sectors"][-1]
        hot = ", ".join(f"{s['name']}({sign(s['wk'])}, 거래대금 {s['dvr']:.1f}배)" for s in top)
        lines.append(("미장 섹터", f"돈이 몰린 곳: {hot} / 가장 약한 곳: {bot['name']}({sign(bot['wk'])})"))

    if p["styles"]:
        won = [(s["name"].split(" vs ")[0 if s["win"] == s["a"] else 1], s["gap"]) for s in p["styles"][:3]]
        lines.append(("스타일", " · ".join(f"{w} 우위({g:.1f}%p)" for w, g in won)))

    hot = [t for t in p["themes"] if t["dvr"] >= 1.2 and t["wk"] > 0][:3]
    if hot:
        lines.append(("머니플로우", "거래대금 늘며 오른 테마: " +
                      ", ".join(f"{t['name']}({sign(t['wk'])})" for t in hot)))
    cold = [t for t in p["themes"][::-1] if t["wk"] < 0][:3]
    if cold:
        lines.append(("약세 테마", ", ".join(f"{t['name']}({sign(t['wk'])})" for t in cold)))

    ke = [e for e in p["kr_etfs"] if e["dvr"] >= 1.0 and e["wk"] > 0][:3] or p["kr_etfs"][:3]
    if ke:
        lines.append(("국장 테마", "돈 몰린 곳: " + ", ".join(
            f"{e['name']}({sign(e['wk'])}, 거래대금 {e['dvr']:.1f}배)" for e in ke)))
    inv = p["kr"].get("investors", {}).get("KOSPI")
    if inv:
        lines.append(("국장 수급", "코스피 " + " · ".join(f"{k} {fmt_krw(v)}" for k, v in inv.items())))
    fb = p["kr"].get("foreign_buy")
    if fb:
        lines.append(("외국인 픽", ", ".join(r["name"] for r in fb[:3])))

    lines.append(("시장 체력", f"관심종목 {p['universe']}개 중 {p['breadth']}% 상승, "
                              f"52주 신고가 {p['nh_total']}개"))
    return [dict(k=k, v=v) for k, v in lines]


def render_text(p):
    """메일 본문용 글 보고서. 메일 앱에서 첨부를 열지 않아도 읽을 수 있게 한다."""
    sg = lambda v: f"{v:+.2f}%"
    L = []
    add = L.append
    add(f"{p['title']} 주간 시황 브리핑")
    add(f"미장 {p['week_us']} · 국장 {p['week_kr']}" + (" · 샘플 데이터" if p["demo"] else ""))
    add("")
    if p.get("notes"):
        add("■ 이번 주 방송 포인트")
        for i, n in enumerate(p["notes"], 1):
            add(f"  {i}. {n['h']}")
            add(f"     {n['b'].replace('**', '')}")
        add("")
    add("■ 이번 주 핵심")
    for x in p["summary"]:
        add(f"  · {x['k']}: {x['v']}")

    add("")
    add("■ 지수 (주간 / 1개월)")
    for i in p["indices"]:
        add(f"  {i['name']:<10} {i['last']:>12,.2f}   {sg(i['wk']):>8}   {sg(i['m1']):>8}")
    if p["macro"]:
        add("")
        add("■ 환율 · 금리 · 원자재 (주간)")
        for m in p["macro"]:
            if m["kind"] == "yield":
                add(f"  {m['name']}: {m['last']:.2f}% ({m['chg'] * 100:+.0f}bp)")
            elif m["kind"] == "fx":
                add(f"  {m['name']}: {m['last']:,.1f}원 ({m['chg']:+.1f}원)")
            else:
                add(f"  {m['name']}: {m['last']:,.2f} ({sg(m['wk'])})")

    add("")
    add("■ 미장 섹터 — 돈은 어디로 갔나 (주간 등락 · 거래대금 평소 대비)")
    for r in p["sectors"]:
        flow = "돈 유입" if r["dvr"] >= 1.1 and r["wk"] > 0 else "매도세" if r["dvr"] >= 1.1 else ""
        add(f"  {r['name']:<8} {sg(r['wk']):>8}   {r['dvr']:.1f}배  {flow}")
    if p["styles"]:
        add("")
        add("■ 스타일 대결")
        for x in p["styles"]:
            add(f"  {x['name']}: {x['a']} {sg(x['aw'])} vs {x['b']} {sg(x['bw'])} → {x['win']} 우위")

    add("")
    add("■ 강세 테마 TOP 10 (구성종목 평균 · 거래대금 · 주도주)")
    for t in p["themes"][:10]:
        add(f"  {t['name']:<14} {sg(t['wk']):>8}  {t['dvr']:.1f}배  {', '.join(t['lead'])}")
    add("■ 약세 테마 TOP 5")
    for t in p["themes"][::-1][:5]:
        add(f"  {t['name']:<14} {sg(t['wk']):>8}  {t['dvr']:.1f}배")

    mv = p["movers"]
    for title, rows, extra in (("미장 주간 상승 TOP 10", mv["up"], None),
                               ("미장 주간 하락 TOP 10", mv["down"], None),
                               ("미장 거래대금 급증 TOP 10", mv["flow"], "dvr")):
        add("")
        add(f"■ {title}")
        for r in rows:
            tail = f"  거래대금 {r['dvr']:.1f}배" if extra else ""
            add(f"  {r['sym']:<6} {r['name'][:18]:<18} {sg(r['wk']):>8}  ({r['t']}){tail}")
    if mv["nh"]:
        add("")
        add(f"■ 이번 주 52주 신고가 ({p['nh_total']}개 중 거래대금 상위)")
        add("  " + ", ".join(f"{r['sym']}({r['wk']:+.1f}%)" for r in mv["nh"]))

    k = p["kr"]
    if k.get("investors"):
        add("")
        add("■ 국장 투자자별 순매수 (주간 합계)")
        for mkt, v in k["investors"].items():
            add(f"  {'코스피' if mkt == 'KOSPI' else '코스닥'}: " + " · ".join(f"{a} {fmt_krw(b)}" for a, b in v.items()))
    if p["kr_etfs"]:
        add("")
        add("■ 국장 테마 ETF (주간 등락 · 거래대금 평소 대비)")
        for e in p["kr_etfs"]:
            add(f"  {e['name']:<10} {sg(e['wk']):>8}  {e['dvr']:.1f}배")
    for key, title in (("foreign_buy", "외국인 순매수 TOP"), ("inst_buy", "기관 순매수 TOP")):
        if k.get(key):
            add("")
            add(f"■ {title}")
            add("  " + ", ".join(f"{r['name']}({fmt_krw(r['amt'])})" for r in k[key]))
    for key, title in (("up", "국장 주간 상승 TOP 10"), ("down", "국장 주간 하락 TOP 10"),
                       ("tv_top", "국장 주간 거래대금 TOP 10")):
        if k.get(key):
            add("")
            add(f"■ {title}")
            for r in k[key]:
                add(f"  {r['name']:<12} {r['close']:>10,.0f}원  {sg(r['wk']):>8}  거래대금 {fmt_krw(r['tv']).lstrip('+')}")

    add("")
    add("■ 다음 주 실적 발표")
    add("  " + (", ".join(f"{r['date']} {r['sym']}" for r in p["earnings"]) or "수집된 일정 없음"))
    add("")
    add(f"생성 {p['generated']} · 데이터 yfinance / 네이버 증권 / KRX")
    return "\n".join(L)


def save_pdf(html_path, pdf_path):
    """방송·폰 확인용 PDF. playwright가 없으면 건너뛴다."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("  PDF 생략: playwright 미설치", file=sys.stderr)
        return
    with sync_playwright() as pw:
        exe = os.environ.get("CHROMIUM_PATH")  # 번들 브라우저 대신 쓸 크롬 경로 (선택)
        b = pw.chromium.launch(executable_path=exe) if exe else pw.chromium.launch()
        page = b.new_page(viewport={"width": 1280, "height": 900})
        page.goto("file://" + os.path.abspath(html_path))
        page.wait_for_timeout(500)
        page.pdf(path=pdf_path, format="A4", landscape=True, print_background=True,
                 margin={"top": "10mm", "bottom": "10mm", "left": "8mm", "right": "8mm"})
        b.close()
    print(f"  PDF 생성: {pdf_path}", file=sys.stderr)


def fmt_krw(v):
    s = "+" if v >= 0 else "-"
    a = abs(v)
    return f"{s}{a / 1e12:.2f}조" if a >= 1e12 else f"{s}{a / 1e8:,.0f}억"


# ───────────────────────── 렌더링 ─────────────────────────

PAGE = r"""<title>__TITLE__</title>
<style>
:root{
  --bg:#f4f5f7; --panel:#ffffff; --panel-2:#f7f8fa;
  --ink:#121620; --ink-2:#4a5260; --ink-3:#7b8491;
  --line:#dfe3ea; --grid:#eceef2;
  --up:#d0342c; --down:#1f5ed0; --mid:#b9bec7;
  --up-bg:rgba(208,52,44,.08); --down-bg:rgba(31,94,208,.08);
  --accent:#121620;
  --shadow:0 1px 2px rgba(18,26,42,.05),0 12px 30px -18px rgba(18,26,42,.25);
}
@media (prefers-color-scheme: dark){
  :root:not([data-theme="light"]){
    --bg:#101217; --panel:#181b22; --panel-2:#1e222a;
    --ink:#f2f4f7; --ink-2:#b4bac5; --ink-3:#848b97;
    --line:#2b303a; --grid:#242831;
    --up:#f0605a; --down:#5b93f0; --mid:#4a505c;
    --up-bg:rgba(240,96,90,.12); --down-bg:rgba(91,147,240,.12);
    --accent:#f2f4f7;
    --shadow:0 1px 2px rgba(0,0,0,.3),0 12px 30px -18px rgba(0,0,0,.6);
  }
}
:root[data-theme="dark"]{
  --bg:#101217; --panel:#181b22; --panel-2:#1e222a;
  --ink:#f2f4f7; --ink-2:#b4bac5; --ink-3:#848b97;
  --line:#2b303a; --grid:#242831;
  --up:#f0605a; --down:#5b93f0; --mid:#4a505c;
  --up-bg:rgba(240,96,90,.12); --down-bg:rgba(91,147,240,.12);
  --accent:#f2f4f7;
  --shadow:0 1px 2px rgba(0,0,0,.3),0 12px 30px -18px rgba(0,0,0,.6);
}
*{box-sizing:border-box}
html{scroll-behavior:smooth;scroll-padding-top:64px}
body{margin:0;background:var(--bg);color:var(--ink);
  font:15px/1.5 "Pretendard","Apple SD Gothic Neo","Noto Sans KR","Malgun Gothic",system-ui,sans-serif;
  font-variant-numeric:tabular-nums;-webkit-font-smoothing:antialiased}
.nav{position:sticky;top:0;z-index:10;display:flex;gap:6px;align-items:center;
  padding:10px 16px;background:color-mix(in srgb,var(--bg) 88%,transparent);
  backdrop-filter:blur(10px);border-bottom:1px solid var(--line);overflow-x:auto;scrollbar-width:none}
.nav a{flex:none;padding:6px 12px;border-radius:999px;color:var(--ink-2);text-decoration:none;
  font-size:13px;font-weight:600;border:1px solid transparent}
.nav a:hover{color:var(--ink)}
.nav a.on{background:var(--panel);color:var(--ink);border-color:var(--line)}
.nav .sp{flex:1}
.nav button{flex:none;font:inherit;font-size:13px;padding:6px 10px;border-radius:8px;
  border:1px solid var(--line);background:var(--panel);color:var(--ink-2);cursor:pointer}
main{max-width:1280px;margin:0 auto;padding:0 16px 80px}
section{min-height:calc(100vh - 56px);padding:40px 0 24px;border-bottom:1px dashed var(--line)}
section:last-child{border-bottom:0}
.eyebrow{font-size:13px;font-weight:700;letter-spacing:.08em;color:var(--ink-3)}
h1{font-size:clamp(32px,5vw,56px);line-height:1.1;margin:8px 0 6px;letter-spacing:-.02em}
h2{font-size:clamp(24px,3.2vw,36px);margin:6px 0 4px;letter-spacing:-.01em}
.lede{color:var(--ink-2);font-size:16px;margin:0 0 24px}
.demo{display:inline-block;margin-left:8px;padding:2px 8px;border-radius:6px;font-size:12px;
  background:var(--up-bg);color:var(--up);font-weight:700;vertical-align:middle}
.grid{display:grid;gap:14px}
.g2{grid-template-columns:repeat(auto-fit,minmax(min(100%,420px),1fr))}
.g3{grid-template-columns:repeat(auto-fit,minmax(min(100%,300px),1fr))}
.g4{grid-template-columns:repeat(auto-fit,minmax(min(100%,160px),1fr))}
.card{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:18px;box-shadow:var(--shadow);min-width:0}
.card h3{margin:0 0 2px;font-size:16px}
.card .sub{color:var(--ink-3);font-size:12.5px;margin:0 0 12px}
.up{color:var(--up)} .down{color:var(--down)} .muted{color:var(--ink-3)}

/* 요약 */
.sum{display:grid;gap:10px;margin-top:28px}
.sum div{display:grid;grid-template-columns:110px 1fr;gap:14px;align-items:baseline;
  padding:14px 18px;background:var(--panel);border:1px solid var(--line);border-radius:12px;font-size:clamp(15px,1.6vw,19px)}
.sum b{font-size:13px;color:var(--ink-3);font-weight:700}
@media (max-width:560px){.sum div{grid-template-columns:1fr;gap:2px}}

/* 타일 */
.tile .nm{font-size:13px;color:var(--ink-2);font-weight:600}
.tile .v{font-size:clamp(20px,2.1vw,26px);white-space:nowrap;font-weight:800;letter-spacing:-.01em;margin-top:2px}
.tile .c{font-size:15px;font-weight:700}
.tile svg{display:block;width:100%;height:44px;margin-top:8px}
.tile.big .v{font-size:32px}
.tag{display:inline-block;font-size:11px;font-weight:700;color:var(--ink-3);border:1px solid var(--line);
  border-radius:5px;padding:0 5px;margin-left:6px;vertical-align:1px}

/* 막대 */
.bars{display:grid;gap:4px}
.bar{display:grid;grid-template-columns:minmax(80px,32%) 1fr;gap:10px;align-items:center;
  min-height:28px;border-radius:6px;padding:0 4px;cursor:default}
.bar:hover{background:var(--panel-2)}
.bar .l{font-size:13.5px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.bar .l small{color:var(--ink-3);font-weight:500;margin-left:4px}
.bar svg{width:100%;height:22px;display:block;overflow:visible}

/* 표 */
table{width:100%;border-collapse:collapse;font-size:14px}
th{font-size:12px;color:var(--ink-3);font-weight:600;text-align:right;white-space:nowrap;padding:6px 6px;border-bottom:1px solid var(--line)}
td{padding:7px 6px;border-bottom:1px solid var(--grid);text-align:right;white-space:nowrap}
th:first-child,td:first-child{text-align:left}
td .n{font-weight:700} td .s{color:var(--ink-3);font-size:12px;margin-left:6px}
td .t{color:var(--ink-3);font-size:12px}
tr:hover td{background:var(--panel-2)}
.tbl{overflow-x:auto}
.chip{display:inline-block;padding:4px 10px;margin:0 6px 6px 0;border-radius:999px;border:1px solid var(--line);
  background:var(--panel-2);font-size:13px;font-weight:600}
.chip i{font-style:normal;margin-left:4px}

/* 스타일 대결 */
.vs{display:grid;grid-template-columns:1fr auto 1fr;gap:8px;align-items:center;text-align:center}
.vs .side{padding:10px;border-radius:10px;background:var(--panel-2)}
.vs .side.win{outline:2px solid var(--ink)}
.vs .side b{display:block;font-size:13px;color:var(--ink-2)}
.vs .side span{font-size:20px;font-weight:800}
.vs em{font-style:normal;color:var(--ink-3);font-size:12px;font-weight:700}

/* 산점도 */
.scatter{position:relative}
.scatter svg{width:100%;display:block;overflow:visible}
.scatter .ql{font-size:12px;font-weight:700;fill:var(--ink-3)}
.scatter .lab{font-size:12px;font-weight:600;fill:var(--ink);paint-order:stroke;stroke:var(--panel);stroke-width:4px;stroke-linejoin:round}
.scatter .ax{font-size:11px;fill:var(--ink-3)}
.legend{display:flex;gap:14px;flex-wrap:wrap;font-size:12.5px;color:var(--ink-2);margin-top:6px}
.legend span::before{content:"";display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:6px;vertical-align:-1px;background:var(--c)}

.tip{position:fixed;z-index:50;pointer-events:none;background:var(--panel);color:var(--ink);border:1px solid var(--line);
  border-radius:10px;padding:8px 10px;font-size:12.5px;box-shadow:var(--shadow);max-width:260px;opacity:0;transition:opacity .08s}
.tip b{display:block;font-size:13px;margin-bottom:2px}
.note{min-height:140px;padding:14px;border:1px dashed var(--line);border-radius:10px;background:var(--panel-2);outline:none;font-size:16px;white-space:pre-wrap}
.story{display:grid;gap:12px;margin:0;padding:0;list-style:none;counter-reset:st}
.story li{display:grid;grid-template-columns:44px 1fr;gap:4px 14px;padding:18px 20px;background:var(--panel);
  border:1px solid var(--line);border-radius:14px;counter-increment:st}
.story li::before{content:counter(st);grid-row:span 3;font-size:28px;font-weight:800;color:var(--ink-3);line-height:1.1}
.story .tag{justify-self:start;margin:0;font-size:11.5px}
.story h3{margin:0;font-size:clamp(17px,2vw,21px);line-height:1.35;text-wrap:balance}
.story p{margin:4px 0 0;color:var(--ink-2);font-size:15.5px;line-height:1.7;max-width:70ch}
.story b{color:var(--ink)}
.empty{color:var(--ink-3);font-size:14px;padding:12px 0}
footer{color:var(--ink-3);font-size:12px;text-align:center;padding:20px}

@media print{
  .nav{display:none} body{font-size:13px}
  section{min-height:0;padding:12px 0;border:0;break-before:page}
  section:first-of-type{break-before:auto}
  .card,.sum div,.bar,tr{break-inside:avoid}
  .card{box-shadow:none}
  .note{min-height:60px}
}
</style>

<nav class="nav" id="nav"></nav>
<main id="app"></main>
<div class="tip" id="tip"></div>
<footer id="foot"></footer>

<script>
const D = __DATA__;
(function(){
const $ = s => document.querySelector(s);
const esc = s => String(s).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const cls = v => v > 0 ? "up" : v < 0 ? "down" : "muted";
const pc = (v, d=2) => (v > 0 ? "+" : "") + v.toFixed(d) + "%";
const tri = v => v > 0 ? "▲" : v < 0 ? "▼" : "–";
const krw = v => { const a = Math.abs(v), s = v >= 0 ? "+" : "-";
  return a >= 1e12 ? s + (a/1e12).toFixed(2) + "조" : s + Math.round(a/1e8).toLocaleString() + "억"; };
const krwAbs = v => v >= 1e12 ? (v/1e12).toFixed(1) + "조" : Math.round(v/1e8).toLocaleString() + "억";
const usd = v => v >= 1e9 ? "$" + (v/1e9).toFixed(1) + "B" : "$" + Math.round(v/1e6) + "M";
const num = (v, d=2) => v.toLocaleString(undefined, {minimumFractionDigits:d, maximumFractionDigits:d});

function fmtMacro(m){
  if (m.kind === "fx") return {v: num(m.last,1) + "원", c: (m.chg>0?"+":"") + num(m.chg,1) + "원"};
  if (m.kind === "yield") return {v: num(m.last,2) + "%", c: (m.chg>0?"+":"") + Math.round(m.chg*100) + "bp"};
  if (m.kind === "usd0") return {v: "$" + num(m.last,0), c: pc(m.wk)};
  if (m.kind === "usd") return {v: "$" + num(m.last,2), c: pc(m.wk)};
  return {v: num(m.last,2), c: pc(m.wk)};
}

/* ── 툴팁 ── */
const tip = $("#tip");
function bindTip(el, html){
  el.addEventListener("mousemove", e => {
    tip.innerHTML = html; tip.style.opacity = 1;
    const w = tip.offsetWidth, h = tip.offsetHeight;
    let x = e.clientX + 14, y = e.clientY + 14;
    if (x + w > innerWidth - 8) x = e.clientX - w - 14;
    if (y + h > innerHeight - 8) y = e.clientY - h - 14;
    tip.style.left = x + "px"; tip.style.top = y + "px";
  });
  el.addEventListener("mouseleave", () => tip.style.opacity = 0);
}

/* ── 스파크라인 ── */
function spark(vals, wk){
  if (!vals || vals.length < 2) return "";
  const W = 200, H = 44, lo = Math.min(...vals), hi = Math.max(...vals), r = (hi - lo) || 1;
  const pts = vals.map((v, i) => [i / (vals.length - 1) * W, H - 3 - (v - lo) / r * (H - 6)]);
  const d = pts.map((p, i) => (i ? "L" : "M") + p[0].toFixed(1) + " " + p[1].toFixed(1)).join("");
  const c = wk >= 0 ? "var(--up)" : "var(--down)";
  const wx = pts[Math.max(0, pts.length - 6)][0];
  return `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" aria-hidden="true">
    <rect x="${wx}" y="0" width="${W - wx}" height="${H}" fill="var(--panel-2)"/>
    <path d="${d}" fill="none" stroke="${c}" stroke-width="2" vector-effect="non-scaling-stroke" stroke-linejoin="round"/></svg>`;
}

/* ── 발산형 가로 막대 (0 기준) ── */
function divBars(rows, opt = {}){
  if (!rows.length) return `<div class="empty">데이터 없음</div>`;
  const key = opt.key || "wk", fmt = opt.fmt || (v => pc(v));
  const m = Math.max(...rows.map(r => Math.abs(r[key])), 0.01);
  // 부호가 한쪽뿐이면 0선을 가장자리로 옮겨 폭을 다 쓴다
  const hasP = rows.some(r => r[key] > 0), hasN = rows.some(r => r[key] < 0);
  const z = hasP && hasN ? 50 : hasN ? 84 : 0, span = hasP && hasN ? 38 : 70;
  const wrap = document.createElement("div"); wrap.className = "bars";
  rows.forEach(r => {
    const v = r[key], w = Math.abs(v) / m * span, pos = v >= 0;
    const x = pos ? z : z - w, c = pos ? "var(--up)" : "var(--down)";
    // 둥근 끝은 데이터 쪽에만: 0선 쪽은 각지게 덮는다
    const flat = pos ? `<rect x="${x}%" y="4" width="${Math.min(w, 1)}%" height="14" fill="${c}"/>`
                     : `<rect x="${Math.max(x + w - 1, x)}%" y="4" width="${Math.min(w, 1)}%" height="14" fill="${c}"/>`;
    const lx = pos ? `${z + w + 1}%` : `${z - w - 1}%`;
    const el = document.createElement("div"); el.className = "bar";
    el.innerHTML = `<div class="l">${esc(r.label)}${r.small ? `<small>${esc(r.small)}</small>` : ""}</div>
      <svg role="img" aria-label="${esc(r.label)} ${fmt(v)}">
        <line x1="${z}%" x2="${z}%" y1="0" y2="22" stroke="var(--mid)" stroke-width="1"/>
        <rect x="${x}%" y="4" width="${Math.max(w, .3)}%" height="14" rx="4" fill="${c}"/>${flat}
        <text x="${lx}" y="15.5" font-size="12.5" font-weight="700" fill="var(--ink)" text-anchor="${pos ? "start" : "end"}">${fmt(v)}</text>
      </svg>`;
    if (r.tip) bindTip(el, r.tip);
    wrap.appendChild(el);
  });
  return wrap;
}

/* ── 섹션 골격 ── */
const app = $("#app"), nav = $("#nav"), secs = [];
function section(id, eyebrow, title, lede){
  const s = document.createElement("section"); s.id = id;
  s.innerHTML = `<div class="eyebrow">${esc(eyebrow)}</div><h2>${esc(title)}</h2>${lede ? `<p class="lede">${lede}</p>` : ""}`;
  app.appendChild(s); secs.push([id, eyebrow]); return s;
}
function card(parent, title, sub, body){
  const c = document.createElement("div"); c.className = "card";
  c.innerHTML = `<h3>${esc(title)}</h3>${sub ? `<p class="sub">${sub}</p>` : ""}`;
  if (typeof body === "string") c.insertAdjacentHTML("beforeend", body); else if (body) c.appendChild(body);
  parent.appendChild(c); return c;
}
function grid(parent, k){ const g = document.createElement("div"); g.className = "grid " + k; parent.appendChild(g); return g; }

const idx = D.indices, byG = g => idx.filter(i => i.g === g);

/* 1. 오프닝 */
{
  const s = document.createElement("section"); s.id = "open";
  s.innerHTML = `<div class="eyebrow">WEEKLY LIVE · 미장 ${esc(D.week_us)} · 국장 ${esc(D.week_kr)}</div>
    <h1>${esc(D.title)} 주간 시황${D.demo ? `<span class="demo">샘플 데이터</span>` : ""}</h1>
    <p class="lede">이번 주 한눈에 보기 — 지수, 돈의 흐름, 특징주</p>`;
  const g = grid(s, "g4");
  idx.forEach(i => g.insertAdjacentHTML("beforeend",
    `<div class="card tile big"><div class="nm">${esc(i.name)}<span class="tag">${i.g}</span></div>
     <div class="v">${num(i.last, i.last > 1000 ? 0 : 2)}</div>
     <div class="c ${cls(i.wk)}">${tri(i.wk)} ${pc(i.wk)} <span class="muted" style="font-weight:500;font-size:12.5px">1개월 ${pc(i.m1,1)}</span></div>
     ${spark(i.spark, i.wk)}</div>`));
  const sm = document.createElement("div"); sm.className = "sum";
  D.summary.forEach(x => sm.insertAdjacentHTML("beforeend", `<div><b>${esc(x.k)}</b><span>${esc(x.v)}</span></div>`));
  s.appendChild(sm);
  app.appendChild(s); secs.push(["open", "오프닝"]);
}

/* 1-1. 방송 원고 */
if (D.notes && D.notes.length) {
  const s = section("story", "방송 포인트", "이번 주 방송 포인트", D.notes_lede ? esc(D.notes_lede) : "방송 순서대로 정리한 이번 주 이야기");
  const ol = document.createElement("ol"); ol.className = "story";
  // 본문은 **굵게**만 허용
  const md = t => esc(t).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>");
  D.notes.forEach(n => ol.insertAdjacentHTML("beforeend",
    `<li>${n.tag ? `<span class="tag">${esc(n.tag)}</span>` : ""}<h3>${esc(n.h)}</h3><p>${md(n.b)}</p></li>`));
  s.appendChild(ol);
}

/* 2. 매크로 */
{
  const s = section("macro", "MACRO", "환율 · 금리 · 원자재", "음영 구간이 이번 주. 금리·달러가 오르면 성장주엔 부담, 환율이 오르면 외국인 수급에 부담.");
  const g = grid(s, "g4");
  D.macro.forEach(m => { const f = fmtMacro(m);
    g.insertAdjacentHTML("beforeend", `<div class="card tile"><div class="nm">${esc(m.name)}</div>
      <div class="v">${f.v}</div><div class="c ${cls(m.wk)}">${tri(m.wk)} ${f.c}</div>${spark(m.spark, m.wk)}</div>`); });
}

/* 3. 미장 섹터 */
{
  const s = section("sector", "US · SECTOR", "미장 섹터 — 돈은 어디로 갔나",
    "섹터 ETF 주간 등락. 괄호는 거래대금이 평소(직전 20일 평균)의 몇 배였는지 — 1배를 넘으면서 오르면 '돈이 들어온' 섹터.");
  const g = grid(s, "g2");
  card(g, "11개 섹터 주간 등락", "S&P500 섹터 SPDR ETF",
    divBars(D.sectors.map(r => ({label: r.name, small: `${r.sym} · ${r.dvr.toFixed(1)}배`, wk: r.wk,
      tip: `<b>${esc(r.name)} (${r.sym})</b>주간 ${pc(r.wk)} · 1개월 ${pc(r.m1)}<br>거래대금 평소 대비 ${r.dvr.toFixed(2)}배`}))));
  const st = card(g, "스타일 대결", "어떤 성격의 주식이 이겼나 (주간 수익률)", "");
  st.insertAdjacentHTML("beforeend", `<div class="grid" style="gap:12px">` + D.styles.map(x => `
    <div><div class="sub" style="margin:0 0 6px;font-weight:600;color:var(--ink-2)">${esc(x.name)}</div>
    <div class="vs"><div class="side ${x.win === x.a ? "win" : ""}"><b>${esc(x.a)}</b><span class="${cls(x.aw)}">${pc(x.aw)}</span></div>
    <em>VS</em><div class="side ${x.win === x.b ? "win" : ""}"><b>${esc(x.b)}</b><span class="${cls(x.bw)}">${pc(x.bw)}</span></div></div></div>`).join("") + `</div>`);
}

/* 4. 머니플로우 맵 */
{
  const s = section("flow", "US · MONEY FLOW", "테마 머니플로우 맵",
    `관심 테마 ${D.themes.length}개를 <b>가로=주간 등락</b>, <b>세로=거래대금 증감</b>으로 찍었다. 오른쪽 위가 '돈 들어오며 오른' 테마.`);
  const c = card(s, "테마별 등락 × 거래대금", "점에 마우스를 올리면 테마 상세", "");
  const box = document.createElement("div"); box.className = "scatter"; c.appendChild(box);
  const T = D.themes, W = 1000, H = 520, P = {l: 48, r: 20, t: 20, b: 36};
  const xs = T.map(t => t.wk), ys = T.map(t => Math.min(t.dvr, 3));
  const xm = Math.max(1, ...xs.map(Math.abs)) * 1.1;
  const y0 = Math.min(0.5, ...ys) - 0.05, y1 = Math.max(1.6, ...ys) + 0.1;
  const X = v => P.l + (v + xm) / (2 * xm) * (W - P.l - P.r);
  const Y = v => P.t + (1 - (Math.min(v, 3) - y0) / (y1 - y0)) * (H - P.t - P.b);
  let svg = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="테마 머니플로우 산점도">`;
  [-xm*.66, -xm*.33, xm*.33, xm*.66].forEach(v =>
    svg += `<line x1="${X(v)}" x2="${X(v)}" y1="${P.t}" y2="${H-P.b}" stroke="var(--grid)"/><text class="ax" x="${X(v)}" y="${H-P.b+18}" text-anchor="middle">${pc(v,1)}</text>`);
  for (let v = Math.ceil(y0*2)/2; v <= y1; v += 0.5)
    svg += `<line x1="${P.l}" x2="${W-P.r}" y1="${Y(v)}" y2="${Y(v)}" stroke="var(--grid)"/><text class="ax" x="${P.l-8}" y="${Y(v)+4}" text-anchor="end">${v.toFixed(1)}배</text>`;
  svg += `<line x1="${X(0)}" x2="${X(0)}" y1="${P.t}" y2="${H-P.b}" stroke="var(--mid)"/>
    <line x1="${P.l}" x2="${W-P.r}" y1="${Y(1)}" y2="${Y(1)}" stroke="var(--mid)" stroke-dasharray="4 4"/>
    <text class="ql" x="${W-P.r-6}" y="${P.t+14}" text-anchor="end">돈 들어오며 상승 ↗</text>
    <text class="ql" x="${P.l+6}" y="${P.t+14}">돈 들어오며 하락 (매도세) ↖</text>
    <text class="ql" x="${W-P.r-6}" y="${H-P.b-8}" text-anchor="end">조용한 상승 ↘</text>
    <text class="ql" x="${P.l+6}" y="${H-P.b-8}">소외 ↙</text>`;
  const score = t => Math.abs(t.wk) * Math.max(t.dvr, 0.5);
  const lab = new Set([...T].sort((a, b) => score(b) - score(a)).slice(0, 10).map(t => t.name));
  const placed = [];
  // 라벨은 점수 높은 순으로 자리를 잡는다 (겹치면 생략, 툴팁으로 확인)
  T.map((t, i) => [t, i]).sort((a, b) => score(b[0]) - score(a[0])).forEach(([t, i]) => {
    const cx = X(t.wk), cy = Y(t.dvr), r = 5 + Math.sqrt(t.n) * 1.2;
    svg += `<circle data-i="${i}" cx="${cx}" cy="${cy}" r="${r}" fill="${t.wk >= 0 ? "var(--up)" : "var(--down)"}" fill-opacity=".78" stroke="var(--panel)" stroke-width="2"/>`;
    const near = placed.some(([px, py]) => Math.abs(px - cx) < 150 && Math.abs(py - cy) < 18);
    if (lab.has(t.name) && !near && (placed.push([cx, cy]), true)) svg += `<text class="lab" x="${cx + (cx > W*.8 ? -r-4 : r+4)}" y="${cy+4}" text-anchor="${cx > W*.8 ? "end" : "start"}">${esc(t.name)}</text>`;
  });
  box.innerHTML = svg + `</svg>`;
  box.insertAdjacentHTML("beforeend", `<div class="legend"><span style="--c:var(--up)">주간 상승 테마</span><span style="--c:var(--down)">주간 하락 테마</span><span class="muted">점 크기 = 종목 수 · 세로 3배 이상은 위쪽 끝에 표시</span></div>`);
  box.querySelectorAll("circle").forEach(el => { const t = T[+el.dataset.i];
    bindTip(el, `<b>${esc(t.name)}</b><span class="muted">${esc(t.g)} · ${t.n}종목</span><br>평균 ${pc(t.wk)} · 상승비율 ${t.up}%<br>거래대금 ${t.dvr.toFixed(2)}배<br>주도주 ${t.lead.map(esc).join(", ")}`); });

  const g = grid(s, "g2"); g.style.marginTop = "14px";
  const trow = t => ({label: t.name, small: t.lead.slice(0, 2).join(" "), wk: t.wk,
    tip: `<b>${esc(t.name)}</b>평균 ${pc(t.wk)} · 상승 ${t.up}%<br>거래대금 ${t.dvr.toFixed(2)}배<br>주도주 ${t.lead.map(esc).join(", ")}`});
  card(g, "강세 테마 TOP 10", "구성종목 평균 주간 등락", divBars(T.slice(0, 10).map(trow)));
  card(g, "약세 테마 TOP 10", "구성종목 평균 주간 등락", divBars(T.slice(-10).reverse().map(trow)));
}

/* 5. 미장 특징주 */
{
  const s = section("us", "US · MOVERS", "미장 특징주",
    `관심종목 ${D.universe}개 중 일평균 거래대금 $20M 이상. 이번 주 52주 신고가 <b>${D.nh_total}개</b>, 상승 종목 비율 <b>${D.breadth}%</b>.`);
  const g = grid(s, "g3");
  const tbl = (rows, extra) => `<div class="tbl"><table><thead><tr><th>종목</th><th>종가</th><th>주간</th><th>${extra[0]}</th></tr></thead><tbody>` +
    rows.map(r => `<tr><td><span class="n">${esc(r.sym)}</span><span class="s">${esc(r.name)}</span><br><span class="t">${esc(r.t)}</span></td>
      <td>$${num(r.close)}</td><td class="${cls(r.wk)}"><b>${pc(r.wk,1)}</b></td><td>${extra[1](r)}</td></tr>`).join("") + `</tbody></table></div>`;
  const dvr = ["거래대금", r => `${r.dvr.toFixed(1)}배`];
  card(g, "주간 상승 TOP 10", "", tbl(D.movers.up, dvr));
  card(g, "주간 하락 TOP 10", "", tbl(D.movers.down, dvr));
  card(g, "거래대금 급증 TOP 10", "평소 대비 거래대금이 가장 많이 늘어난 종목 — 뉴스·수급 체크 대상", tbl(D.movers.flow, ["일평균", r => usd(r.dv)]));
  card(s, "이번 주 52주 신고가", "주간 등락 순", D.movers.nh.length ?
    `<div>` + D.movers.nh.map(r => `<span class="chip">${esc(r.sym)}<i class="${cls(r.wk)}">${pc(r.wk,1)}</i></span>`).join("") + `</div>`
    : `<div class="empty">신고가 종목 없음</div>`).style.marginTop = "14px";
}

/* 6. 국장 수급 */
{
  const K = D.kr;
  const s = section("krflow", "KR · FLOW", "국장 수급 — 누가 샀나, 어디로 갔나", `기간 ${esc(K.period || D.week_kr)}.`);
  const inv = Object.entries(K.investors || {});
  if (inv.length) {
    const g = grid(s, "g2");
    inv.forEach(([mkt, v]) =>
      card(g, `${mkt === "KOSPI" ? "코스피" : "코스닥"} 투자자별 순매수`, "주간 합계",
        divBars(Object.entries(v).map(([k, a]) => ({label: k, wk: a})), {fmt: krw})));
  } else {
    s.insertAdjacentHTML("beforeend", `<div class="card empty">투자자별 순매수 데이터를 받지 못했습니다.</div>`);
  }
  if (D.kr_etfs.length) {
    const c = card(s, "국장 테마 ETF 주간 등락", "괄호는 거래대금이 평소(직전 20일 평균)의 몇 배였는지 — 미장 섹터와 같은 기준",
      divBars(D.kr_etfs.map(r => ({label: r.name, small: `${r.dvr.toFixed(1)}배`, wk: r.wk,
        tip: `<b>${esc(r.name)} ETF (${r.sym})</b>주간 ${pc(r.wk)}<br>거래대금 평소 대비 ${r.dvr.toFixed(2)}배`}))));
    c.style.marginTop = "14px";
  }
  {
    const list = (rows) => `<div class="tbl"><table><tbody>` + rows.map((r, i) =>
      `<tr><td><span class="t">${i+1}</span> <span class="n">${esc(r.name)}</span></td><td class="${cls(r.amt)}"><b>${krw(r.amt)}</b></td></tr>`).join("") + `</tbody></table></div>`;
    const lists = [["외국인 순매수 TOP", K.foreign_buy], ["외국인 순매도 TOP", K.foreign_sell],
                   ["기관 순매수 TOP", K.inst_buy], ["기관 순매도 TOP", K.inst_sell]].filter(x => x[1] && x[1].length);
    if (lists.length) {
      const g2 = grid(s, "g4"); g2.style.marginTop = "14px";
      lists.forEach(([t, rows]) => card(g2, t, "", list(rows)));
    }
    if (K.sectors) {
      const top = K.sectors.slice(0, 8), bot = K.sectors.slice(-5).filter(r => !top.includes(r));
      const c = card(s, "코스피 업종 주간 등락", "강한 업종 8 · 약한 업종 5",
        divBars([...top, ...bot].map(r => ({label: r.name, wk: r.wk}))));
      c.style.marginTop = "14px";
    }
  }
}

/* 7. 국장 특징주 */
{
  const K = D.kr;
  const s = section("kr", "KR · MOVERS", "국장 특징주", esc(K.movers_src || "코스피+코스닥, 시가총액 3,000억 이상") + ".");
  if (!K.up) {
    s.insertAdjacentHTML("beforeend", `<div class="card empty">국장 종목 데이터를 받지 못했습니다.</div>`);
  } else {
    const g = grid(s, "g3");
    const tbl = (rows, last) => `<div class="tbl"><table><thead><tr><th>종목</th><th>종가</th><th>주간</th><th>${last}</th></tr></thead><tbody>` +
      rows.map(r => `<tr><td><span class="n">${esc(r.name)}</span></td><td>${Math.round(r.close).toLocaleString()}</td>
        <td class="${cls(r.wk)}"><b>${pc(r.wk,1)}</b></td><td>${krwAbs(r.tv)}</td></tr>`).join("") + `</tbody></table></div>`;
    card(g, "주간 상승 TOP 10", "", tbl(K.up, "거래대금"));
    card(g, "주간 하락 TOP 10", "", tbl(K.down, "거래대금"));
    card(g, "주간 거래대금 TOP 10", "돈이 가장 많이 오간 종목", tbl(K.tv_top, "거래대금"));
  }
}

/* 8. 다음 주 */
{
  const s = section("next", "NEXT WEEK", "다음 주 체크포인트", "실적 발표는 자동 수집, 경제지표·이벤트는 직접 적어두세요 (이 브라우저에 저장됩니다).");
  const g = grid(s, "g2");
  card(g, "실적 발표 예정", "관심종목 중 거래대금 상위", D.earnings.length ?
    `<div>` + D.earnings.map(r => `<span class="chip">${esc(r.date)} · ${esc(r.sym)}<i class="muted">${esc(r.name)}</i></span>`).join("") + `</div>`
    : `<div class="empty">수집된 일정 없음</div>`);
  const c = card(g, "방송 메모", "FOMC · CPI · 고용지표 · 옵션만기 등", `<div class="note" contenteditable="true" id="note"></div>`);
  const KEY = "weekly-brief-note-" + D.title;
  const note = c.querySelector("#note");
  try { note.textContent = localStorage.getItem(KEY) || ""; } catch (e) {}
  note.addEventListener("input", () => { try { localStorage.setItem(KEY, note.textContent); } catch (e) {} });
}

/* ── 내비 / 키보드 ── */
nav.innerHTML = secs.map(([id, n]) => `<a href="#${id}" data-id="${id}">${esc(n)}</a>`).join("") +
  `<span class="sp"></span><button id="theme" type="button">테마</button>`;
$("#theme").onclick = () => {
  const r = document.documentElement, dark = r.dataset.theme ? r.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
  r.dataset.theme = dark ? "light" : "dark";
};
const links = [...nav.querySelectorAll("a")];
const io = new IntersectionObserver(es => es.forEach(e => { if (e.isIntersecting)
  links.forEach(a => a.classList.toggle("on", a.dataset.id === e.target.id)); }), {rootMargin: "-40% 0px -55% 0px"});
document.querySelectorAll("section").forEach(s => io.observe(s));
addEventListener("keydown", e => {
  if (e.target.isContentEditable) return;
  const all = [...document.querySelectorAll("section")];
  const cur = all.findIndex(s => s.getBoundingClientRect().top > 80) - 1;
  const at = cur < 0 ? all.length - 1 : cur;
  if (["ArrowRight", "PageDown", "j"].includes(e.key)) { e.preventDefault(); all[Math.min(at + 1, all.length - 1)].scrollIntoView(); }
  if (["ArrowLeft", "PageUp", "k"].includes(e.key)) { e.preventDefault(); all[Math.max(at - 1, 0)].scrollIntoView(); }
});
$("#foot").textContent = `생성 ${D.generated} · 데이터 yfinance / KRX(pykrx) · ←/→ 키로 섹션 이동` + (D.demo ? " · 샘플 데이터(실제 시세 아님)" : "");
})();
</script>
"""


def render_html(payload):
    def clean(o):
        if isinstance(o, float):
            return 0.0 if math.isnan(o) or math.isinf(o) else o
        if isinstance(o, dict):
            return {k: clean(v) for k, v in o.items()}
        if isinstance(o, list):
            return [clean(v) for v in o]
        return o
    data = json.dumps(clean(payload), separators=(",", ":"), ensure_ascii=False)
    data = data.replace("<", "\\u003c").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    title = f"{payload.get('title', '')} 주간 시황".strip()
    return PAGE.replace("__TITLE__", title.replace("<", "")).replace("__DATA__", data)


def main():
    ap = argparse.ArgumentParser(description="주간 시황 방송 자료 HTML 생성")
    ap.add_argument("--demo", action="store_true", help="샘플 데이터로 생성 (레이아웃 확인용)")
    ap.add_argument("--output", "-o", default="weekly_brief.html", help="출력 HTML 경로")
    ap.add_argument("--no-kr", action="store_true", help="국장 수급 생략")
    ap.add_argument("--no-earnings", action="store_true", help="다음 주 실적 일정 생략")
    ap.add_argument("--text", help="글 보고서(.txt) 경로 — 메일 본문용")
    ap.add_argument("--pdf", help="PDF 경로 (playwright 필요)")
    ap.add_argument("--json", help="집계 데이터(.json) 저장 경로")
    ap.add_argument("--from-json", help="저장해 둔 집계 데이터로 다시 그리기 (수집 생략)")
    ap.add_argument("--notes", help="방송 원고 JSON ([{tag,h,b}, ...]) — 페이지 앞부분에 넣는다")
    args = ap.parse_args()

    if args.from_json:
        with open(args.from_json, encoding="utf-8") as f:
            payload = json.load(f)
        if args.notes:
            with open(args.notes, encoding="utf-8") as f:
                payload["notes"] = json.load(f)
        write_outputs(payload, args)
        return

    theme_syms = sorted({s for syms in US_THEMES.values() for s in syms})
    extra = [s for s, *_ in INDICES] + [s for s, *_ in MACRO] + [s for s, _ in SECTORS] \
        + [x for a, b, *_ in STYLES for x in (a, b)] + [s for s, _ in KR_ETFS] + KOSPI + KOSDAQ
    symbols = sorted(set(theme_syms + extra))

    if args.demo:
        frames, kr, earnings = demo_frames(symbols), demo_kr(), [
            dict(sym="MU", name="Micron", date="09/29 (Mon)"),
            dict(sym="NKE", name="Nike", date="10/01 (Wed)"),
            dict(sym="STZ", name="Constellation", date="10/02 (Thu)")]
    else:
        frames = fetch_us(symbols)
        if "^GSPC" not in frames:
            raise SystemExit("S&P500 데이터를 받지 못해 중단합니다")
        kr = {}
        if not args.no_kr and "^KS11" in frames:
            kr_week, kr_prev = week_split(frames["^KS11"].index)
            # pykrx는 KRX 로그인(KRX_ID/KRX_PW)이 있어야 동작한다
            if os.environ.get("KRX_ID") and os.environ.get("KRX_PW"):
                try:
                    kr = fetch_kr(kr_week, kr_prev)
                except Exception as e:
                    print(f"  [국장] pykrx 수집 실패: {e}", file=sys.stderr)
            else:
                print("  [국장] KRX 계정 없음 — 네이버/yfinance 대체 경로 사용", file=sys.stderr)
            kr.setdefault("period", f"{kr_week[0]:%m/%d}~{kr_week[-1]:%m/%d}")
            if not kr.get("investors"):
                kr["investors"] = fetch_naver_investors(kr_week)
            if not kr.get("up"):
                kr.update(kr_movers_from_frames(frames, kr_week, kr_prev))
        earnings = []
        if not args.no_earnings:
            last = frames["^GSPC"].index[-1].date()
            nxt_mon = last + timedelta(days=7 - last.weekday())
            week, prev_day = week_split(frames["^GSPC"].index)
            by_dv = []
            for s in theme_syms:
                if s in frames:
                    st = stats(frames[s], week, prev_day)
                    if st:
                        by_dv.append((st["dv"], s))
            top = [s for _, s in sorted(by_dv, reverse=True)[:80]]
            print(f"  [미장] 다음 주 실적 일정 조회 ({len(top)}종목)", file=sys.stderr)
            earnings = fetch_earnings(top, nxt_mon, nxt_mon + timedelta(days=4))

    payload = build_payload(frames, kr, earnings, args.demo)

    # 로그에서 바로 확인할 수 있게 요약을 남긴다
    print("  ── 요약 ──", file=sys.stderr)
    for line in payload["summary"]:
        print(f"  [{line['k']}] {line['v']}", file=sys.stderr)
    k = payload["kr"]
    print(f"  섹션: 지수 {len(payload['indices'])} · 매크로 {len(payload['macro'])} · "
          f"섹터 {len(payload['sectors'])} · 테마 {len(payload['themes'])} · "
          f"국장ETF {len(payload['kr_etfs'])} · 국장수급 {list(k.get('investors', {}))} · "
          f"외국인TOP {len(k.get('foreign_buy', []))} · 국장특징주 {len(k.get('up', []))} · "
          f"실적 {len(payload['earnings'])}", file=sys.stderr)
    write_outputs(payload, args)


def write_outputs(payload, args):
    html = render_html(payload)
    with open(args.output, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"  생성 완료: {args.output} ({len(html.encode('utf-8')) / 1e3:.0f} KB)", file=sys.stderr)
    if args.text:
        with open(args.text, "w", encoding="utf-8") as f:
            f.write(render_text(payload))
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
    if args.pdf:
        try:
            save_pdf(args.output, args.pdf)
        except Exception as e:
            print(f"  PDF 실패: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
