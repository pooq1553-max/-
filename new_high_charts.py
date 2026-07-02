"""52주 신고가 근접 종목의 7일 가격 + Stochastic %K 오버레이 차트 그리드.

전략: 신고가 근처인데 Stochastic %K가 낮은 종목 = 강한 추세 안의 단기 눌림목.
좌상단이 가장 낮은 Stochastic (매수 우선순위), 우하단으로 갈수록 올라감.

사용:
    python new_high_charts.py --output reports/new_high_charts_YYYYMMDD.png
"""
from __future__ import annotations

import argparse
import sys
import warnings
from datetime import datetime
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yfinance as yf

from stock_report import US, NAMES, get_name  # 유니버스 재사용

warnings.filterwarnings("ignore")

STOCH_PERIOD = 14
DISPLAY_DAYS = 7
FETCH_PERIOD = "3mo"
MAX_STOCKS = 20
GRID_COLS = 4
PCT_HIGH_MIN = 90.0  # 52주 고가의 90% 이상만 후보
TV_TOP_PCT = 30.0    # 거래대금 상위 30% 이내

# 매수 매력도 색상 (Stochastic %K 값에 따른 배경)
BUY_ZONE = 30   # 이하면 강한 매수 신호
NEUTRAL = 60    # 이상이면 과열


def stochastic_k(high: pd.Series, low: pd.Series, close: pd.Series, period: int = STOCH_PERIOD) -> pd.Series:
    lowest = low.rolling(period).min()
    highest = high.rolling(period).max()
    return 100 * (close - lowest) / (highest - lowest)


def fetch(symbols: list[str]) -> dict[str, pd.DataFrame]:
    """각 심볼별 OHLCV DataFrame을 반환."""
    print(f"Fetching {len(symbols)} tickers...", file=sys.stderr)
    raw = yf.download(
        symbols, period=FETCH_PERIOD, interval="1d",
        group_by="ticker", progress=False, threads=True, auto_adjust=False,
    )
    result: dict[str, pd.DataFrame] = {}
    for sym in symbols:
        try:
            if len(symbols) == 1:
                df = raw
            else:
                df = raw[sym]
            df = df.dropna(subset=["Close"])
            if len(df) >= STOCH_PERIOD + 2:
                result[sym] = df
        except (KeyError, ValueError):
            continue
    return result


def screen_candidates(data: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """52주 신고가 근접 + 거래대금 상위 필터를 통과한 종목의 요약."""
    rows = []
    for sym, df in data.items():
        close = df["Close"]
        high52 = close.tail(252).max() if len(close) >= 20 else close.max()
        last = float(close.iloc[-1])
        pct_h = last / high52 * 100 if high52 else 0.0
        if pct_h < PCT_HIGH_MIN:
            continue
        vol20 = (df["Close"] * df["Volume"]).tail(20).mean()
        rows.append({"sym": sym, "pct_h": pct_h, "tv20": float(vol20), "last": last, "high52": float(high52)})
    if not rows:
        return pd.DataFrame()
    df_out = pd.DataFrame(rows)
    tv_threshold = df_out["tv20"].quantile(1 - TV_TOP_PCT / 100)
    df_out = df_out[df_out["tv20"] >= tv_threshold].reset_index(drop=True)
    return df_out


def compute_stoch_for_candidates(candidates: pd.DataFrame, data: dict[str, pd.DataFrame]) -> pd.DataFrame:
    stoch_vals = []
    for sym in candidates["sym"]:
        df = data[sym]
        k = stochastic_k(df["High"], df["Low"], df["Close"])
        stoch_vals.append(float(k.iloc[-1]))
    candidates = candidates.copy()
    candidates["stoch_k"] = stoch_vals
    return candidates.sort_values("stoch_k", ascending=True).reset_index(drop=True)


def cell_bg(stoch_val: float) -> str | None:
    if stoch_val <= BUY_ZONE:
        return "#e8f7ec"  # 연한 초록: 매수 매력 구간
    if stoch_val >= NEUTRAL + 20:
        return "#fdecec"  # 연한 빨강: 과열 경고
    return None


def draw_cell(ax_price, sym: str, ohlcv: pd.DataFrame, stoch_series: pd.Series, high52: float) -> None:
    tail = ohlcv.tail(DISPLAY_DAYS)
    stoch_tail = stoch_series.tail(DISPLAY_DAYS)
    x = np.arange(len(tail))

    stoch_now = float(stoch_series.iloc[-1])
    last_close = float(tail["Close"].iloc[-1])
    pct_from_high = last_close / high52 * 100

    bg = cell_bg(stoch_now)
    if bg is not None:
        ax_price.set_facecolor(bg)

    # 가격 (High-Low bar + 종가 표시)
    ax_price.vlines(x, tail["Low"], tail["High"], color="#333", linewidth=1.5, alpha=0.6)
    ax_price.plot(x, tail["Close"], color="#0d47a1", linewidth=2.0, marker="o", markersize=4)

    # 52주 고가 라인 (표시 범위 안이면)
    if tail["High"].max() >= high52 * 0.98:
        ax_price.axhline(high52, color="#c62828", linewidth=0.8, linestyle="--", alpha=0.6)

    # Stochastic %K (오른쪽 y축, 0~100)
    ax_stoch = ax_price.twinx()
    ax_stoch.plot(x, stoch_tail, color="#ff8c00", linewidth=1.8, alpha=0.85, marker="s", markersize=3)
    ax_stoch.axhline(20, color="#4caf50", linewidth=0.5, linestyle=":", alpha=0.5)
    ax_stoch.axhline(80, color="#f44336", linewidth=0.5, linestyle=":", alpha=0.5)
    ax_stoch.set_ylim(0, 100)
    ax_stoch.set_yticks([0, 20, 50, 80, 100])
    ax_stoch.tick_params(axis="y", labelsize=6, colors="#ff8c00")

    # 축 정리
    ax_price.set_xticks(x)
    ax_price.set_xticklabels([d.strftime("%m/%d") for d in tail.index], fontsize=6, rotation=0)
    ax_price.tick_params(axis="y", labelsize=6)
    ax_price.grid(True, alpha=0.15, linewidth=0.5)

    # 제목 (영어로 표기 - GitHub Actions 환경에 한글 폰트 없음)
    display_name = NAMES.get(sym, sym)
    if not display_name.isascii():
        display_name = sym  # 한국 종목명은 티커로 대체
    title = f"{sym}  %K={stoch_now:.0f}  |  {display_name}"
    subtitle = f"${last_close:.2f}   52W: {pct_from_high:.1f}%"
    ax_price.set_title(title, fontsize=8, fontweight="bold", loc="left", pad=2)
    ax_price.text(
        0.99, 0.02, subtitle,
        transform=ax_price.transAxes, fontsize=6.5, ha="right", va="bottom",
        color="#555", fontfamily="monospace",
        bbox=dict(facecolor="white", edgecolor="none", alpha=0.7, pad=1.5),
    )


def build_grid(
    candidates: pd.DataFrame,
    data: dict[str, pd.DataFrame],
    output_path: Path,
) -> None:
    n = min(len(candidates), MAX_STOCKS)
    if n == 0:
        # 신고가 종목이 없을 때도 빈 표지 이미지 생성
        fig, ax = plt.subplots(figsize=(8, 4))
        ax.text(0.5, 0.5, "No 52W-high candidates found today",
                ha="center", va="center", fontsize=14)
        ax.axis("off")
        fig.savefig(output_path, dpi=140, bbox_inches="tight")
        plt.close(fig)
        return

    candidates = candidates.head(n)
    rows = (n + GRID_COLS - 1) // GRID_COLS
    fig, axes = plt.subplots(
        rows, GRID_COLS,
        figsize=(GRID_COLS * 3.6, rows * 2.4),
        squeeze=False,
    )
    fig.suptitle(
        f"52W-High Stocks — 7d Price + Stochastic %K  ({datetime.now().strftime('%Y-%m-%d')})\n"
        f"Sorted by Stoch %K ascending (lower = better pullback buy)  |  "
        f"green cell: %K ≤ {BUY_ZONE},  red cell: %K ≥ {NEUTRAL + 20}",
        fontsize=11, fontweight="bold", y=0.995,
    )

    for i in range(rows * GRID_COLS):
        r, c = divmod(i, GRID_COLS)
        ax = axes[r][c]
        if i >= n:
            ax.axis("off")
            continue
        row = candidates.iloc[i]
        sym = row["sym"]
        df = data[sym]
        stoch_series = stochastic_k(df["High"], df["Low"], df["Close"])
        draw_cell(ax, sym, df, stoch_series, row["high52"])

    fig.tight_layout(rect=[0, 0, 1, 0.97])
    fig.savefig(output_path, dpi=140, bbox_inches="tight")
    plt.close(fig)


def write_text_summary(candidates: pd.DataFrame, path: Path) -> None:
    lines = [
        "52주 신고가 종목 — Stochastic %K 낮은 순 (눌림목 매수 후보)",
        f"필터: 52주 고가 {PCT_HIGH_MIN:.0f}%↑ AND 거래대금 상위 {TV_TOP_PCT:.0f}%",
        f"기준일: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "",
        f"{'순위':<4}{'티커':<8}{'종목명':<18}{'%K':>6}{'종가':>10}{'52W%':>8}",
        "-" * 60,
    ]
    for i, r in candidates.iterrows():
        name = get_name(r["sym"]) if r["sym"] in NAMES else r["sym"]
        mark = " ★" if r["stoch_k"] <= BUY_ZONE else "  "
        lines.append(
            f"{i+1:<4}{r['sym']:<8}{name[:16]:<18}"
            f"{r['stoch_k']:>6.0f}"
            f"{r['last']:>10.2f}"
            f"{r['last']/r['high52']*100:>7.1f}%"
            f"{mark}"
        )
    lines.append("")
    lines.append("★ = Stochastic 30 이하 (매수 매력 구간)")
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", default="reports")
    parser.add_argument("--image", default=None, help="차트 PNG 파일명 (기본: 자동)")
    parser.add_argument("--text", default=None, help="텍스트 요약 파일명 (기본: 자동)")
    args = parser.parse_args()

    today = datetime.now().strftime("%Y%m%d")
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    image_path = out_dir / (args.image or f"new_high_charts_{today}.png")
    text_path = out_dir / (args.text or f"new_high_charts_{today}.txt")

    data = fetch(US)
    candidates = screen_candidates(data)

    if candidates.empty:
        build_grid(candidates, data, image_path)
        text_path.write_text("52주 신고가 종목 없음", encoding="utf-8")
        print(f"No candidates found. Wrote empty {image_path}")
        return

    ranked = compute_stoch_for_candidates(candidates, data)
    build_grid(ranked, data, image_path)
    write_text_summary(ranked, text_path)
    print(f"Wrote {image_path} ({len(ranked)} candidates) and {text_path}")


if __name__ == "__main__":
    main()
