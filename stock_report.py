#!/usr/bin/env python3
"""
Stock Report — 52주 신고가 + 거래대금 상위 AND 조건 투자 보고서
pip install yfinance pandas schedule

사용법:
  python stock_report.py                # 즉시 보고서 생성
  python stock_report.py --market US    # US만
  python stock_report.py --market KR    # 한국만
  python stock_report.py --output report.txt  # 파일로 저장
"""
import argparse
import warnings
import sys
from datetime import datetime
from io import StringIO

import pandas as pd
import yfinance as yf

warnings.filterwarnings("ignore")

# ─── 종목 유니버스 ───
US = [
    "AAPL","MSFT","GOOGL","AMZN","NVDA","META","TSLA","BRK-B","UNH","JNJ",
    "V","XOM","JPM","PG","MA","HD","CVX","MRK","ABBV","LLY","PEP","KO",
    "COST","AVGO","TMO","MCD","WMT","CRM","ACN","ADBE","AMD","NFLX",
    "INTC","QCOM","TXN","AMAT","LRCX","KLAC","SNPS","CDNS","MRVL","ARM",
    "PLTR","SMCI","CRWD","PANW","DDOG","NET","ZS","SNOW","ORCL","CSCO",
    "IBM","NOW","UBER","ABNB","SQ","SHOP","COIN","BAC","WFC","GS","MS",
    "C","BLK","SCHW","AXP","DIS","CMCSA","T","VZ","TMUS","NXPI","ON",
    "MCHP","ADI","MU","FTNT","WDAY","TEAM","REGN","AMGN","GILD","VRTX",
    "MRNA","BMY","PFE","DHR","SYK","BSX","ABT","ISRG","ZTS","CI","CAT",
    "DE","HON","GE","RTX","BA","LMT","NOC","UPS","FDX","AMT","PLD","CCI",
    "EQIX","NEE","DUK","SO","DELL","DASH","TT","IR","APH","CTAS","INTU",
    "ANSS","ICE","CME","SPGI","MCO","ADP","ROP","IDXX","DXCM","MSCI",
]
KOSPI = [
    "005930.KS","000660.KS","035420.KS","005380.KS","051910.KS","006400.KS",
    "035720.KS","005490.KS","068270.KS","028260.KS","207940.KS","012330.KS",
    "055550.KS","066570.KS","003550.KS","105560.KS","096770.KS","034730.KS",
    "032830.KS","015760.KS","003670.KS","033780.KS","000270.KS","138040.KS",
    "009150.KS","018260.KS","090430.KS","011200.KS","017670.KS","086790.KS",
    "010130.KS","316140.KS","161390.KS","010950.KS","009540.KS","011170.KS",
    "024110.KS","000810.KS","036570.KS","030200.KS","004020.KS","011780.KS",
    "006800.KS","267250.KS","021240.KS","071050.KS","010140.KS","078930.KS",
    "009830.KS","002790.KS","034020.KS","036460.KS","010620.KS","088980.KS",
    "097950.KS","047050.KS","000720.KS","326030.KS","259960.KS","180640.KS",
    "128940.KS","047810.KS","042700.KS","272210.KS","035250.KS","000100.KS",
    "402340.KS","329180.KS","005830.KS","006360.KS","100840.KS","192820.KS",
    "302440.KS","052690.KS","008770.KS","023530.KS",
]
KOSDAQ = [
    "247540.KQ","196170.KQ","377300.KQ","263750.KQ","145020.KQ","091990.KQ",
    "357780.KQ","403870.KQ","058470.KQ","041510.KQ","328130.KQ","086520.KQ",
    "293490.KQ","112040.KQ","095340.KQ","067310.KQ","036930.KQ","035900.KQ",
    "137310.KQ","323410.KQ","039030.KQ","078600.KQ","257720.KQ","240810.KQ",
    "251270.KQ","352820.KQ","068760.KQ","336260.KQ","022100.KQ","307950.KQ",
    "041190.KQ","298380.KQ","090460.KQ","383220.KQ","042000.KQ","214150.KQ",
    "195940.KQ","348210.KQ","299030.KQ","053800.KQ","140860.KQ","048410.KQ",
    "278280.KQ","097520.KQ","222080.KQ","174900.KQ","043150.KQ","064350.KQ",
    "208710.KQ","028300.KQ","294090.KQ","237690.KQ","365270.KQ","369370.KQ",
]

# ─── 이름 매핑 (주요 종목) ───
NAMES = {
    "AAPL": "Apple", "MSFT": "Microsoft", "GOOGL": "Alphabet", "AMZN": "Amazon",
    "NVDA": "NVIDIA", "META": "Meta", "TSLA": "Tesla", "AVGO": "Broadcom",
    "LLY": "Eli Lilly", "JPM": "JP Morgan", "V": "Visa", "UNH": "UnitedHealth",
    "MA": "Mastercard", "COST": "Costco", "HD": "Home Depot", "NFLX": "Netflix",
    "CRM": "Salesforce", "AMD": "AMD", "ORCL": "Oracle", "PLTR": "Palantir",
    "ARM": "ARM Holdings", "CRWD": "CrowdStrike", "PANW": "Palo Alto",
    "COIN": "Coinbase", "SMCI": "Super Micro", "NOW": "ServiceNow",
    "005930.KS": "삼성전자", "000660.KS": "SK하이닉스", "035420.KS": "NAVER",
    "005380.KS": "현대차", "051910.KS": "LG화학", "006400.KS": "삼성SDI",
    "035720.KS": "카카오", "005490.KS": "POSCO홀딩스", "068270.KS": "셀트리온",
    "028260.KS": "삼성물산", "207940.KS": "삼성바이오", "012330.KS": "현대모비스",
    "055550.KS": "신한지주", "066570.KS": "LG전자", "003550.KS": "LG",
    "105560.KS": "KB금융", "247540.KQ": "에코프로비엠", "196170.KQ": "알테오젠",
    "377300.KQ": "카카오페이", "263750.KQ": "펄어비스", "145020.KQ": "휴젤",
    "091990.KQ": "셀트리온헬스케어",
}


def fmt_cap(v, mkt):
    if pd.isna(v) or v <= 0:
        return "-"
    if mkt == "US":
        if v >= 1e12:
            return f"${v/1e12:.1f}T"
        if v >= 1e9:
            return f"${v/1e9:.0f}B"
        return f"${v/1e6:.0f}M"
    if v >= 1e12:
        return f"{v/1e12:.1f}조"
    return f"{v/1e8:,.0f}억"


def fmt_tv(v, mkt):
    if pd.isna(v) or v <= 0:
        return "-"
    if mkt == "US":
        if v >= 1e9:
            return f"${v/1e9:.1f}B"
        if v >= 1e6:
            return f"${v/1e6:.0f}M"
        return f"${v:,.0f}"
    if v >= 1e12:
        return f"{v/1e12:.1f}조"
    if v >= 1e8:
        return f"{v/1e8:,.0f}억"
    return f"{v:,.0f}"


def fmt_price(v, mkt):
    if mkt == "US":
        return f"${v:,.2f}"
    return f"{v:,.0f}원"


def scan(symbols, mkt, min_cap):
    """yfinance로 종목 스캔."""
    print(f"  [{mkt}] {len(symbols)}개 종목 다운로드 중...", file=sys.stderr)
    raw = yf.download(symbols, period="1y", interval="1d",
                      group_by="ticker", progress=False, threads=True)
    rows = []
    for i, sym in enumerate(symbols):
        try:
            t = yf.Ticker(sym)
            fi = t.fast_info
            mc = getattr(fi, "market_cap", 0) or 0
            if mc < min_cap:
                continue
            price = getattr(fi, "last_price", 0) or 0
            prev = getattr(fi, "previous_close", 0) or price
            chg = ((price - prev) / prev * 100) if prev else 0
            h52 = getattr(fi, "year_high", 0) or 0
            l52 = getattr(fi, "year_low", 0) or 0
            vol = getattr(fi, "last_volume", 0) or 0
            tv = price * vol
            pct_h = (price / h52 * 100) if h52 else 0

            # 10일 평균 거래량
            try:
                if len(symbols) == 1:
                    vs = raw["Volume"].dropna().tail(10)
                else:
                    vs = raw[(sym, "Volume")].dropna().tail(10)
                avg_vol = vs.mean() if len(vs) else vol
            except Exception:
                avg_vol = vol
            vol_r = (vol / avg_vol) if avg_vol else 1.0

            # 20일 평균 거래대금 (보고서용)
            try:
                if len(symbols) == 1:
                    ps = raw["Close"].dropna().tail(20)
                    vols = raw["Volume"].dropna().tail(20)
                else:
                    ps = raw[(sym, "Close")].dropna().tail(20)
                    vols = raw[(sym, "Volume")].dropna().tail(20)
                avg_tv = (ps * vols).mean() if len(ps) else tv
            except Exception:
                avg_tv = tv
            tv_ratio = (tv / avg_tv) if avg_tv else 1.0

            rows.append(dict(
                sym=sym, price=price, chg=chg, h52=h52, l52=l52,
                pct_h=pct_h, mc=mc, vol=vol, avg_vol=avg_vol,
                vol_r=vol_r, tv=tv, avg_tv=avg_tv, tv_ratio=tv_ratio, mkt=mkt,
            ))
            if (i + 1) % 20 == 0:
                print(f"  ... {i+1}/{len(symbols)}", file=sys.stderr)
        except Exception:
            continue
    return pd.DataFrame(rows)


def get_name(sym):
    """종목명 반환."""
    if sym in NAMES:
        return NAMES[sym]
    return sym.replace(".KS", "").replace(".KQ", "")


def grade_stock(row):
    """종목 등급 산정: S/A/B."""
    score = 0
    # 52주 고가 근접도
    if row["pct_h"] >= 98:
        score += 3
    elif row["pct_h"] >= 95:
        score += 2
    else:
        score += 1
    # 거래대금 비율 (평균 대비)
    if row["tv_ratio"] >= 2.0:
        score += 3
    elif row["tv_ratio"] >= 1.5:
        score += 2
    else:
        score += 1
    # 거래량 비율
    if row["vol_r"] >= 2.0:
        score += 2
    elif row["vol_r"] >= 1.3:
        score += 1
    # 당일 등락폭
    if row["chg"] >= 3:
        score += 1

    if score >= 7:
        return "S"
    if score >= 5:
        return "A"
    return "B"


def generate_report(all_data, pct_h_min=90, tv_top_pct=30):
    """
    AND 조건 보고서 생성:
    - 52주 고가 대비 pct_h_min% 이상 (기본 90%)
    - 거래대금 상위 tv_top_pct% 이내 (기본 상위 30%)
    """
    buf = StringIO()
    now = datetime.now()

    def w(text=""):
        buf.write(text + "\n")

    w("=" * 70)
    w(f"  투자 유망 종목 보고서")
    w(f"  {now.strftime('%Y년 %m월 %d일 %H:%M')} 기준")
    w(f"  필터: 52주 신고가 {pct_h_min}%↑ AND 거래대금 상위 {tv_top_pct}%")
    w("=" * 70)
    w()

    if all_data.empty:
        w("  데이터 없음.")
        return buf.getvalue()

    # 시장별 거래대금 상위 필터 계산
    filtered_rows = []
    for mkt in all_data["mkt"].unique():
        mkt_df = all_data[all_data["mkt"] == mkt].copy()
        tv_threshold = mkt_df["tv"].quantile(1 - tv_top_pct / 100)
        cond = (mkt_df["pct_h"] >= pct_h_min) & (mkt_df["tv"] >= tv_threshold)
        filtered_rows.append(mkt_df[cond])

    df = pd.concat(filtered_rows, ignore_index=True) if filtered_rows else pd.DataFrame()

    if df.empty:
        w("  조건을 만족하는 종목이 없습니다.")
        w(f"  (52주 고가 {pct_h_min}%↑ AND 거래대금 상위 {tv_top_pct}% 동시 충족)")
        return buf.getvalue()

    # 등급 산정
    df["grade"] = df.apply(grade_stock, axis=1)
    df = df.sort_values(["grade", "pct_h"], ascending=[True, False])

    # ─── 요약 ───
    w(f"  총 {len(df)}개 종목이 두 조건을 동시에 충족합니다.")
    for g in ["S", "A", "B"]:
        cnt = len(df[df["grade"] == g])
        if cnt:
            w(f"    등급 {g}: {cnt}개")
    w()

    # ─── 시장별 상세 ───
    for mkt in ["US", "KR"]:
        mkt_df = df[df["mkt"] == mkt]
        if mkt_df.empty:
            continue

        label = "미국 시장" if mkt == "US" else "한국 시장"
        w("-" * 70)
        w(f"  [{label}]")
        w("-" * 70)
        w()

        for grade in ["S", "A", "B"]:
            gdf = mkt_df[mkt_df["grade"] == grade]
            if gdf.empty:
                continue

            grade_label = {"S": "최우선 관심", "A": "관심", "B": "모니터링"}[grade]
            w(f"  === 등급 {grade} ({grade_label}) ===")
            w()

            for _, r in gdf.iterrows():
                name = get_name(r["sym"])
                ticker = r["sym"].replace(".KS", "").replace(".KQ", "")
                w(f"  [{grade}] {name} ({ticker})")
                w(f"      현재가: {fmt_price(r['price'], mkt)}  |  등락: {r['chg']:+.2f}%")
                w(f"      52주 고가 대비: {r['pct_h']:.1f}%  (고가: {fmt_price(r['h52'], mkt)})")
                w(f"      거래대금: {fmt_tv(r['tv'], mkt)}  (평균 대비 {r['tv_ratio']:.1f}배)")
                w(f"      거래량 비율: {r['vol_r']:.1f}x  |  시가총액: {fmt_cap(r['mc'], mkt)}")

                # 간단한 코멘트
                comments = []
                if r["pct_h"] >= 98:
                    comments.append("52주 신고가 돌파 직전")
                elif r["pct_h"] >= 95:
                    comments.append("52주 고가 근접")
                if r["tv_ratio"] >= 2.0:
                    comments.append("거래대금 급증 (강한 수급)")
                elif r["tv_ratio"] >= 1.5:
                    comments.append("거래대금 증가")
                if r["vol_r"] >= 2.0:
                    comments.append("거래량 폭증")
                if r["chg"] >= 3:
                    comments.append("강한 상승세")
                elif r["chg"] >= 1:
                    comments.append("양봉")
                elif r["chg"] <= -1:
                    comments.append("고가권 조정 중")

                if comments:
                    w(f"      -> {', '.join(comments)}")
                w()

    # ─── 투자 의견 요약 ───
    w("=" * 70)
    w("  투자 의견 요약")
    w("=" * 70)
    w()

    s_stocks = df[df["grade"] == "S"]
    if not s_stocks.empty:
        w("  [최우선 관심 종목]")
        for _, r in s_stocks.iterrows():
            name = get_name(r["sym"])
            w(f"    - {name}: 신고가 근접({r['pct_h']:.1f}%) + "
              f"거래대금 활발({r['tv_ratio']:.1f}x) -> 추세 추종 매매 유리")
        w()

    a_stocks = df[df["grade"] == "A"]
    if not a_stocks.empty:
        w("  [관심 종목]")
        for _, r in a_stocks.iterrows():
            name = get_name(r["sym"])
            w(f"    - {name}: 고가권 유지 + 수급 양호 -> 눌림목 매수 대기")
        w()

    b_stocks = df[df["grade"] == "B"]
    if not b_stocks.empty:
        w("  [모니터링 종목]")
        for _, r in b_stocks.iterrows():
            name = get_name(r["sym"])
            w(f"    - {name}: 조건 충족하나 모멘텀 추가 확인 필요")
        w()

    w("-" * 70)
    w("  주의: 본 보고서는 데이터 기반 자동 생성이며 투자 권유가 아닙니다.")
    w("  투자 결정은 본인의 판단과 책임 하에 이루어져야 합니다.")
    w("-" * 70)
    w(f"  보고서 생성: {now.strftime('%Y-%m-%d %H:%M:%S')}")
    w()

    return buf.getvalue()


def run_report(market="ALL", output=None):
    """보고서 실행."""
    jobs = []
    if market in ("US", "ALL"):
        jobs.append(("US", US, 5e9))
    if market in ("KR", "ALL"):
        jobs.append(("KR", KOSPI, 1e12))
        jobs.append(("KR", KOSDAQ, 1e12))

    all_dfs = []
    for mkt, syms, mc in jobs:
        df = scan(syms, mkt, mc)
        if not df.empty:
            all_dfs.append(df)

    combined = pd.concat(all_dfs, ignore_index=True) if all_dfs else pd.DataFrame()
    report = generate_report(combined)

    # 출력
    print(report)

    # 파일 저장
    if output:
        filepath = output
    else:
        filepath = f"report_{datetime.now().strftime('%Y%m%d_%H%M')}.txt"

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"  보고서 저장: {filepath}", file=sys.stderr)

    return filepath


def main():
    parser = argparse.ArgumentParser(description="52주 신고가 + 거래대금 AND 조건 투자 보고서")
    parser.add_argument("--market", choices=["US", "KR", "ALL"], default="ALL",
                        help="시장 선택 (기본: ALL)")
    parser.add_argument("--output", "-o", type=str, default=None,
                        help="출력 파일명 (기본: report_YYYYMMDD_HHMM.txt)")
    args = parser.parse_args()
    run_report(market=args.market, output=args.output)


if __name__ == "__main__":
    main()
