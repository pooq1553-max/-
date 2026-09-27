import requests
H = {"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)", "Referer": "https://m.stock.naver.com/"}
urls = [
    "https://m.stock.naver.com/api/index/KOSPI/trend",
    "https://m.stock.naver.com/api/index/KOSPI/trend?pageSize=10&page=1",
    "https://m.stock.naver.com/api/index/KOSPI/investorTrend",
    "https://m.stock.naver.com/api/index/KOSPI/integration",
    "https://m.stock.naver.com/api/index/KOSPI/basic",
    "https://api.stock.naver.com/index/KOSPI/trend",
    "https://m.stock.naver.com/front-api/index/trend?indexCode=KOSPI",
    "https://m.stock.naver.com/api/stocks/marketValue/KOSPI?page=1&pageSize=5",
    "https://m.stock.naver.com/api/stocks/foreignBuy/KOSPI?page=1&pageSize=5",
    "https://finance.naver.com/sise/sise_trans_style.naver",
    "https://finance.naver.com/sise/sise_deal_rank_iframe.naver?sosok=01&investor_gubun=9000&type=buy",
]
for u in urls:
    try:
        r = requests.get(u, headers=H, timeout=10)
        body = r.content[:600].decode("utf-8", "replace") if "json" in r.headers.get("content-type", "") else r.content.decode("euc-kr", "replace")[:0] + r.content[:400].decode("utf-8", "replace")
        print(f"### {r.status_code} {r.headers.get('content-type')} {u}\n{body!r}\n")
    except Exception as e:
        print(f"### ERR {u} {e}\n")
