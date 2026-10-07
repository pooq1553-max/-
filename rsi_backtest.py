#!/usr/bin/env python3
"""
RSI 역추세 백테스트 (기본: SOXL = 필라델피아 반도체지수 3배 ETF)

규칙
  - 보유 안 함 + RSI < 30  -> 그날 종가에 전액 매수
  - 보유 중   + RSI > 80  -> 그날 종가에 전량 매도
  - RSI는 Wilder 방식(기본 14일), 수정주가(분할·배당 반영) 기준

사용 예
  python rsi_backtest.py                        # SOXL 상장일~현재
  python rsi_backtest.py --start 2020-01-01     # 기간 지정
  python rsi_backtest.py --buy 30 --sell 80 --period 14 --fee 0.1
  python rsi_backtest.py --csv soxl.csv         # 다운로드 대신 CSV(Date, Close) 사용
"""
import argparse
import sys

import numpy as np
import pandas as pd


def load_prices(ticker, start, end, csv_path=None):
    if csv_path:
        df = pd.read_csv(csv_path, parse_dates=["Date"], index_col="Date")
        close = df["Close"]
    else:
        import yfinance as yf
        kw = {"start": start} if start else {"period": "max"}
        df = yf.download(ticker, end=end, auto_adjust=True, progress=False, **kw)
        if df.empty:
            sys.exit(f"{ticker} 가격을 받지 못했습니다.")
        close = df["Close"]
        if isinstance(close, pd.DataFrame):
            close = close.iloc[:, 0]
    close = close.dropna().sort_index()
    if start:
        close = close[close.index >= pd.Timestamp(start)]
    if end:
        close = close[close.index <= pd.Timestamp(end)]
    return close


def rsi(close, period=14):
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss
    return 100 - 100 / (1 + rs)


def backtest(close, period=14, buy_th=30, sell_th=80, fee_pct=0.0):
    r = rsi(close, period)
    fee = fee_pct / 100
    trades = []
    equity = []
    held = []
    cash, shares = 1.0, 0.0
    entry = None

    for date, px, rv in zip(close.index, close.values, r.values):
        if not np.isnan(rv):
            if shares == 0 and rv < buy_th:
                shares = cash * (1 - fee) / px
                cash = 0.0
                entry = (date, px, rv)
            elif shares > 0 and rv > sell_th:
                cash = shares * px * (1 - fee)
                shares = 0.0
                trades.append({
                    "매수일": entry[0].date(), "매수가": entry[1], "매수RSI": entry[2],
                    "매도일": date.date(), "매도가": px, "매도RSI": rv,
                    "보유일": (date - entry[0]).days,
                    "수익률%": ((px * (1 - fee)) / (entry[1] / (1 - fee)) - 1) * 100,
                })
                entry = None
        equity.append(cash + shares * px)
        held.append(shares > 0)

    equity = pd.Series(equity, index=close.index)
    equity.attrs["exposure"] = np.mean(held) * 100
    return trades, equity, entry, r


def max_drawdown(series):
    return (series / series.cummax() - 1).min() * 100


def cagr(series):
    years = (series.index[-1] - series.index[0]).days / 365.25
    return ((series.iloc[-1] / series.iloc[0]) ** (1 / years) - 1) * 100 if years > 0 else 0.0


def main():
    ap = argparse.ArgumentParser(description="RSI 역추세 백테스트")
    ap.add_argument("--ticker", default="SOXL")
    ap.add_argument("--start", default=None)
    ap.add_argument("--end", default=None)
    ap.add_argument("--period", type=int, default=14, help="RSI 기간")
    ap.add_argument("--buy", type=float, default=30, help="이 값 미만이면 매수")
    ap.add_argument("--sell", type=float, default=80, help="이 값 초과면 매도")
    ap.add_argument("--fee", type=float, default=0.0, help="편도 수수료+슬리피지 %%")
    ap.add_argument("--csv", default=None, help="Date, Close 컬럼 CSV")
    args = ap.parse_args()

    close = load_prices(args.ticker, args.start, args.end, args.csv)
    trades, equity, open_pos, r = backtest(close, args.period, args.buy, args.sell, args.fee)

    pd.set_option("display.width", 200)
    print(f"\n=== {args.ticker} RSI({args.period}) <{args.buy:g} 매수 / >{args.sell:g} 매도 "
          f"(편도비용 {args.fee:g}%) ===")
    print(f"기간: {close.index[0].date()} ~ {close.index[-1].date()} ({len(close)}거래일)\n")

    if trades:
        tdf = pd.DataFrame(trades)
        print(tdf.to_string(index=False, float_format=lambda x: f"{x:,.2f}"))
    else:
        print("완료된 거래 없음")

    if open_pos:
        last = close.iloc[-1]
        print(f"\n[보유 중] {open_pos[0].date()} 매수가 {open_pos[1]:,.2f} -> 현재 {last:,.2f} "
              f"({(last / open_pos[1] - 1) * 100:+.2f}%, 현재 RSI {r.iloc[-1]:.1f})")

    bh = close / close.iloc[0]
    n = len(trades)
    wins = sum(t["수익률%"] > 0 for t in trades)

    print("\n--- 요약 ---")
    print(f"완료 거래 수     : {n}회")
    if n:
        rets = [t["수익률%"] for t in trades]
        print(f"승률             : {wins / n * 100:.1f}% ({wins}승 {n - wins}패)")
        print(f"평균 거래 수익률 : {np.mean(rets):+.2f}%  (최고 {max(rets):+.2f}%, 최저 {min(rets):+.2f}%)")
        print(f"평균 보유 기간   : {np.mean([t['보유일'] for t in trades]):.0f}일")
    print(f"전략 누적수익률  : {(equity.iloc[-1] - 1) * 100:+,.2f}%")
    print(f"전략 CAGR        : {cagr(equity):+.2f}%")
    print(f"전략 MDD         : {max_drawdown(equity):.2f}%")
    print(f"시장 노출 비율   : {equity.attrs['exposure']:.1f}%")
    print(f"단순보유 누적    : {(bh.iloc[-1] - 1) * 100:+,.2f}%")
    print(f"단순보유 CAGR    : {cagr(bh):+.2f}%")
    print(f"단순보유 MDD     : {max_drawdown(bh):.2f}%")
    print(f"현재 RSI         : {r.iloc[-1]:.1f}")


if __name__ == "__main__":
    main()
