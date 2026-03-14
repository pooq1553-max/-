#!/usr/bin/env python3
"""
Market Scanner — 신고가 + 거래대금 + 시총 필터
pip install yfinance pandas
사용법:
  python scanner.py              # 전체 (US + KOSPI + KOSDAQ)
  python scanner.py --market US  # US만
  python scanner.py --market KR  # 한국만
"""
import argparse
import warnings
from datetime import datetime
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
def fmt_cap(v, mkt):
    if pd.isna(v) or v <= 0: return "-"
    if mkt == "US":
        return f"${v/1e12:.1f}T" if v >= 1e12 else f"${v/1e9:.0f}B" if v >= 1e9 else f"${v/1e6:.0f}M"
    return f"{v/1e12:.1f}조" if v >= 1e12 else f"{v/1e8:,.0f}억"
def fmt_tv(v, mkt):
    if pd.isna(v) or v <= 0: return "-"
    if mkt == "US":
        return f"${v/1e9:.1f}B" if v >= 1e9 else f"${v/1e6:.0f}M" if v >= 1e6 else f"${v:,.0f}"
    return f"{v/1e12:.1f}조" if v >= 1e12 else f"{v/1e8:,.0f}억" if v >= 1e8 else f"{v:,.0f}"
def scan(symbols, mkt, min_cap):
    """yfinance로 종목 스캔. 한번에 히스토리 다운 + fast_info로 시총 체크."""
    print(f"  📥 {len(symbols)}개 종목 히스토리 다운로드...")

    # 1년치 한방에 다운로드 (52주 고가 + 평균 거래량 계산용)
    raw = yf.download(symbols, period="1y", interval="1d",
                      group_by="ticker", progress=False, threads=True)
    rows = []
    total = len(symbols)
    for i, sym in enumerate(symbols):
        try:
            t = yf.Ticker(sym)
            fi = t.fast_info
            mc = getattr(fi, "market_cap", 0) or 0
            if mc < min_cap:
                continue
            price = getattr(fi, "last_price", 0) or 0
            prev  = getattr(fi, "previous_close", 0) or price
            chg   = ((price - prev) / prev * 100) if prev else 0
            h52   = getattr(fi, "year_high", 0) or 0
            l52   = getattr(fi, "year_low", 0) or 0
            vol   = getattr(fi, "last_volume", 0) or 0
            tv    = price * vol
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
            rows.append(dict(
                sym=sym, price=price, chg=chg, h52=h52, l52=l52,
                pct_h=pct_h, mc=mc, vol=vol, avg_vol=avg_vol,
                vol_r=vol_r, tv=tv, mkt=mkt,
            ))
            if (i + 1) % 20 == 0:
                print(f"  ... {i+1}/{total}")
        except Exception:
            continue
    return pd.DataFrame(rows)
def print_ath(df, mkt, n=30):
    sub = df[df["pct_h"] >= 90].sort_values("pct_h", ascending=False).head(n)
    if sub.empty:
        print("  (없음)\n"); return
    hdr = f"  {'#':>3}  {'종목':>10}  {'현재가':>12}  {'등락':>8}  {'52주高비':>8}  {'시총':>10}  {'거래대금':>10}  {'Vol비':>6}"
    print(hdr)
    print("  " + "─" * len(hdr))
    for i, (_, r) in enumerate(sub.iterrows()):
        s = r["sym"].replace(".KS","").replace(".KQ","")
        tag = "🔥" if r["pct_h"] >= 98 else "⬆️" if r["pct_h"] >= 95 else "📈"
        p = f"${r['price']:,.2f}" if mkt == "US" else f"₩{r['price']:,.0f}"
        c = f"{r['chg']:+.2f}%"
        vr = f"{r['vol_r']:.1f}x"
        print(f"  {i+1:>3}  {tag} {s:>8}  {p:>12}  {c:>8}  {r['pct_h']:>7.1f}%  "
              f"{fmt_cap(r['mc'], mkt):>10}  {fmt_tv(r['tv'], mkt):>10}  {vr:>6}")
    print()
def print_tv(df, mkt, n=20):
    sub = df.sort_values("tv", ascending=False).head(n)
    if sub.empty:
        print("  (없음)\n"); return
    hdr = f"  {'#':>3}  {'종목':>10}  {'현재가':>12}  {'등락':>8}  {'거래대금':>12}  {'시총':>10}  {'52주高비':>8}  {'Vol비':>6}"
    print(hdr)
    print("  " + "─" * len(hdr))
    for i, (_, r) in enumerate(sub.iterrows()):
        s = r["sym"].replace(".KS","").replace(".KQ","")
        tag = "🔥" if r["pct_h"] >= 95 else "  "
        p = f"${r['price']:,.2f}" if mkt == "US" else f"₩{r['price']:,.0f}"
        c = f"{r['chg']:+.2f}%"
        vr = f"{r['vol_r']:.1f}x"
        print(f"  {i+1:>3}  {tag}{s:>8}  {p:>12}  {c:>8}  {fmt_tv(r['tv'], mkt):>12}  "
              f"{fmt_cap(r['mc'], mkt):>10}  {r['pct_h']:>7.1f}%  {vr:>6}")
    print()
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--market", choices=["US","KR","ALL"], default="ALL")
    args = parser.parse_args()
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    print(f"\n{'═'*60}")
    print(f"  ⚡ Market Scanner — {now}")
    print(f"{'═'*60}\n")
    jobs = []
    if args.market in ("US","ALL"):
        jobs.append(("US", US, 5e9, "🇺🇸 US Market ($5B+)"))
    if args.market in ("KR","ALL"):
        jobs.append(("KR", KOSPI,  1e12, "🇰🇷 KOSPI (1조+)"))
        jobs.append(("KR", KOSDAQ, 1e12, "🇰🇷 KOSDAQ (1조+)"))
    all_dfs = []
    for mkt, syms, mc, label in jobs:
        print(f"┌─ {label}  ({len(syms)}개 후보)")
        df = scan(syms, mkt, mc)
        print(f"│  시총 통과: {len(df)}개")
        if not df.empty:
            ath_n = len(df[df["pct_h"] >= 95])
            near_n = len(df[(df["pct_h"] >= 90) & (df["pct_h"] < 95)])
            print(f"│  🔥 신고가(95%↑): {ath_n}  📈 근접(90~95%): {near_n}")
            print(f"│")
            print(f"│  ── 🔥 52주 신고가 근접 (90%↑) ──")
            print_ath(df, mkt)
            print(f"│  ── 💰 거래대금 TOP 20 ──")
            print_tv(df, mkt)
            all_dfs.append(df)
        print(f"└{'─'*58}\n")
    # 전체 요약
    if len(all_dfs) > 1:
        combined = pd.concat(all_dfs, ignore_index=True)
        ath_all = combined[combined["pct_h"] >= 95].sort_values("pct_h", ascending=False)
        if not ath_all.empty:
            print(f"{'─'*60}")
            print(f"  📊 전 시장 신고가 종목 (95%↑)")
            print(f"{'─'*60}")
            for _, r in ath_all.iterrows():
                s = r["sym"].replace(".KS","").replace(".KQ","")
                print(f"  🔥 {s:>10}  {r['pct_h']:.1f}%  "
                      f"chg {r['chg']:+.2f}%  vol {r['vol_r']:.1f}x  ({r['mkt']})")
            print()
    print(f"  ✅ 완료 — {datetime.now().strftime('%H:%M:%S')}\n")
if __name__ == "__main__":
    main()
