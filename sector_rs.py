"""US 섹터 ETF 거래량 가중 모멘텀(수급) 순위표.

거래량 가중 모멘텀 정의:
    score(t) = Σ_{i=t-19..t}  daily_return_i × (volume_i / avg60_volume_i)
- 20 거래일 모멘텀에 각 날짜의 상대 거래량을 곱해 합산.
- "상대 거래량이 높은 날의 상승"이 크게 반영되어 수급 방향성을 나타냄.

매일 재실행되어도 최근 10 거래일 순위표가 온전히 재계산되도록 설계.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd
import yfinance as yf

SECTORS: dict[str, str] = {
    "XLK": "기술",
    "XLF": "금융",
    "XLE": "에너지",
    "XLV": "헬스",
    "XLI": "산업",
    "XLY": "임의소비",
    "XLP": "필수소비",
    "XLU": "유틸",
    "XLB": "소재",
    "XLRE": "부동산",
    "XLC": "커뮤니케이션",
}

MOMENTUM_WINDOW = 20
VOLUME_WINDOW = 60
DISPLAY_DAYS = 10


def compute_scores(prices: pd.DataFrame, volumes: pd.DataFrame) -> pd.DataFrame:
    """각 (날짜, 티커) 조합에 대해 거래량 가중 모멘텀 점수를 계산."""
    daily_return = prices.pct_change()
    avg_volume = volumes.rolling(VOLUME_WINDOW, min_periods=VOLUME_WINDOW // 2).mean()
    vol_ratio = volumes / avg_volume
    contribution = daily_return * vol_ratio
    scores = contribution.rolling(MOMENTUM_WINDOW, min_periods=MOMENTUM_WINDOW).sum()
    return scores


def build_rank_table(scores: pd.DataFrame) -> pd.DataFrame:
    """점수 → 순위(1이 가장 강함). 최근 DISPLAY_DAYS 행만 반환."""
    ranks = scores.rank(axis=1, ascending=False, method="min").astype("Int64")
    ranks = ranks.dropna(how="all").tail(DISPLAY_DAYS)
    return ranks


def render_markdown(ranks: pd.DataFrame, scores: pd.DataFrame) -> str:
    tickers = list(SECTORS.keys())
    header_cells = [f"{SECTORS[t]}<br>({t})" for t in tickers]
    lines = ["# US 섹터 ETF 수급(거래량 가중 모멘텀) 순위", ""]
    lines.append(f"- 지표: 20일 모멘텀 × 상대 거래량(60일 평균 대비) 누적합")
    lines.append(f"- 숫자 = 순위 (1이 가장 강함, {len(tickers)}가 가장 약함)")
    lines.append(f"- 최근 {DISPLAY_DAYS} 거래일 (아래로 갈수록 최신)")
    lines.append("")
    lines.append("| 날짜 | " + " | ".join(header_cells) + " |")
    lines.append("|---|" + "|".join(["---"] * len(tickers)) + "|")
    for date, row in ranks.iterrows():
        cells = [f"{int(row[t])}" if pd.notna(row[t]) else "-" for t in tickers]
        lines.append(f"| {date.strftime('%Y-%m-%d')} | " + " | ".join(cells) + " |")
    lines.append("")
    last_date = ranks.index[-1]
    last_ranks = ranks.loc[last_date].dropna().sort_values()
    last_scores = scores.loc[last_date]
    lines.append(f"## {last_date.strftime('%Y-%m-%d')} 상세")
    lines.append("")
    lines.append("| 순위 | 섹터 | 티커 | 점수 |")
    lines.append("|---|---|---|---|")
    for ticker, rank in last_ranks.items():
        lines.append(
            f"| {int(rank)} | {SECTORS[ticker]} | {ticker} | {last_scores[ticker]:+.4f} |"
        )
    lines.append("")
    return "\n".join(lines)


def fetch_data(tickers: list[str], period: str = "6mo") -> tuple[pd.DataFrame, pd.DataFrame]:
    data = yf.download(
        tickers,
        period=period,
        interval="1d",
        auto_adjust=True,
        progress=False,
        group_by="column",
    )
    prices = data["Close"][tickers]
    volumes = data["Volume"][tickers]
    return prices, volumes


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", default="reports", help="출력 디렉토리")
    parser.add_argument("--csv", default="sector_rs.csv", help="CSV 파일명 (순위 이력)")
    parser.add_argument("--md", default="sector_rs.md", help="Markdown 파일명 (표시용)")
    args = parser.parse_args()

    tickers = list(SECTORS.keys())
    prices, volumes = fetch_data(tickers)
    scores = compute_scores(prices, volumes)
    ranks = build_rank_table(scores)
    if ranks.empty:
        raise SystemExit(
            "No ranking rows produced — check that Yahoo Finance returned "
            "enough history for all sector ETFs."
        )

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    csv_path = out_dir / args.csv
    ranks_csv = ranks.copy()
    ranks_csv.index = ranks_csv.index.strftime("%Y-%m-%d")
    ranks_csv.index.name = "date"
    ranks_csv.to_csv(csv_path)

    md_path = out_dir / args.md
    md_path.write_text(render_markdown(ranks, scores), encoding="utf-8")

    print(f"Wrote {csv_path} and {md_path}")
    print(f"Latest date: {ranks.index[-1].strftime('%Y-%m-%d')}")


if __name__ == "__main__":
    main()
