import requests
H = {"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)", "Referer": "https://m.stock.naver.com/"}
B = "https://m.stock.naver.com/api"
urls = [f"{B}/index/KOSPI/trend?bizdate=20260922", f"{B}/index/KOSPI/trend?date=20260922",
        f"{B}/index/KOSPI/trend/20260922", f"{B}/index/KOSPI/trends", f"{B}/index/KOSPI/trend/daily",
        f"{B}/index/KOSPI/dealTrend", f"{B}/index/KOSPI/investor", f"{B}/index/KOSDAQ/trend",
        f"{B}/index/KOSPI/trend?startDate=20260921&endDate=20260923",
        f"{B}/stocks/foreignerBuy/KOSPI?page=1&pageSize=3", f"{B}/stocks/netBuying/KOSPI?page=1&pageSize=3",
        f"{B}/stocks/up/KOSPI?page=1&pageSize=2", f"{B}/stocks/searchTop/KOSPI?page=1&pageSize=2"]
for u in urls:
    try:
        r = requests.get(u, headers=H, timeout=10)
        print(f"### {r.status_code} {u}\n{r.content[:300].decode('utf-8','replace')!r}\n")
    except Exception as e:
        print(f"### ERR {u} {e}\n")
