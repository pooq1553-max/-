#!/usr/bin/env python3
"""샘플 데이터로 보고서 생성 데모"""
import pandas as pd
from stock_report import generate_report

# 2026년 3월 20일(금) 기준 샘플 데이터 (가상)
sample_data = [
    # ─── US 시장 ───
    # 52주 신고가 근접 + 거래대금 상위 (AND 조건 충족)
    dict(sym="NVDA",  price=152.40, chg=3.21, h52=155.00, l52=75.50,
         pct_h=98.3, mc=3.74e12, vol=85_000_000, avg_vol=52_000_000,
         vol_r=1.63, tv=12.95e9, avg_tv=7.8e9, tv_ratio=1.66, mkt="US"),
    dict(sym="AVGO",  price=228.50, chg=2.15, h52=231.00, l52=128.40,
         pct_h=98.9, mc=1.07e12, vol=25_000_000, avg_vol=18_000_000,
         vol_r=1.39, tv=5.71e9, avg_tv=4.1e9, tv_ratio=1.39, mkt="US"),
    dict(sym="META",  price=632.80, chg=1.85, h52=645.00, l52=390.20,
         pct_h=98.1, mc=1.60e12, vol=18_000_000, avg_vol=14_000_000,
         vol_r=1.29, tv=11.39e9, avg_tv=8.5e9, tv_ratio=1.34, mkt="US"),
    dict(sym="PLTR",  price=98.50, chg=4.52, h52=100.00, l52=22.10,
         pct_h=98.5, mc=224e9, vol=120_000_000, avg_vol=65_000_000,
         vol_r=1.85, tv=11.82e9, avg_tv=5.9e9, tv_ratio=2.00, mkt="US"),
    dict(sym="ORCL",  price=185.20, chg=1.32, h52=192.00, l52=112.50,
         pct_h=96.5, mc=510e9, vol=15_000_000, avg_vol=12_000_000,
         vol_r=1.25, tv=2.78e9, avg_tv=2.1e9, tv_ratio=1.32, mkt="US"),
    dict(sym="COST",  price=985.00, chg=0.95, h52=1010.00, l52=680.20,
         pct_h=97.5, mc=437e9, vol=3_200_000, avg_vol=2_800_000,
         vol_r=1.14, tv=3.15e9, avg_tv=2.7e9, tv_ratio=1.17, mkt="US"),
    dict(sym="NFLX",  price=1025.30, chg=2.80, h52=1050.00, l52=550.00,
         pct_h=97.6, mc=445e9, vol=8_500_000, avg_vol=5_200_000,
         vol_r=1.63, tv=8.71e9, avg_tv=5.3e9, tv_ratio=1.64, mkt="US"),
    dict(sym="LLY",   price=880.50, chg=1.10, h52=920.00, l52=560.00,
         pct_h=95.7, mc=837e9, vol=4_200_000, avg_vol=3_500_000,
         vol_r=1.20, tv=3.70e9, avg_tv=3.0e9, tv_ratio=1.23, mkt="US"),
    dict(sym="CRM",   price=345.60, chg=0.65, h52=365.00, l52=210.00,
         pct_h=94.7, mc=335e9, vol=7_000_000, avg_vol=6_500_000,
         vol_r=1.08, tv=2.42e9, avg_tv=2.2e9, tv_ratio=1.10, mkt="US"),
    dict(sym="NOW",   price=1050.00, chg=1.55, h52=1080.00, l52=620.00,
         pct_h=97.2, mc=215e9, vol=2_100_000, avg_vol=1_800_000,
         vol_r=1.17, tv=2.21e9, avg_tv=1.8e9, tv_ratio=1.23, mkt="US"),
    # 거래대금 높지만 52주 고가 미달 (AND 조건 미충족 — 필터링됨)
    dict(sym="TSLA",  price=265.00, chg=-1.20, h52=420.00, l52=138.80,
         pct_h=63.1, mc=845e9, vol=95_000_000, avg_vol=80_000_000,
         vol_r=1.19, tv=25.18e9, avg_tv=20.5e9, tv_ratio=1.23, mkt="US"),
    dict(sym="AAPL",  price=228.50, chg=0.35, h52=260.00, l52=164.08,
         pct_h=87.9, mc=3.50e12, vol=55_000_000, avg_vol=48_000_000,
         vol_r=1.15, tv=12.57e9, avg_tv=10.8e9, tv_ratio=1.16, mkt="US"),
    # ─── KR 시장 ───
    dict(sym="005930.KS", price=83500, chg=2.45, h52=85000, l52=52600,
         pct_h=98.2, mc=498e12, vol=25_000_000, avg_vol=15_000_000,
         vol_r=1.67, tv=2.09e12, avg_tv=1.2e12, tv_ratio=1.74, mkt="KR"),
    dict(sym="000660.KS", price=215000, chg=3.61, h52=218000, l52=130000,
         pct_h=98.6, mc=156e12, vol=5_500_000, avg_vol=3_200_000,
         vol_r=1.72, tv=1.18e12, avg_tv=680e9, tv_ratio=1.74, mkt="KR"),
    dict(sym="035420.KS", price=385000, chg=1.85, h52=395000, l52=185000,
         pct_h=97.5, mc=63e12, vol=1_200_000, avg_vol=900_000,
         vol_r=1.33, tv=462e9, avg_tv=340e9, tv_ratio=1.36, mkt="KR"),
    dict(sym="068270.KS", price=225000, chg=4.17, h52=228000, l52=128000,
         pct_h=98.7, mc=31e12, vol=3_800_000, avg_vol=2_100_000,
         vol_r=1.81, tv=855e9, avg_tv=470e9, tv_ratio=1.82, mkt="KR"),
    dict(sym="247540.KQ", price=320000, chg=5.26, h52=325000, l52=140000,
         pct_h=98.5, mc=22e12, vol=1_500_000, avg_vol=700_000,
         vol_r=2.14, tv=480e9, avg_tv=210e9, tv_ratio=2.29, mkt="KR"),
    dict(sym="196170.KQ", price=285000, chg=3.64, h52=290000, l52=52000,
         pct_h=98.3, mc=19e12, vol=2_200_000, avg_vol=1_400_000,
         vol_r=1.57, tv=627e9, avg_tv=380e9, tv_ratio=1.65, mkt="KR"),
    # KR - 52주 고가 미달 (필터링됨)
    dict(sym="005380.KS", price=245000, chg=0.82, h52=310000, l52=168000,
         pct_h=79.0, mc=52e12, vol=2_000_000, avg_vol=1_800_000,
         vol_r=1.11, tv=490e9, avg_tv=430e9, tv_ratio=1.14, mkt="KR"),
]

df = pd.DataFrame(sample_data)

report = generate_report(df)
print(report)

with open("report_friday_example.txt", "w", encoding="utf-8") as f:
    f.write(report)

print("(report_friday_example.txt 저장 완료)")
