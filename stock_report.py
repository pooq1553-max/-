#!/usr/bin/env python3
"""
Stock Report — 52주 신고가 + 거래대금 상위 AND 조건 투자 보고서
pip install yfinance pandas schedule

사용법:
  python stock_report.py                # 즉시 보고서 생성
  python stock_report.py --market US    # US만
  python stock_report.py --market KR    # 한국만
  python stock_report.py --output report.txt  # 파일로 저장
  python stock_report.py --premarket    # 미국 프리마켓 52주 신고가 스캔
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
    # KOSPI
    "005930.KS": "삼성전자", "000660.KS": "SK하이닉스", "035420.KS": "NAVER",
    "005380.KS": "현대차", "051910.KS": "LG화학", "006400.KS": "삼성SDI",
    "035720.KS": "카카오", "005490.KS": "POSCO홀딩스", "068270.KS": "셀트리온",
    "028260.KS": "삼성물산", "207940.KS": "삼성바이오로직스", "012330.KS": "현대모비스",
    "055550.KS": "신한지주", "066570.KS": "LG전자", "003550.KS": "LG",
    "105560.KS": "KB금융", "096770.KS": "SK이노베이션", "034730.KS": "SK",
    "032830.KS": "삼성생명", "015760.KS": "한국전력", "003670.KS": "포스코퓨처엠",
    "033780.KS": "KT&G", "000270.KS": "기아", "138040.KS": "메리츠금융지주",
    "009150.KS": "삼성전기", "018260.KS": "삼성에스디에스", "090430.KS": "아모레퍼시픽",
    "011200.KS": "HMM", "017670.KS": "SK텔레콤", "086790.KS": "하나금융지주",
    "010130.KS": "고려아연", "316140.KS": "우리금융지주", "161390.KS": "한국타이어앤테크놀로지",
    "010950.KS": "S-Oil", "009540.KS": "한국조선해양", "011170.KS": "롯데케미칼",
    "024110.KS": "기업은행", "000810.KS": "삼성화재", "036570.KS": "엔씨소프트",
    "030200.KS": "KT", "004020.KS": "현대제철", "011780.KS": "금호석유",
    "006800.KS": "미래에셋증권", "267250.KS": "HD현대", "021240.KS": "코웨이",
    "071050.KS": "한국금융지주", "010140.KS": "삼성중공업", "078930.KS": "GS",
    "009830.KS": "한화솔루션", "002790.KS": "아모레G", "034020.KS": "두산에너빌리티",
    "036460.KS": "한국가스공사", "010620.KS": "HD현대미포", "088980.KS": "맥쿼리인프라",
    "097950.KS": "CJ제일제당", "047050.KS": "포스코인터내셔널", "000720.KS": "현대건설",
    "326030.KS": "SK바이오팜", "259960.KS": "크래프톤", "180640.KS": "한진칼",
    "128940.KS": "한미약품", "047810.KS": "한국항공우주", "042700.KS": "한미반도체",
    "272210.KS": "한화시스템", "035250.KS": "강원랜드", "000100.KS": "유한양행",
    "402340.KS": "SK스퀘어", "329180.KS": "HD현대중공업", "005830.KS": "DB손해보험",
    "006360.KS": "GS건설", "100840.KS": "SNT에너지", "192820.KS": "코스맥스",
    "302440.KS": "SK바이오사이언스", "052690.KS": "한전기술", "008770.KS": "호텔신라",
    "023530.KS": "롯데쇼핑",
    # KOSDAQ
    "247540.KQ": "에코프로비엠", "196170.KQ": "알테오젠", "377300.KQ": "카카오페이",
    "263750.KQ": "펄어비스", "145020.KQ": "휴젤", "091990.KQ": "셀트리온헬스케어",
    "357780.KQ": "솔브레인", "403870.KQ": "HPSP", "058470.KQ": "리노공업",
    "041510.KQ": "에스엠", "328130.KQ": "루닛", "086520.KQ": "에코프로",
    "293490.KQ": "카카오게임즈", "112040.KQ": "위메이드", "095340.KQ": "ISC",
    "067310.KQ": "하나마이크론", "036930.KQ": "주성엔지니어링", "035900.KQ": "JYP Ent.",
    "137310.KQ": "에스디바이오센서", "323410.KQ": "카카오뱅크", "039030.KQ": "이오테크닉스",
    "078600.KQ": "대주전자재료", "257720.KQ": "실리콘투", "240810.KQ": "원익IPS",
    "251270.KQ": "넷마블", "352820.KQ": "하이브", "068760.KQ": "셀트리온제약",
    "336260.KQ": "두산퓨얼셀", "022100.KQ": "포스코DX", "307950.KQ": "현대오토에버",
    "041190.KQ": "우리기술투자", "298380.KQ": "에이비엘바이오", "090460.KQ": "비에이치",
    "383220.KQ": "F&F", "042000.KQ": "카페24", "214150.KQ": "클래시스",
    "195940.KQ": "HK이노엔", "348210.KQ": "넥스틴", "299030.KQ": "하나기술",
    "053800.KQ": "안랩", "140860.KQ": "파크시스템스", "048410.KQ": "현대바이오",
    "278280.KQ": "천보", "097520.KQ": "에코프로에이치엔", "222080.KQ": "씨에스윈드",
    "174900.KQ": "앱클론", "043150.KQ": "바텍", "064350.KQ": "현대로템",
    "208710.KQ": "바이오니아", "028300.KQ": "에이치엘비", "294090.KQ": "이오플로우",
    "237690.KQ": "에스티팜", "365270.KQ": "큐셀즈", "369370.KQ": "블래드바이오사이언스",
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


def scan_premarket(symbols):
    """미국 프리마켓 52주 신고가 근접 종목 스캔."""
    print(f"  [프리마켓] {len(symbols)}개 종목 스캔 중...", file=sys.stderr)
    rows = []
    for i, sym in enumerate(symbols):
        try:
            t = yf.Ticker(sym)
            fi = t.fast_info
            mc = getattr(fi, "market_cap", 0) or 0
            if mc < 5e9:
                continue
            # 프리마켓 가격
            info = t.info
            pre_price = info.get("preMarketPrice", 0) or 0
            if pre_price <= 0:
                continue
            prev_close = getattr(fi, "previous_close", 0) or info.get("regularMarketPreviousClose", 0) or 0
            h52 = getattr(fi, "year_high", 0) or 0
            if h52 <= 0:
                continue

            pct_h = (pre_price / h52 * 100)
            chg = ((pre_price - prev_close) / prev_close * 100) if prev_close else 0
            pre_vol = info.get("preMarketVolume", 0) or 0

            rows.append(dict(
                sym=sym, pre_price=pre_price, prev_close=prev_close,
                chg=chg, h52=h52, pct_h=pct_h, mc=mc, pre_vol=pre_vol,
            ))
            if (i + 1) % 20 == 0:
                print(f"  ... {i+1}/{len(symbols)}", file=sys.stderr)
        except Exception:
            continue
    return pd.DataFrame(rows)


def generate_premarket_report(df):
    """프리마켓 52주 신고가 보고서 생성."""
    buf = StringIO()
    now = datetime.now()

    def w(text=""):
        buf.write(text + "\n")

    w("=" * 70)
    w("  미국 프리마켓 52주 신고가 스캔")
    w(f"  {now.strftime('%Y년 %m월 %d일 %H:%M')} 기준 (본장 개장 전)")
    w("=" * 70)
    w()

    if df.empty:
        w("  프리마켓 데이터가 없습니다. (프리마켓 시간이 아닐 수 있습니다)")
        return buf.getvalue()

    # 52주 고가 대비 95% 이상만 필터
    hits = df[df["pct_h"] >= 95].sort_values("pct_h", ascending=False)
    watch = df[(df["pct_h"] >= 90) & (df["pct_h"] < 95)].sort_values("pct_h", ascending=False)

    if hits.empty and watch.empty:
        w("  프리마켓에서 52주 고가 근접 종목이 없습니다.")
        w()
        # 상위 10개라도 보여줌
        top = df.sort_values("pct_h", ascending=False).head(10)
        if not top.empty:
            w("  [참고] 52주 고가 대비 상위 10종목:")
            w()
            for _, r in top.iterrows():
                name = get_name(r["sym"])
                w(f"    {name} ({r['sym']}): ${r['pre_price']:,.2f}  "
                  f"({r['chg']:+.2f}%)  고가대비 {r['pct_h']:.1f}%")
            w()
        return buf.getvalue()

    w(f"  52주 신고가 근접/돌파: {len(hits)}개  |  관찰 대상: {len(watch)}개")
    w()

    if not hits.empty:
        w("-" * 70)
        w("  [52주 신고가 돌파/근접] (95% 이상)")
        w("-" * 70)
        w()
        for _, r in hits.iterrows():
            name = get_name(r["sym"])
            status = "신고가 돌파!" if r["pct_h"] >= 100 else "신고가 근접"
            w(f"  * {name} ({r['sym']})  -- {status}")
            w(f"      프리마켓: ${r['pre_price']:,.2f}  |  전일종가: ${r['prev_close']:,.2f}  |  등락: {r['chg']:+.2f}%")
            w(f"      52주 고가: ${r['h52']:,.2f}  |  고가 대비: {r['pct_h']:.1f}%")
            w(f"      시가총액: {fmt_cap(r['mc'], 'US')}")
            if r["pct_h"] >= 100:
                w(f"      -> 프리마켓에서 52주 신고가 갱신! 본장 갭업 출발 가능성")
            elif r["pct_h"] >= 98:
                w(f"      -> 본장에서 52주 신고가 돌파 가능성 높음")
            else:
                w(f"      -> 52주 고가권 진입, 본장 흐름 주시")
            w()

    if not watch.empty:
        w("-" * 70)
        w("  [관찰 대상] (90~95%)")
        w("-" * 70)
        w()
        for _, r in watch.iterrows():
            name = get_name(r["sym"])
            w(f"  - {name} ({r['sym']}): ${r['pre_price']:,.2f}  "
              f"({r['chg']:+.2f}%)  고가대비 {r['pct_h']:.1f}%")
        w()

    w("=" * 70)
    w("  본장 매매 전략")
    w("=" * 70)
    w()
    if not hits.empty:
        w("  [신고가 돌파/근접 종목]")
        for _, r in hits.iterrows():
            name = get_name(r["sym"])
            if r["pct_h"] >= 100:
                w(f"    - {name}: 갭업 출발 예상 -> 시초가 돌파 시 추격 매수 or 눌림목 대기")
            else:
                w(f"    - {name}: 신고가 {r['pct_h']:.1f}% -> 돌파 시 추세 추종, 실패 시 관망")
        w()

    w("-" * 70)
    w("  주의: 프리마켓 데이터 기반이며, 본장에서 방향이 바뀔 수 있습니다.")
    w("  투자 결정은 본인의 판단과 책임 하에 이루어져야 합니다.")
    w("-" * 70)
    w(f"  보고서 생성: {now.strftime('%Y-%m-%d %H:%M:%S')}")
    w()

    return buf.getvalue()


def run_premarket(output=None):
    """프리마켓 보고서 실행."""
    df = scan_premarket(US)
    report = generate_premarket_report(df)

    print(report)

    if output:
        filepath = output
    else:
        filepath = f"premarket_{datetime.now().strftime('%Y%m%d_%H%M')}.txt"

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"  보고서 저장: {filepath}", file=sys.stderr)

    return filepath


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
    parser.add_argument("--premarket", action="store_true",
                        help="미국 프리마켓 52주 신고가 스캔")
    args = parser.parse_args()
    if args.premarket:
        run_premarket(output=args.output)
    else:
        run_report(market=args.market, output=args.output)


if __name__ == "__main__":
    main()
