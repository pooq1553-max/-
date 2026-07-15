"""미너비니 Trend Template 통과 종목 중 베이스 다지기 진행 중인 후보 스캔.

파도타기의 타이밍:
- Trend Template 8개 요건 전부 통과 = Stage 2 확인
- 5~26주 지속되는 베이스가 정상. 26주 초과 = 피로, 5주 미만 = 미성숙.
- 베이스 카운트 낮을수록 (1~2차) 우선. 4차 이상은 후기 리스크.
- 최근 변동성 수축 (last 2주 range vs prior 4주 range) 시 임박한 돌파.

우선순위 점수 = RS Rating × 베이스 성숙도 × 수축 정도 × 카운트 페널티.
"""
from __future__ import annotations

import argparse
import sys
import warnings
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yfinance as yf

warnings.filterwarnings("ignore")

# ─── 파라미터 ───
MIN_BASE_WEEKS = 5
MAX_BASE_WEEKS = 26
MIN_TREND_DAYS = 200  # 최소 히스토리 요건
RS_MIN = 70            # Trend Template #8
DISPLAY_TOP_N = 20
GRID_COLS = 4


# ─── 유니버스 획득 ───
_SP500_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
_NDX_URL = "https://en.wikipedia.org/wiki/Nasdaq-100"


def fetch_universe() -> list[str]:
    """S&P 500 ∪ NASDAQ-100 티커. Wikipedia 실패 시 fallback."""
    tickers: set[str] = set()
    try:
        sp = pd.read_html(_SP500_URL, match="Symbol")[0]
        sp_col = "Symbol" if "Symbol" in sp.columns else sp.columns[0]
        tickers.update(sp[sp_col].astype(str).str.replace(".", "-", regex=False).tolist())
        print(f"S&P 500: {len(tickers)} tickers", file=sys.stderr)
    except Exception as e:
        print(f"S&P 500 fetch failed: {e}", file=sys.stderr)
    try:
        # NDX 페이지의 여러 표 중 Ticker 열이 있는 표를 찾음
        for tbl in pd.read_html(_NDX_URL):
            col = None
            for c in tbl.columns:
                if str(c).strip().lower() in ("ticker", "symbol"):
                    col = c
                    break
            if col is not None:
                ndx_syms = tbl[col].astype(str).str.replace(".", "-", regex=False).tolist()
                tickers.update(ndx_syms)
                print(f"NASDAQ 100 (+): now {len(tickers)} tickers", file=sys.stderr)
                break
    except Exception as e:
        print(f"NASDAQ 100 fetch failed: {e}", file=sys.stderr)
    tickers.discard("nan")
    tickers = {t for t in tickers if t and t.isascii() and len(t) <= 6}
    if not tickers:
        # 최후 fallback: 주요 대형주
        from stock_report import US  # type: ignore
        return sorted(US)
    return sorted(tickers)


# ─── OHLCV 다운로드 ───
def fetch_prices(tickers: list[str]) -> dict[str, pd.DataFrame]:
    print(f"Downloading {len(tickers)} tickers (1y OHLCV)...", file=sys.stderr)
    raw = yf.download(
        tickers, period="1y", interval="1d",
        group_by="ticker", progress=False, threads=True, auto_adjust=False,
    )
    result: dict[str, pd.DataFrame] = {}
    for sym in tickers:
        try:
            df = raw[sym] if len(tickers) > 1 else raw
            df = df.dropna(subset=["Close"])
            if len(df) >= MIN_TREND_DAYS:
                result[sym] = df
        except (KeyError, ValueError):
            continue
    print(f"Usable data for {len(result)} tickers", file=sys.stderr)
    return result


# ─── Trend Template ───
@dataclass
class TrendCheck:
    passed: bool
    price: float
    ma50: float
    ma150: float
    ma200: float
    ma200_slope_up: bool
    pct_from_low: float
    pct_from_high: float


def check_trend_template(df: pd.DataFrame) -> TrendCheck:
    close = df["Close"]
    price = float(close.iloc[-1])
    ma50 = float(close.tail(50).mean())
    ma150 = float(close.tail(150).mean())
    ma200 = float(close.tail(200).mean())
    ma200_prev = float(close.iloc[-220:-200].mean()) if len(close) >= 220 else ma200
    ma200_slope_up = ma200 > ma200_prev

    high52 = float(df["High"].tail(252).max())
    low52 = float(df["Low"].tail(252).min())
    pct_from_low = (price / low52 - 1) * 100 if low52 else 0.0
    pct_from_high = (price / high52) * 100 if high52 else 0.0

    passed = (
        price > ma150 and price > ma200
        and ma150 > ma200
        and ma200_slope_up
        and ma50 > ma150 > ma200
        and price > ma50
        and pct_from_low >= 25
        and pct_from_high >= 75
    )
    return TrendCheck(passed, price, ma50, ma150, ma200, ma200_slope_up, pct_from_low, pct_from_high)


# ─── RS Rating (IBD 스타일 근사) ───
def compute_rs_ratings(data: dict[str, pd.DataFrame]) -> dict[str, float]:
    """3/6/9/12개월 수익률 가중치로 종합해 유니버스 대비 백분위 반환."""
    weighted_returns: dict[str, float] = {}
    for sym, df in data.items():
        c = df["Close"]
        if len(c) < 252:
            continue
        last = c.iloc[-1]
        try:
            r3 = last / c.iloc[-63] - 1
            r6 = last / c.iloc[-126] - 1
            r9 = last / c.iloc[-189] - 1
            r12 = last / c.iloc[-252] - 1
        except (IndexError, ZeroDivisionError):
            continue
        weighted_returns[sym] = 0.4 * r3 + 0.2 * r6 + 0.2 * r9 + 0.2 * r12
    if not weighted_returns:
        return {}
    s = pd.Series(weighted_returns)
    percentiles = s.rank(pct=True) * 99 + 1  # 1~100
    return percentiles.to_dict()


# ─── 베이스 분석 ───
@dataclass
class BaseInfo:
    weeks: float
    depth_pct: float           # (high - low) / high * 100
    pivot: float               # 베이스 고점
    dist_to_pivot_pct: float   # 현재 가격이 피봇 몇 % 아래 (음수면 돌파)
    contraction_pct: float     # (prior_range - recent_range) / prior_range * 100
    in_range: bool             # 5-26주 정상 범위 여부
    healthy_depth: bool        # 깊이 ≤ 35%


def analyze_base(df: pd.DataFrame) -> BaseInfo:
    """최근 26주 내에서 베이스 다지기 구간 식별."""
    lookback = min(len(df), MAX_BASE_WEEKS * 5 + 5)
    seg = df.tail(lookback)
    close = seg["Close"]
    high = seg["High"]
    low = seg["Low"]

    # 베이스 시작 = 이번 lookback 내 가장 최근 최고 고점 이후
    idx_peak = int(high.values.argmax())  # 0-based
    if idx_peak == len(seg) - 1:
        # 현재가 최고점 = 아직 베이스 없음 (또는 방금 형성 시작)
        weeks = 0.0
        depth = 0.0
        pivot = float(high.iloc[-1])
    else:
        pivot = float(high.iloc[idx_peak])
        base_slice = seg.iloc[idx_peak:]
        base_low = float(base_slice["Low"].min())
        depth = (pivot - base_low) / pivot * 100
        weeks = (len(base_slice) - 1) / 5.0

    price = float(close.iloc[-1])
    dist_to_pivot_pct = (price / pivot - 1) * 100

    # 변동성 수축: 마지막 10일 range vs 이전 20일 range (평균화)
    if len(seg) >= 30:
        recent = seg.tail(10)
        prior = seg.iloc[-30:-10]
        recent_range = (recent["High"].max() - recent["Low"].min()) / recent["Close"].mean() * 100
        prior_range = (prior["High"].max() - prior["Low"].min()) / prior["Close"].mean() * 100
        contraction = (1 - recent_range / prior_range) * 100 if prior_range > 0 else 0.0
    else:
        contraction = 0.0

    in_range = MIN_BASE_WEEKS <= weeks <= MAX_BASE_WEEKS
    healthy_depth = depth <= 35
    return BaseInfo(weeks, depth, pivot, dist_to_pivot_pct, contraction, in_range, healthy_depth)


# ─── 베이스 카운트 (근사) ───
def count_bases(df: pd.DataFrame) -> int:
    """Stage 2 시작 이후 10%+ 눌림 개수. 최소 1."""
    close = df["Close"]
    # Stage 2 시작 근사: 200MA가 처음으로 상승 반전한 지점 이후
    ma200 = close.rolling(200).mean()
    if ma200.notna().sum() < 30:
        return 1
    # 최근 200MA 상승 지속 구간 찾기
    slope = ma200.diff(10) > 0  # 10일 기울기 양수
    if not slope.iloc[-1]:
        return 1
    # 뒤에서부터 slope가 True인 구간의 시작
    slope_last = slope.iloc[::-1]
    stage2_start_from_end = 0
    for v in slope_last:
        if not v:
            break
        stage2_start_from_end += 1
    start_idx = len(close) - stage2_start_from_end
    stage2_slice = close.iloc[start_idx:]
    if len(stage2_slice) < 20:
        return 1

    # 10%+ 눌림 카운트: rolling max 대비 -10% 이하로 떨어진 후 회복하는 구간
    peaks_encountered = 0
    running_max = stage2_slice.iloc[0]
    pulled_back = False
    for v in stage2_slice.values:
        if v > running_max:
            if pulled_back:
                peaks_encountered += 1
                pulled_back = False
            running_max = v
        elif v <= running_max * 0.90:
            pulled_back = True
    return max(1, peaks_encountered + 1)


# ─── 후보 스코어링 ───
@dataclass
class Candidate:
    sym: str
    trend: TrendCheck
    base: BaseInfo
    base_count: int
    rs_rating: float
    score: float


def score_candidate(trend: TrendCheck, base: BaseInfo, base_count: int, rs: float) -> float:
    # RS는 이미 1~100. 여기에 베이스 품질과 카운트 페널티를 곱함.
    quality = 1.0
    if base.in_range:
        quality *= 1.5
    if base.healthy_depth:
        quality *= 1.2
    if base.contraction_pct >= 30:
        quality *= 1.3
    elif base.contraction_pct >= 15:
        quality *= 1.15
    if abs(base.dist_to_pivot_pct) <= 5:
        quality *= 1.2  # 피봇 근접

    # 베이스 카운트 페널티
    count_mult = {1: 1.15, 2: 1.10, 3: 1.0, 4: 0.85}.get(base_count, 0.7)

    return rs * quality * count_mult


# ─── 렌더링 ───
def write_text_report(candidates: list[Candidate], path: Path) -> None:
    lines = [
        "미너비니 Trend Template 통과 + 베이스 다지기 진행 종목",
        f"기준일: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"필터: Trend Template 8개 요건 + RS ≥ {RS_MIN}",
        f"정렬: RS × 베이스 품질 × 카운트 페널티 (높을수록 파도타기 매수 우선)",
        "",
        "베이스 상태 기호:",
        "  ✓ = 5~26주 정상 범위 / 깊이 35% 이하 / 수축 진행",
        "  △ = 정상 범위 벗어남 (5주 미만 or 26주 초과)",
        "  ! = 깊이 35% 초과 (베이스 손상 가능)",
        "",
        f"{'순위':<4}{'티커':<8}{'RS':>4}  {'베이스':>7}{'깊이':>7}{'수축':>7}  {'피봇거리':>9}  {'카운트':>4}  {'상태':<6}",
        "-" * 76,
    ]
    for i, c in enumerate(candidates, 1):
        status = "✓" if c.base.in_range and c.base.healthy_depth else ("△" if not c.base.in_range else "!")
        lines.append(
            f"{i:<4}"
            f"{c.sym:<8}"
            f"{c.rs_rating:>4.0f}  "
            f"{c.base.weeks:>5.1f}주 "
            f"{c.base.depth_pct:>5.1f}% "
            f"{c.base.contraction_pct:>5.1f}% "
            f"{c.base.dist_to_pivot_pct:>+7.1f}%  "
            f"{c.base_count:>4}  "
            f"{status:<6}"
        )
    lines.append("")
    lines.append("피봇거리: 음수 = 아직 베이스 안, 양수 = 피봇 돌파 진행")
    lines.append("")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _draw_stock(ax, sym: str, df: pd.DataFrame, cand: Candidate) -> None:
    tail = df.tail(126)  # 최근 6개월
    close = tail["Close"]
    x = np.arange(len(tail))
    ma50 = tail["Close"].rolling(50).mean()
    ma150 = tail["Close"].rolling(150).mean()
    ma200 = tail["Close"].rolling(200).mean()

    # 참고용 전체 MA 계산에는 tail 이전 데이터 필요 → 전체 df에서 계산 후 tail
    full_ma50 = df["Close"].rolling(50).mean().tail(126)
    full_ma150 = df["Close"].rolling(150).mean().tail(126)
    full_ma200 = df["Close"].rolling(200).mean().tail(126)

    ax.plot(x, close, color="#0d47a1", linewidth=1.4)
    ax.plot(x, full_ma50, color="#00897b", linewidth=0.9, alpha=0.85, label="50")
    ax.plot(x, full_ma150, color="#f57c00", linewidth=0.9, alpha=0.85, label="150")
    ax.plot(x, full_ma200, color="#c62828", linewidth=0.9, alpha=0.85, label="200")

    ax.axhline(cand.base.pivot, color="#7b1fa2", linewidth=0.9, linestyle="--", alpha=0.7)

    # 베이스 구간 음영
    if cand.base.weeks > 0:
        base_days = int(cand.base.weeks * 5)
        base_start = max(0, len(tail) - base_days - 1)
        ax.axvspan(base_start, len(tail) - 1, color="#fff59d", alpha=0.28)

    ax.set_xticks([])
    ax.tick_params(axis="y", labelsize=6)
    ax.grid(True, alpha=0.15, linewidth=0.5)

    title = f"{sym}  RS={cand.rs_rating:.0f}  base#{cand.base_count}"
    ax.set_title(title, fontsize=8, fontweight="bold", loc="left", pad=2)
    subtitle = (
        f"${cand.trend.price:.1f}   "
        f"{cand.base.weeks:.1f}w / {cand.base.depth_pct:.0f}%   "
        f"pivot {cand.base.dist_to_pivot_pct:+.1f}%"
    )
    ax.text(
        0.99, 0.02, subtitle,
        transform=ax.transAxes, fontsize=6.3, ha="right", va="bottom",
        color="#333", fontfamily="monospace",
        bbox=dict(facecolor="white", edgecolor="none", alpha=0.75, pad=1.5),
    )


def draw_top_grid(candidates: list[Candidate], data: dict[str, pd.DataFrame], path: Path) -> None:
    top = candidates[:DISPLAY_TOP_N]
    if not top:
        fig, ax = plt.subplots(figsize=(8, 4))
        ax.text(0.5, 0.5, "No Stage 2 candidates today", ha="center", va="center", fontsize=14)
        ax.axis("off")
        fig.savefig(path, dpi=140, bbox_inches="tight")
        plt.close(fig)
        return

    n = len(top)
    rows = (n + GRID_COLS - 1) // GRID_COLS
    fig, axes = plt.subplots(rows, GRID_COLS, figsize=(GRID_COLS * 3.6, rows * 2.4), squeeze=False)
    fig.suptitle(
        f"Stage 2 + Base Consolidation  ({datetime.now().strftime('%Y-%m-%d')})\n"
        "yellow band = current base | dashed = pivot | 50/150/200 MA overlaid",
        fontsize=11, fontweight="bold", y=0.995,
    )
    for i in range(rows * GRID_COLS):
        r, c = divmod(i, GRID_COLS)
        ax = axes[r][c]
        if i >= n:
            ax.axis("off")
            continue
        cand = top[i]
        _draw_stock(ax, cand.sym, data[cand.sym], cand)
    fig.tight_layout(rect=[0, 0, 1, 0.97])
    fig.savefig(path, dpi=140, bbox_inches="tight")
    plt.close(fig)


# ─── 메인 ───
def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", default="reports")
    parser.add_argument("--txt", default=None)
    parser.add_argument("--png", default=None)
    args = parser.parse_args()

    today = datetime.now().strftime("%Y%m%d")
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    txt_path = out_dir / (args.txt or f"stage2_{today}.txt")
    png_path = out_dir / (args.png or f"stage2_{today}.png")

    universe = fetch_universe()
    print(f"Universe size: {len(universe)}", file=sys.stderr)
    data = fetch_prices(universe)

    rs_ratings = compute_rs_ratings(data)

    candidates: list[Candidate] = []
    for sym, df in data.items():
        trend = check_trend_template(df)
        if not trend.passed:
            continue
        rs = rs_ratings.get(sym, 0)
        if rs < RS_MIN:
            continue
        base = analyze_base(df)
        base_count = count_bases(df)
        score = score_candidate(trend, base, base_count, rs)
        candidates.append(Candidate(sym, trend, base, base_count, rs, score))

    candidates.sort(key=lambda c: c.score, reverse=True)
    print(f"Passing candidates: {len(candidates)}", file=sys.stderr)

    write_text_report(candidates, txt_path)
    draw_top_grid(candidates, data, png_path)
    print(f"Wrote {txt_path} and {png_path}")


if __name__ == "__main__":
    main()
