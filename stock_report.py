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
import time
import unicodedata
import warnings
import sys
from datetime import datetime, timedelta
from io import StringIO

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.patches import FancyBboxPatch
import numpy as np

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

# ─── 섹터 매핑 ───
US_SECTORS = {
    "반도체":     ["NVDA","AMD","INTC","QCOM","TXN","AMAT","LRCX","KLAC","AVGO","MRVL",
                   "ARM","SMCI","NXPI","ON","MCHP","ADI","MU","SNPS","CDNS"],
    "빅테크":     ["AAPL","MSFT","GOOGL","AMZN","META","TSLA"],
    "소프트웨어":  ["CRM","ADBE","ORCL","NOW","INTU","WDAY","TEAM","SNOW","ANSS"],
    "사이버보안":  ["CRWD","PANW","FTNT","ZS","NET"],
    "클라우드/SaaS":["DDOG","SHOP","CSCO","IBM"],
    "핀테크/결제": ["V","MA","SQ","COIN","AXP","ICE","CME","SPGI","MCO","MSCI"],
    "금융":       ["JPM","BAC","WFC","GS","MS","C","BLK","SCHW"],
    "헬스케어":   ["UNH","JNJ","MRK","ABBV","LLY","PFE","REGN","AMGN","GILD","VRTX",
                   "MRNA","BMY","CI"],
    "의료기기":   ["TMO","DHR","SYK","BSX","ABT","ISRG","ZTS","IDXX","DXCM"],
    "소비재":     ["PG","PEP","KO","COST","MCD","WMT","HD"],
    "미디어/엔터": ["NFLX","DIS","CMCSA"],
    "통신":       ["T","VZ","TMUS"],
    "플랫폼":     ["PLTR","UBER","ABNB","DASH"],
    "에너지":     ["XOM","CVX"],
    "산업재":     ["CAT","DE","HON","GE","RTX","BA","LMT","NOC","TT","IR"],
    "운송/물류":  ["UPS","FDX"],
    "리츠/유틸":  ["AMT","PLD","CCI","EQIX","NEE","DUK","SO"],
    "기타":       ["BRK-B","DELL","APH","CTAS","ADP","ROP","ACN"],
}

KR_SECTORS = {
    "반도체":     ["005930.KS","000660.KS","042700.KS","009150.KS",
                   "067310.KQ","036930.KQ","095340.KQ","039030.KQ","240810.KQ",
                   "403870.KQ","058470.KQ","022100.KQ","307950.KQ"],
    "2차전지":    ["051910.KS","006400.KS","003670.KS",
                   "247540.KQ","086520.KQ","078600.KQ","097520.KQ","278280.KQ"],
    "자동차":     ["005380.KS","000270.KS","012330.KS","161390.KS",
                   "064350.KQ"],
    "조선/중공업": ["009540.KS","010140.KS","010620.KS","329180.KS",
                    "267250.KS","272210.KS","047810.KS"],
    "금융":       ["055550.KS","105560.KS","086790.KS","316140.KS","024110.KS",
                   "000810.KS","006800.KS","071050.KS","138040.KS","005830.KS",
                   "032830.KS"],
    "인터넷/플랫폼":["035420.KS","035720.KS",
                     "377300.KQ","323410.KQ","293490.KQ"],
    "바이오":     ["068270.KS","207940.KS","128940.KS","000100.KS","326030.KS",
                   "302440.KS",
                   "196170.KQ","145020.KQ","091990.KQ","137310.KQ","298380.KQ",
                   "048410.KQ","174900.KQ","208710.KQ","028300.KQ","294090.KQ",
                   "237690.KQ","195940.KQ","369370.KQ"],
    "엔터/미디어": ["041510.KQ","035900.KQ","352820.KQ","251270.KQ",
                    "263750.KQ","112040.KQ"],
    "철강/화학":  ["005490.KS","011170.KS","011780.KS","010950.KS",
                   "004020.KS","009830.KS"],
    "건설/인프라": ["000720.KS","006360.KS","034020.KS","088980.KS"],
    "유틸/에너지": ["015760.KS","036460.KS","096770.KS","052690.KS",
                    "365270.KQ","336260.KQ"],
    "통신":       ["030200.KS","017670.KS","018260.KS"],
    "소비재/유통": ["028260.KS","033780.KS","090430.KS","002790.KS",
                    "021240.KS","023530.KS","008770.KS","097950.KS",
                    "383220.KQ","214150.KQ","257720.KQ"],
    "IT서비스":   ["402340.KS","259960.KS","036570.KS",
                   "042000.KQ","053800.KQ","043150.KQ","328130.KQ",
                   "090460.KQ","140860.KQ","348210.KQ","299030.KQ",
                   "222080.KQ","041190.KQ"],
    "기타":       ["034730.KS","078930.KS","180640.KS","035250.KS",
                   "010130.KS","047050.KS","100840.KS","192820.KS",
                   "011200.KS","357780.KQ"],
}

# ─── 미장 세부 테마 (관심종목 탭) ───
US_THEMES = {
    # 반도체
    "DRAM/메모리":      ["MU","SNDK","STX","WDC","NVMI"],
    "CPU":              ["AMD","INTC","ARM","QCOM"],
    "GPU/AI가속기":     ["NVDA","AVGO","MRVL","ALAB","CRDO"],
    "파운드리":         ["TSM","GFS","UMC","ASX","AMKR"],
    "반도체장비":       ["AMAT","LRCX","KLAC","ASML","TER","ONTO","ACMR","UCTT","AEIS","CAMT","VECO","AMBA"],
    "EDA/반도체IP":     ["SNPS","CDNS","ARM","LSCC","RMBS","CEVA"],
    "아날로그/전력반도체":["TXN","ADI","NXPI","ON","MCHP","MPWR","WOLF","STM","SLAB","SITM","POWI","DIOD"],
    "반도체소재":       ["ENTG","MKSI","IPGP","COHU","FORM","AXT"],

    # AI / 소프트웨어
    "AI인프라/데이터":  ["PLTR","SNOW","MDB","CFLT","DDOG","AI","BBAI","SOUN","TEM"],
    "클라우드":         ["MSFT","AMZN","GOOGL","ORCL","NOW","CRM","IBM"],
    "사이버보안":       ["CRWD","PANW","ZS","FTNT","S","NET","OKTA","CYBR","QLYS","TENB","RPD","VRNS"],
    "양자컴퓨팅":       ["IONQ","RGTI","QBTS","QUBT","ARQQ"],
    "엔터프라이즈SW":   ["ADBE","INTU","WDAY","TEAM","HUBS","ZM","DOCU","TWLO","PATH","MNDY","GTLB","BILL"],

    # 하드웨어 / 네트워킹
    "서버/데이터센터HW":["DELL","SMCI","HPE","ANET","PSTG","NTAP","VRT"],
    "광통신":           ["CIEN","LITE","COHR","AAOI","FN","APH","POET"],
    "네트워크장비":     ["CSCO","JNPR","EXTR","NTGR","CALX","HLIT"],

    # 전력 / 에너지 전환
    "원자력/우라늄":    ["CEG","VST","SMR","OKLO","LEU","CCJ","NNE","BWXT","UEC","DNN","UUUU","ASPI"],
    "전력장비/그리드":  ["ETN","PWR","GEV","EMR","HUBB","NVT","AZZ","POWL","GNRC","ATKR"],
    "태양광":           ["FSLR","ENPH","SEDG","RUN","NXT","ARRY","SHLS","CSIQ","JKS","MAXN","SPWR"],
    "풍력":             ["GEV","TPIC","AMSC","NEP"],
    "수소/연료전지":    ["PLUG","BE","BLDP","FCEL","HYSR"],
    "유틸리티":         ["NEE","DUK","SO","AEP","D","EXC","XEL","SRE","PCG","ED","WEC","ES"],

    # 전기차 / 모빌리티
    "전기차":           ["TSLA","RIVN","LCID","NIO","XPEV","LI","ZK","VFS"],
    "자율주행/라이다":  ["MBLY","LAZR","OUST","INVZ","AUR","PONY","GRAB","UBER","LYFT"],
    "전통자동차":       ["GM","F","STLA","TM","HMC","RACE"],
    "배터리/리튬":      ["ALB","SQM","PLL","LAC","QS","ENVX","FREY","SLDP","AMPX","MP"],
    "EV충전":           ["CHPT","BLNK","EVGO","WBX"],

    # 바이오 / 헬스케어
    "GLP-1/비만치료":   ["LLY","NVO","VKTX","ALT","TERN","GPCR","AMGN","ZEAL"],
    "대형제약":         ["JNJ","PFE","MRK","ABBV","BMY","AZN","GSK","SNY","NVS","TAK"],
    "바이오테크":       ["GILD","VRTX","REGN","BIIB","MRNA","BNTX","ALNY","INCY","EXAS","NBIX","SRPT","RARE","IONS","BMRN"],
    "의료기기":         ["ISRG","SYK","BSX","MDT","ABT","EW","ZBH","DXCM","PODD","TNDM","GMED","NVCR"],
    "의료보험/서비스":  ["UNH","ELV","CI","CVS","HUM","MCK","COR","CAH","HCA","THC","UHS"],
    "라이프사이언스툴": ["TMO","DHR","A","WAT","MTD","RVTY","ILMN","PACB","TXG","QGEN","BRKR"],

    # 금융
    "대형은행":         ["JPM","BAC","WFC","C","GS","MS"],
    "지역은행":         ["USB","PNC","TFC","MTB","FITB","RF","KEY","CFG","HBAN","ZION","CMA","WAL"],
    "결제":             ["V","MA","AXP","PYPL","FI","GPN","FOUR","TOST","XYZ","WEX"],
    "핀테크":           ["SOFI","AFRM","UPST","LC","HOOD","NU","DAVE","PGY","OPFI"],
    "크립토/마이닝":    ["COIN","MSTR","MARA","RIOT","CLSK","HUT","CIFR","WULF","BITF","HIVE","BTBT","GLXY","CORZ","IREN","BMNR"],
    "자산운용/PE":      ["BLK","BX","KKR","APO","ARES","TROW","BEN","SCHW","IBKR","OWL","TPG"],
    "보험":             ["BRK-B","PGR","ALL","TRV","CB","AIG","MET","PRU","HIG","AFL","CINF","EG"],
    "거래소/금융데이터":["ICE","CME","NDAQ","CBOE","SPGI","MCO","MSCI","FDS","MORN","TW","VIRT"],

    # 소비재 / 리테일
    "대형리테일":       ["WMT","COST","TGT","DG","DLTR","BJ","KR","ROST","TJX","BURL","FIVE","OLLI"],
    "이커머스":         ["AMZN","SHOP","ETSY","EBAY","W","CHWY","CVNA","MELI","SE","CPNG","BABA","PDD","JD","GLBE"],
    "음식료":           ["KO","PEP","MDLZ","GIS","HSY","KHC","CAG","CPB","SJM","MNST","CELH","KDP","K","TSN","HRL"],
    "레스토랑":         ["MCD","SBUX","CMG","YUM","QSR","DPZ","WING","SHAK","TXRH","DRI","CAVA","EAT"],
    "의류/스포츠":      ["NKE","LULU","DECK","ONON","SKX","VFC","RL","PVH","ANF","UAA","CROX","BIRK","GAP"],
    "화장품/뷰티":      ["EL","ULTA","COTY","ELF","IPAR"],
    "생활용품":         ["PG","CL","KMB","CHD","CLX","EPC","REYN"],
    "담배/주류":        ["PM","MO","BTI","STZ","DEO","TAP","SAM","BF-B"],
    "여행/항공":        ["DAL","UAL","AAL","LUV","ALK","BKNG","ABNB","EXPE","MAR","HLT","H","RCL","CCL","NCLH","TRIP"],
    "반려동물":         ["CHWY","IDXX","ZTS","FRPT","ELAN","TRUP","WOOF"],

    # 미디어 / 엔터
    "스트리밍/미디어":  ["NFLX","DIS","WBD","PARA","CMCSA","ROKU","SPOT","FUBO","LYV"],
    "게임":             ["EA","TTWO","RBLX","U","PLTK","APP","GRVY","SKLZ"],
    "카지노/베팅":      ["DKNG","PENN","CZR","MGM","LVS","WYNN","BYD","CHDN","FLUT","RSI"],
    "광고/마케팅테크":  ["GOOGL","META","TTD","APP","PINS","SNAP","RDDT","OMC","IPG","MGNI","CRTO","DV","ZETA","IAS"],
    "소셜/데이팅":      ["META","PINS","SNAP","RDDT","MTCH","BMBL","NXST"],

    # 산업 / 방산 / 우주
    "방산":             ["LMT","RTX","NOC","GD","LHX","HII","TXT","HWM","TDG","AXON","KTOS","AVAV","LDOS","BAH","CACI","SAIC","RCAT"],
    "우주/위성":        ["RKLB","LUNR","ASTS","PL","RDW","IRDM","VSAT","GSAT","SPCE","MNTS"],
    "항공기/부품":      ["BA","ERJ","HWM","TDG","SPR","HEI","CW","MOG-A"],
    "기계/중장비":      ["CAT","DE","CMI","PCAR","AGCO","TEX","OSK","URI","HRI","ALG","MTW"],
    "산업자동화/로봇":  ["ROK","ABB","SYM","NDSN","ZBRA","CGNX","MIDD","EMR","HON","AME","PH","DOV","ITW","IR","GGG"],
    "건설/엔지니어링":  ["PWR","EME","MTZ","ACM","J","FLR","DY","GVA","STRL","ROAD","IESC","PRIM"],
    "주택건설":         ["DHI","LEN","PHM","NVR","TOL","KBH","TMHC","MTH","MHO","BLDR","POOL","IBP"],
    "철도/운송":        ["UNP","CSX","NSC","CP","CNI"],
    "물류/택배":        ["UPS","FDX","XPO","ODFL","SAIA","CHRW","EXPD","GXO","JBHT","KNX","RXO"],
    "해운/탱커":        ["ZIM","MATX","SBLK","GNK","EGLE","GOGL","DAC","GSL","KEX","TNK","FRO","DHT","INSW","STNG"],
    "3D프린팅":         ["DDD","SSYS","MKFG","VJET","XMTR","PRLB"],

    # 소재 / 에너지
    "석유가스대형":     ["XOM","CVX","COP","OXY","EOG","PSX","VLO","MPC","HES","DVN","FANG","PR","CTRA","APA"],
    "오일서비스":       ["SLB","HAL","BKR","NOV","CHX","WFRD","TDW","RIG","VAL"],
    "LNG/파이프라인":   ["LNG","ET","EPD","KMI","WMB","OKE","TRGP","MPLX","PAA","DTM","NEXT","GLNG"],
    "금/은광산":        ["NEM","GOLD","AEM","KGC","AU","HMY","GFI","WPM","FNV","RGLD","BTG","EGO","IAG","CDE","HL","AG","PAAS"],
    "구리/산업금속":    ["FCX","SCCO","TECK","RIO","BHP","VALE","AA","CENX","MP","ATI","CRS","HAYN","UEC"],
    "철강":             ["NUE","STLD","CLF","X","RS","CMC","MT","TX","ZEUS"],
    "화학":             ["LIN","APD","SHW","ECL","DD","DOW","LYB","PPG","EMN","CE","FMC","IFF","ASH","OLN","WLK"],
    "목재/건자재":      ["WY","PCH","RYN","LPX","BCC","UFPI","MLM","VMC","EXP","SUM","CX","JHX"],
    "농업/식품원재료":  ["ADM","BG","CTVA","MOS","CF","NTR","DAR","LW","INGR","ANDE"],

    # 부동산 리츠
    "데이터센터리츠":   ["EQIX","DLR","IRM"],
    "통신타워리츠":     ["AMT","CCI","SBAC","UNIT"],
    "산업/물류리츠":    ["PLD","EXR","PSA","CUBE","STAG","FR","EGP","TRNO","REXR"],
    "리테일리츠":       ["SPG","O","KIM","REG","FRT","BRX","NNN","ADC","MAC"],
    "주거리츠":         ["AVB","EQR","MAA","ESS","UDR","CPT","INVH","AMH","ELS","SUI"],
    "헬스케어리츠":     ["WELL","VTR","OHI","DOC","CTRE","SBRA","NHI"],
    "오피스/호텔리츠":  ["BXP","VNO","SLG","HST","RHP","PK","APLE","DRH"],

    # 통신 / 기타
    "통신사":           ["T","VZ","TMUS","LUMN","CHTR","CABO","FYBR","IRDM"],
    "인력/컨설팅":      ["ACN","ADP","PAYX","PAYC","PCTY","RHI","MAN","KFY","CBZ","TNET"],
    "교육":             ["CHGG","COUR","UDMY","LRN","ATGE","LOPE","STRA","PRDO"],
    "대마":             ["TLRY","CGC","CRON","ACB","SNDL","GRWG"],
}

# 테마 대분류 (보고서 섹션 순서)
THEME_GROUPS = {
    "반도체": ["DRAM/메모리","CPU","GPU/AI가속기","파운드리","반도체장비",
               "EDA/반도체IP","아날로그/전력반도체","반도체소재"],
    "AI/소프트웨어": ["AI인프라/데이터","클라우드","사이버보안","양자컴퓨팅","엔터프라이즈SW"],
    "하드웨어/네트워킹": ["서버/데이터센터HW","광통신","네트워크장비"],
    "전력/에너지전환": ["원자력/우라늄","전력장비/그리드","태양광","풍력","수소/연료전지","유틸리티"],
    "전기차/모빌리티": ["전기차","자율주행/라이다","전통자동차","배터리/리튬","EV충전"],
    "바이오/헬스케어": ["GLP-1/비만치료","대형제약","바이오테크","의료기기","의료보험/서비스","라이프사이언스툴"],
    "금융": ["대형은행","지역은행","결제","핀테크","크립토/마이닝","자산운용/PE","보험","거래소/금융데이터"],
    "소비재/리테일": ["대형리테일","이커머스","음식료","레스토랑","의류/스포츠","화장품/뷰티",
                      "생활용품","담배/주류","여행/항공","반려동물"],
    "미디어/엔터": ["스트리밍/미디어","게임","카지노/베팅","광고/마케팅테크","소셜/데이팅"],
    "산업/방산/우주": ["방산","우주/위성","항공기/부품","기계/중장비","산업자동화/로봇",
                        "건설/엔지니어링","주택건설","철도/운송","물류/택배","해운/탱커","3D프린팅"],
    "소재/에너지": ["석유가스대형","오일서비스","LNG/파이프라인","금/은광산","구리/산업금속",
                    "철강","화학","목재/건자재","농업/식품원재료"],
    "부동산리츠": ["데이터센터리츠","통신타워리츠","산업/물류리츠","리테일리츠",
                   "주거리츠","헬스케어리츠","오피스/호텔리츠"],
    "통신/기타": ["통신사","인력/컨설팅","교육","대마"],
}

# 테마 종목 이름 (NAMES에 없는 것들)
THEME_NAMES = {
    "MU":"Micron","SNDK":"SanDisk","STX":"Seagate","WDC":"Western Digital","NVMI":"Nova",
    "TSM":"TSMC","GFS":"GlobalFoundries","UMC":"UMC","ASX":"ASE Tech","AMKR":"Amkor",
    "ASML":"ASML","TER":"Teradyne","ONTO":"Onto Innovation","ACMR":"ACM Research",
    "UCTT":"Ultra Clean","AEIS":"Advanced Energy","CAMT":"Camtek","VECO":"Veeco","AMBA":"Ambarella",
    "LSCC":"Lattice","RMBS":"Rambus","CEVA":"CEVA","MPWR":"Monolithic Power","WOLF":"Wolfspeed",
    "STM":"STMicro","SLAB":"Silicon Labs","SITM":"SiTime","POWI":"Power Integrations","DIOD":"Diodes",
    "ENTG":"Entegris","MKSI":"MKS Instruments","IPGP":"IPG Photonics","COHU":"Cohu",
    "FORM":"FormFactor","AXT":"AXT","ALAB":"Astera Labs","CRDO":"Credo",
    "MDB":"MongoDB","CFLT":"Confluent","AI":"C3.ai","BBAI":"BigBear.ai","SOUN":"SoundHound","TEM":"Tempus AI",
    "S":"SentinelOne","OKTA":"Okta","CYBR":"CyberArk","QLYS":"Qualys","TENB":"Tenable",
    "RPD":"Rapid7","VRNS":"Varonis","NET":"Cloudflare","ZS":"Zscaler",
    "IONQ":"IonQ","RGTI":"Rigetti","QBTS":"D-Wave","QUBT":"Quantum Computing","ARQQ":"Arqit",
    "HUBS":"HubSpot","ZM":"Zoom","DOCU":"DocuSign","TWLO":"Twilio","PATH":"UiPath",
    "MNDY":"Monday.com","GTLB":"GitLab","BILL":"Bill.com","WDAY":"Workday","TEAM":"Atlassian",
    "HPE":"HP Enterprise","ANET":"Arista","PSTG":"Pure Storage","NTAP":"NetApp","VRT":"Vertiv",
    "CIEN":"Ciena","LITE":"Lumentum","COHR":"Coherent","AAOI":"Applied Optoelectronics",
    "FN":"Fabrinet","POET":"POET Tech","JNPR":"Juniper","EXTR":"Extreme Networks",
    "NTGR":"NETGEAR","CALX":"Calix","HLIT":"Harmonic",
    "CEG":"Constellation Energy","VST":"Vistra","SMR":"NuScale","OKLO":"Oklo","LEU":"Centrus",
    "CCJ":"Cameco","NNE":"Nano Nuclear","BWXT":"BWX Tech","UEC":"Uranium Energy",
    "DNN":"Denison Mines","UUUU":"Energy Fuels","ASPI":"ASP Isotopes",
    "ETN":"Eaton","PWR":"Quanta Services","GEV":"GE Vernova","EMR":"Emerson","HUBB":"Hubbell",
    "NVT":"nVent","AZZ":"AZZ","POWL":"Powell Industries","GNRC":"Generac","ATKR":"Atkore",
    "FSLR":"First Solar","ENPH":"Enphase","SEDG":"SolarEdge","RUN":"Sunrun","NXT":"Nextracker",
    "ARRY":"Array Tech","SHLS":"Shoals","CSIQ":"Canadian Solar","JKS":"JinkoSolar",
    "MAXN":"Maxeon","SPWR":"SunPower","TPIC":"TPI Composites","AMSC":"American Superconductor",
    "PLUG":"Plug Power","BE":"Bloom Energy","BLDP":"Ballard Power","FCEL":"FuelCell Energy",
    "AEP":"American Electric","EXC":"Exelon","XEL":"Xcel Energy","SRE":"Sempra","PCG":"PG&E",
    "ED":"Con Edison","WEC":"WEC Energy","ES":"Eversource",
    "RIVN":"Rivian","LCID":"Lucid","NIO":"NIO","XPEV":"XPeng","LI":"Li Auto","ZK":"Zeekr","VFS":"VinFast",
    "MBLY":"Mobileye","LAZR":"Luminar","OUST":"Ouster","INVZ":"Innoviz","AUR":"Aurora",
    "PONY":"Pony.ai","GRAB":"Grab","LYFT":"Lyft",
    "GM":"GM","F":"Ford","STLA":"Stellantis","TM":"Toyota","HMC":"Honda","RACE":"Ferrari",
    "ALB":"Albemarle","SQM":"SQM","PLL":"Piedmont Lithium","LAC":"Lithium Americas",
    "QS":"QuantumScape","ENVX":"Enovix","FREY":"FREYR","SLDP":"Solid Power","AMPX":"Amprius",
    "MP":"MP Materials","CHPT":"ChargePoint","BLNK":"Blink Charging","EVGO":"EVgo","WBX":"Wallbox",
    "NVO":"Novo Nordisk","VKTX":"Viking Therapeutics","ALT":"Altimmune","TERN":"Terns Pharma",
    "GPCR":"Structure Therapeutics","ZEAL":"Zealand Pharma",
    "AZN":"AstraZeneca","GSK":"GSK","SNY":"Sanofi","NVS":"Novartis","TAK":"Takeda",
    "BIIB":"Biogen","BNTX":"BioNTech","ALNY":"Alnylam","INCY":"Incyte","EXAS":"Exact Sciences",
    "NBIX":"Neurocrine","SRPT":"Sarepta","RARE":"Ultragenyx","IONS":"Ionis","BMRN":"BioMarin",
    "MDT":"Medtronic","EW":"Edwards Lifesciences","ZBH":"Zimmer Biomet","PODD":"Insulet",
    "TNDM":"Tandem Diabetes","GMED":"Globus Medical","NVCR":"NovoCure",
    "ELV":"Elevance","CVS":"CVS Health","HUM":"Humana","MCK":"McKesson","COR":"Cencora",
    "CAH":"Cardinal Health","HCA":"HCA Healthcare","THC":"Tenet Health","UHS":"Universal Health",
    "A":"Agilent","WAT":"Waters","MTD":"Mettler-Toledo","RVTY":"Revvity","ILMN":"Illumina",
    "PACB":"PacBio","TXG":"10x Genomics","QGEN":"Qiagen","BRKR":"Bruker",
    "USB":"US Bancorp","PNC":"PNC","TFC":"Truist","MTB":"M&T Bank","FITB":"Fifth Third",
    "RF":"Regions","KEY":"KeyCorp","CFG":"Citizens","HBAN":"Huntington","ZION":"Zions",
    "CMA":"Comerica","WAL":"Western Alliance",
    "PYPL":"PayPal","FI":"Fiserv","GPN":"Global Payments","FOUR":"Shift4","TOST":"Toast",
    "XYZ":"Block","WEX":"WEX","SOFI":"SoFi","AFRM":"Affirm","UPST":"Upstart","LC":"LendingClub",
    "HOOD":"Robinhood","NU":"Nu Holdings","DAVE":"Dave","PGY":"Pagaya","OPFI":"OppFi",
    "MSTR":"MicroStrategy","MARA":"MARA Holdings","RIOT":"Riot Platforms","CLSK":"CleanSpark",
    "HUT":"Hut 8","CIFR":"Cipher Mining","WULF":"TeraWulf","BITF":"Bitfarms","HIVE":"HIVE Digital",
    "BTBT":"Bit Digital","GLXY":"Galaxy Digital","CORZ":"Core Scientific","IREN":"IREN","BMNR":"Bitmine",
    "BX":"Blackstone","KKR":"KKR","APO":"Apollo","ARES":"Ares Management","TROW":"T. Rowe Price",
    "BEN":"Franklin Resources","IBKR":"Interactive Brokers","OWL":"Blue Owl","TPG":"TPG",
    "PGR":"Progressive","ALL":"Allstate","TRV":"Travelers","CB":"Chubb","AIG":"AIG",
    "MET":"MetLife","PRU":"Prudential","HIG":"Hartford","AFL":"Aflac","CINF":"Cincinnati Financial",
    "EG":"Everest Group","NDAQ":"Nasdaq","CBOE":"Cboe","FDS":"FactSet","MORN":"Morningstar",
    "TW":"Tradeweb","VIRT":"Virtu Financial",
    "TGT":"Target","DG":"Dollar General","DLTR":"Dollar Tree","BJ":"BJ's Wholesale","KR":"Kroger",
    "ROST":"Ross Stores","TJX":"TJX","BURL":"Burlington","FIVE":"Five Below","OLLI":"Ollie's",
    "ETSY":"Etsy","EBAY":"eBay","W":"Wayfair","CHWY":"Chewy","CVNA":"Carvana",
    "MELI":"MercadoLibre","SE":"Sea Limited","CPNG":"Coupang","BABA":"Alibaba","PDD":"PDD",
    "JD":"JD.com","GLBE":"Global-E",
    "MDLZ":"Mondelez","GIS":"General Mills","HSY":"Hershey","KHC":"Kraft Heinz","CAG":"Conagra",
    "CPB":"Campbell's","SJM":"Smucker","MNST":"Monster Beverage","CELH":"Celsius",
    "KDP":"Keurig Dr Pepper","K":"Kellanova","TSN":"Tyson Foods","HRL":"Hormel",
    "CMG":"Chipotle","YUM":"Yum Brands","QSR":"Restaurant Brands","DPZ":"Domino's",
    "WING":"Wingstop","SHAK":"Shake Shack","TXRH":"Texas Roadhouse","DRI":"Darden","CAVA":"CAVA",
    "EAT":"Brinker",
    "LULU":"Lululemon","DECK":"Deckers","ONON":"On Holding","SKX":"Skechers","VFC":"VF Corp",
    "RL":"Ralph Lauren","PVH":"PVH","ANF":"Abercrombie","UAA":"Under Armour","CROX":"Crocs",
    "BIRK":"Birkenstock","GAP":"Gap",
    "EL":"Estee Lauder","ULTA":"Ulta Beauty","COTY":"Coty","ELF":"e.l.f. Beauty","IPAR":"Interparfums",
    "CL":"Colgate","KMB":"Kimberly-Clark","CHD":"Church & Dwight","CLX":"Clorox",
    "EPC":"Edgewell","REYN":"Reynolds",
    "PM":"Philip Morris","MO":"Altria","BTI":"British American Tobacco","STZ":"Constellation Brands",
    "DEO":"Diageo","TAP":"Molson Coors","SAM":"Boston Beer","BF-B":"Brown-Forman",
    "DAL":"Delta","UAL":"United Airlines","AAL":"American Airlines","LUV":"Southwest",
    "ALK":"Alaska Air","BKNG":"Booking","EXPE":"Expedia","MAR":"Marriott","HLT":"Hilton",
    "H":"Hyatt","RCL":"Royal Caribbean","CCL":"Carnival","NCLH":"Norwegian Cruise","TRIP":"TripAdvisor",
    "FRPT":"Freshpet","ELAN":"Elanco","TRUP":"Trupanion","WOOF":"Petco","IDXX":"IDEXX",
    "WBD":"Warner Bros Discovery","PARA":"Paramount","ROKU":"Roku","SPOT":"Spotify",
    "FUBO":"fuboTV","LYV":"Live Nation",
    "EA":"Electronic Arts","TTWO":"Take-Two","RBLX":"Roblox","U":"Unity","PLTK":"Playtika",
    "APP":"AppLovin","GRVY":"Gravity","SKLZ":"Skillz",
    "DKNG":"DraftKings","PENN":"PENN Entertainment","CZR":"Caesars","MGM":"MGM Resorts",
    "LVS":"Las Vegas Sands","WYNN":"Wynn Resorts","BYD":"Boyd Gaming","CHDN":"Churchill Downs",
    "FLUT":"Flutter","RSI":"Rush Street",
    "TTD":"The Trade Desk","PINS":"Pinterest","SNAP":"Snap","RDDT":"Reddit","OMC":"Omnicom",
    "IPG":"Interpublic","MGNI":"Magnite","CRTO":"Criteo","DV":"DoubleVerify","ZETA":"Zeta Global",
    "IAS":"Integral Ad Science","MTCH":"Match Group","BMBL":"Bumble","NXST":"Nexstar",
    "GD":"General Dynamics","LHX":"L3Harris","HII":"Huntington Ingalls","TXT":"Textron",
    "HWM":"Howmet","TDG":"TransDigm","AXON":"Axon","KTOS":"Kratos","AVAV":"AeroVironment",
    "LDOS":"Leidos","BAH":"Booz Allen","CACI":"CACI","SAIC":"SAIC","RCAT":"Red Cat",
    "RKLB":"Rocket Lab","LUNR":"Intuitive Machines","ASTS":"AST SpaceMobile","PL":"Planet Labs",
    "RDW":"Redwire","IRDM":"Iridium","VSAT":"Viasat","GSAT":"Globalstar","SPCE":"Virgin Galactic",
    "MNTS":"Momentus","ERJ":"Embraer","SPR":"Spirit AeroSystems","HEI":"HEICO",
    "CW":"Curtiss-Wright","MOG-A":"Moog",
    "CMI":"Cummins","PCAR":"PACCAR","AGCO":"AGCO","TEX":"Terex","OSK":"Oshkosh",
    "URI":"United Rentals","HRI":"Herc Holdings","ALG":"Alamo Group","MTW":"Manitowoc",
    "ROK":"Rockwell Automation","ABB":"ABB","SYM":"Symbotic","NDSN":"Nordson","ZBRA":"Zebra Tech",
    "CGNX":"Cognex","MIDD":"Middleby","AME":"AMETEK","PH":"Parker Hannifin","DOV":"Dover",
    "ITW":"Illinois Tool Works","IR":"Ingersoll Rand","GGG":"Graco",
    "EME":"EMCOR","MTZ":"MasTec","ACM":"AECOM","J":"Jacobs","FLR":"Fluor","DY":"Dycom",
    "GVA":"Granite Construction","STRL":"Sterling Infrastructure","ROAD":"Construction Partners",
    "IESC":"IES Holdings","PRIM":"Primoris",
    "DHI":"D.R. Horton","LEN":"Lennar","PHM":"PulteGroup","NVR":"NVR","TOL":"Toll Brothers",
    "KBH":"KB Home","TMHC":"Taylor Morrison","MTH":"Meritage Homes","MHO":"M/I Homes",
    "BLDR":"Builders FirstSource","POOL":"Pool Corp","IBP":"Installed Building Products",
    "UNP":"Union Pacific","CSX":"CSX","NSC":"Norfolk Southern","CP":"Canadian Pacific","CNI":"Canadian National",
    "XPO":"XPO","ODFL":"Old Dominion","SAIA":"Saia","CHRW":"C.H. Robinson","EXPD":"Expeditors",
    "GXO":"GXO Logistics","JBHT":"J.B. Hunt","KNX":"Knight-Swift","RXO":"RXO",
    "ZIM":"ZIM Shipping","MATX":"Matson","SBLK":"Star Bulk","GNK":"Genco Shipping",
    "EGLE":"Eagle Bulk","GOGL":"Golden Ocean","DAC":"Danaos","GSL":"Global Ship Lease",
    "KEX":"Kirby","TNK":"Teekay Tankers","FRO":"Frontline","DHT":"DHT Holdings",
    "INSW":"International Seaways","STNG":"Scorpio Tankers",
    "DDD":"3D Systems","SSYS":"Stratasys","MKFG":"Markforged","VJET":"voxeljet",
    "XMTR":"Xometry","PRLB":"Proto Labs",
    "COP":"ConocoPhillips","OXY":"Occidental","EOG":"EOG Resources","PSX":"Phillips 66",
    "VLO":"Valero","MPC":"Marathon Petroleum","HES":"Hess","DVN":"Devon Energy",
    "FANG":"Diamondback","PR":"Permian Resources","CTRA":"Coterra","APA":"APA Corp",
    "SLB":"SLB","HAL":"Halliburton","BKR":"Baker Hughes","NOV":"NOV Inc","CHX":"ChampionX",
    "WFRD":"Weatherford","TDW":"Tidewater","RIG":"Transocean","VAL":"Valaris",
    "LNG":"Cheniere Energy","ET":"Energy Transfer","EPD":"Enterprise Products","KMI":"Kinder Morgan",
    "WMB":"Williams","OKE":"ONEOK","TRGP":"Targa Resources","MPLX":"MPLX","PAA":"Plains All American",
    "DTM":"DT Midstream","NEXT":"NextDecade","GLNG":"Golar LNG",
    "NEM":"Newmont","GOLD":"Barrick","AEM":"Agnico Eagle","KGC":"Kinross Gold","AU":"AngloGold",
    "HMY":"Harmony Gold","GFI":"Gold Fields","WPM":"Wheaton Precious","FNV":"Franco-Nevada",
    "RGLD":"Royal Gold","BTG":"B2Gold","EGO":"Eldorado Gold","IAG":"IAMGOLD","CDE":"Coeur Mining",
    "HL":"Hecla Mining","AG":"First Majestic","PAAS":"Pan American Silver",
    "FCX":"Freeport-McMoRan","SCCO":"Southern Copper","TECK":"Teck Resources","RIO":"Rio Tinto",
    "BHP":"BHP","VALE":"Vale","AA":"Alcoa","CENX":"Century Aluminum","ATI":"ATI Inc",
    "CRS":"Carpenter Tech","HAYN":"Haynes International",
    "NUE":"Nucor","STLD":"Steel Dynamics","CLF":"Cleveland-Cliffs","X":"US Steel",
    "RS":"Reliance Steel","CMC":"Commercial Metals","MT":"ArcelorMittal","TX":"Ternium","ZEUS":"Olympic Steel",
    "LIN":"Linde","APD":"Air Products","SHW":"Sherwin-Williams","ECL":"Ecolab","DD":"DuPont",
    "DOW":"Dow","LYB":"LyondellBasell","PPG":"PPG","EMN":"Eastman Chemical","CE":"Celanese",
    "FMC":"FMC Corp","IFF":"IFF","ASH":"Ashland","OLN":"Olin","WLK":"Westlake",
    "WY":"Weyerhaeuser","PCH":"PotlatchDeltic","RYN":"Rayonier","LPX":"Louisiana-Pacific",
    "BCC":"Boise Cascade","UFPI":"UFP Industries","MLM":"Martin Marietta","VMC":"Vulcan Materials",
    "EXP":"Eagle Materials","SUM":"Summit Materials","CX":"Cemex","JHX":"James Hardie",
    "ADM":"Archer-Daniels","BG":"Bunge","CTVA":"Corteva","MOS":"Mosaic","CF":"CF Industries",
    "NTR":"Nutrien","DAR":"Darling Ingredients","LW":"Lamb Weston","INGR":"Ingredion","ANDE":"Andersons",
    "EQIX":"Equinix","DLR":"Digital Realty","IRM":"Iron Mountain","AMT":"American Tower",
    "CCI":"Crown Castle","SBAC":"SBA Communications","UNIT":"Uniti Group",
    "PLD":"Prologis","EXR":"Extra Space","PSA":"Public Storage","CUBE":"CubeSmart",
    "STAG":"STAG Industrial","FR":"First Industrial","EGP":"EastGroup","TRNO":"Terreno",
    "REXR":"Rexford Industrial","SPG":"Simon Property","O":"Realty Income","KIM":"Kimco",
    "REG":"Regency Centers","FRT":"Federal Realty","BRX":"Brixmor","NNN":"NNN REIT",
    "ADC":"Agree Realty","MAC":"Macerich",
    "AVB":"AvalonBay","EQR":"Equity Residential","MAA":"Mid-America","ESS":"Essex Property",
    "UDR":"UDR","CPT":"Camden Property","INVH":"Invitation Homes","AMH":"American Homes 4 Rent",
    "ELS":"Equity Lifestyle","SUI":"Sun Communities",
    "WELL":"Welltower","VTR":"Ventas","OHI":"Omega Healthcare","DOC":"Healthpeak",
    "CTRE":"CareTrust","SBRA":"Sabra Health","NHI":"National Health Investors",
    "BXP":"BXP","VNO":"Vornado","SLG":"SL Green","HST":"Host Hotels","RHP":"Ryman Hospitality",
    "PK":"Park Hotels","APLE":"Apple Hospitality","DRH":"DiamondRock",
    "LUMN":"Lumen","CHTR":"Charter Communications","CABO":"Cable One","FYBR":"Frontier Comm",
    "PAYX":"Paychex","PAYC":"Paycom","PCTY":"Paylocity","RHI":"Robert Half","MAN":"ManpowerGroup",
    "KFY":"Korn Ferry","CBZ":"CBIZ","TNET":"TriNet",
    "CHGG":"Chegg","COUR":"Coursera","UDMY":"Udemy","LRN":"Stride","ATGE":"Adtalem",
    "LOPE":"Grand Canyon Education","STRA":"Strategic Education","PRDO":"Perdoceo",
    "TLRY":"Tilray","CGC":"Canopy Growth","CRON":"Cronos","ACB":"Aurora Cannabis",
    "SNDL":"SNDL","GRWG":"GrowGeneration",
    # S&P 대형주 (기존 NAMES 미등록분)
    "ABBV":"AbbVie","ABNB":"Airbnb","ABT":"Abbott","ACN":"Accenture","ADBE":"Adobe",
    "ADI":"Analog Devices","ADP":"ADP","AMAT":"Applied Materials","AMGN":"Amgen",
    "APH":"Amphenol","AXP":"American Express","BA":"Boeing","BAC":"Bank of America",
    "BLK":"BlackRock","BMY":"Bristol Myers","BRK-B":"Berkshire Hathaway","BSX":"Boston Scientific",
    "C":"Citigroup","CAT":"Caterpillar","CDNS":"Cadence","CI":"Cigna","CMCSA":"Comcast",
    "CME":"CME Group","CSCO":"Cisco","CVX":"Chevron","D":"Dominion Energy","DDOG":"Datadog",
    "DE":"Deere","DELL":"Dell","DHR":"Danaher","DIS":"Disney","DUK":"Duke Energy",
    "DXCM":"DexCom","FDX":"FedEx","FTNT":"Fortinet","GILD":"Gilead","GS":"Goldman Sachs",
    "HON":"Honeywell","HYSR":"SunHydrogen","IBM":"IBM","ICE":"ICE","INTC":"Intel",
    "INTU":"Intuit","ISRG":"Intuitive Surgical","JNJ":"Johnson & Johnson","KLAC":"KLA Corp",
    "KO":"Coca-Cola","LMT":"Lockheed Martin","LRCX":"Lam Research","MCD":"McDonald's",
    "MCHP":"Microchip","MCO":"Moody's","MRK":"Merck","MRNA":"Moderna","MRVL":"Marvell",
    "MS":"Morgan Stanley","MSCI":"MSCI","NEE":"NextEra Energy","NEP":"NextEra Partners",
    "NKE":"Nike","NOC":"Northrop Grumman","NXPI":"NXP Semiconductors","ON":"onsemi",
    "PEP":"PepsiCo","PFE":"Pfizer","PG":"Procter & Gamble","QCOM":"Qualcomm",
    "REGN":"Regeneron","RTX":"RTX","SBUX":"Starbucks","SCHW":"Charles Schwab",
    "SHOP":"Shopify","SNOW":"Snowflake","SNPS":"Synopsys","SO":"Southern Company",
    "SPGI":"S&P Global","SYK":"Stryker","T":"AT&T","TMO":"Thermo Fisher","TMUS":"T-Mobile",
    "TXN":"Texas Instruments","UBER":"Uber","UPS":"UPS","VRTX":"Vertex Pharma","VZ":"Verizon",
    "WFC":"Wells Fargo","WMT":"Walmart","XOM":"Exxon Mobil","ZTS":"Zoetis",
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


# ─── 리스크 지표 ───
RISK_TICKERS = {
    "VIX":      "^VIX",       # 공포지수
    "미국10Y":   "^TNX",       # 미국 10년 국채 금리
    "달러인덱스": "DX-Y.NYB",  # 달러 인덱스
    "금":        "GC=F",       # 금 선물
    "원/달러":   "KRW=X",      # 원달러 환율
    "VKOSPI":   "^KS200VIX",  # 한국 변동성지수 (없으면 skip)
}


def scan_risk_indicators(market="ALL"):
    """시장 리스크 지표 + 주요 선물/지수 스캔."""
    results = {}
    tickers_to_scan = {}

    if market in ("US", "ALL"):
        tickers_to_scan.update({
            "VIX":        "^VIX",       # 공포지수
            "미국10Y":     "^TNX",       # 10년 국채 금리
            "달러인덱스":   "DX-Y.NYB",  # 달러 인덱스
            "금":          "GC=F",       # 금 선물
            "S&P500":     "^GSPC",      # S&P 500
            "나스닥":      "^IXIC",      # 나스닥 종합
            "S&P선물":     "ES=F",       # S&P 500 선물
            "나스닥선물":   "NQ=F",       # 나스닥 100 선물
        })
    if market in ("KR", "ALL"):
        tickers_to_scan.update({
            "원/달러":     "KRW=X",      # 원달러 환율
            "코스피":      "^KS11",      # 코스피 지수
            "코스닥":      "^KQ11",      # 코스닥 지수
            "코스피200선물":"KS200.KS",   # 코스피200 선물 (ETF 대용)
        })

    for name, sym in tickers_to_scan.items():
        try:
            t = yf.Ticker(sym)
            hist = t.history(period="5d")
            if hist.empty:
                continue
            current = hist["Close"].iloc[-1]
            prev = hist["Close"].iloc[-2] if len(hist) >= 2 else current
            chg = ((current - prev) / prev * 100) if prev else 0
            # 5일 전 대비 변화도
            first = hist["Close"].iloc[0] if len(hist) >= 2 else current
            chg_5d = ((current - first) / first * 100) if first else 0
            results[name] = dict(value=current, chg=chg, chg_5d=chg_5d)
        except Exception:
            continue

    return results


def format_risk_section(risk_data, market="ALL"):
    """리스크 지표 섹션 텍스트 생성."""
    if not risk_data:
        return ""

    buf = StringIO()

    def w(text=""):
        buf.write(text + "\n")

    w("=" * 70)
    w("  시장 리스크 대시보드")
    w("=" * 70)
    w()

    # 구분해서 출력
    risk_keys = ["VIX", "미국10Y", "달러인덱스", "금", "원/달러"]
    index_keys = ["S&P500", "나스닥", "코스피", "코스닥"]
    futures_keys = ["S&P선물", "나스닥선물", "코스피200선물"]

    def fmt_val(name, val):
        if name == "VIX":
            return f"{val:.2f}"
        if name == "미국10Y":
            return f"{val:.3f}%"
        if name in ("달러인덱스",):
            return f"{val:.2f}"
        if name == "금":
            return f"${val:,.1f}"
        if name == "원/달러":
            return f"{val:,.1f}원"
        if name in ("S&P500", "나스닥"):
            return f"{val:,.1f}"
        if name in ("코스피", "코스닥"):
            return f"{val:,.2f}"
        if "선물" in name:
            return f"{val:,.1f}"
        return f"{val:.2f}"

    def print_group(title, keys):
        items = [(k, risk_data[k]) for k in keys if k in risk_data]
        if not items:
            return
        w(f"  [{title}]")
        for name, d in items:
            val = d["value"]
            chg = d["chg"]
            chg_5d = d["chg_5d"]
            arrow = "▲" if chg > 0 else "▼" if chg < 0 else "─"
            w(f"    {name:<12}  {fmt_val(name, val):>12}  "
              f"{arrow}{abs(chg):>5.2f}% (전일)  |  5일: {chg_5d:+.2f}%")
        w()

    print_group("리스크 지표", risk_keys)
    print_group("주요 지수", index_keys)
    print_group("선물", futures_keys)

    # 리스크 판단
    warnings = []
    vix = risk_data.get("VIX", {})
    if vix and vix.get("value", 0) >= 30:
        warnings.append(f"⚠ VIX {vix['value']:.1f} - 공포 구간! 변동성 극대화 주의")
    elif vix and vix.get("value", 0) >= 25:
        warnings.append(f"⚠ VIX {vix['value']:.1f} - 불안 구간, 포지션 축소 고려")
    elif vix and vix.get("value", 0) <= 15:
        warnings.append(f"  VIX {vix['value']:.1f} - 안정 구간, 시장 낙관적")

    tnx = risk_data.get("미국10Y", {})
    if tnx and tnx.get("chg", 0) > 3:
        warnings.append(f"⚠ 미국10Y 금리 급등 ({tnx['chg']:+.2f}%) - 성장주 하락 압력")
    elif tnx and tnx.get("value", 0) >= 5.0:
        warnings.append(f"⚠ 미국10Y {tnx['value']:.2f}% - 고금리 지속, 밸류에이션 부담")

    krw = risk_data.get("원/달러", {})
    if krw and krw.get("value", 0) >= 1400:
        warnings.append(f"⚠ 원/달러 {krw['value']:,.0f}원 - 원화 약세, 외국인 매도 압력")
    if krw and krw.get("chg", 0) > 1:
        warnings.append(f"⚠ 원/달러 급등 ({krw['chg']:+.2f}%) - 환율 불안")

    gold = risk_data.get("금", {})
    if gold and gold.get("chg_5d", 0) > 5:
        warnings.append(f"⚠ 금 5일간 {gold['chg_5d']:+.1f}% 급등 - 안전자산 선호 강화")

    # 선물/지수 경고
    sp_fut = risk_data.get("S&P선물", {})
    if sp_fut and sp_fut.get("chg", 0) < -1:
        warnings.append(f"⚠ S&P 선물 {sp_fut['chg']:+.2f}% - 미장 하락 출발 가능")
    nq_fut = risk_data.get("나스닥선물", {})
    if nq_fut and nq_fut.get("chg", 0) < -1.5:
        warnings.append(f"⚠ 나스닥 선물 {nq_fut['chg']:+.2f}% - 기술주 약세 신호")

    kospi = risk_data.get("코스피", {})
    if kospi and kospi.get("chg", 0) < -2:
        warnings.append(f"⚠ 코스피 {kospi['chg']:+.2f}% 급락")
    kosdaq = risk_data.get("코스닥", {})
    if kosdaq and kosdaq.get("chg", 0) < -2.5:
        warnings.append(f"⚠ 코스닥 {kosdaq['chg']:+.2f}% 급락")

    if warnings:
        w("  [리스크 경고]")
        for warn in warnings:
            w(f"  {warn}")
    else:
        w("  [리스크 양호] 주요 지표 안정권")
    w()

    # 종합 신호등
    danger_count = sum(1 for warn in warnings if warn.startswith("⚠"))
    if danger_count >= 3:
        w("  종합 판단: 🔴 위험 - 보수적 매매 권장, 현금 비중 확대")
    elif danger_count >= 1:
        w("  종합 판단: 🟡 주의 - 선별적 매매, 리스크 관리 강화")
    else:
        w("  종합 판단: 🟢 양호 - 정상 매매 가능")
    w()

    return buf.getvalue()


def compute_fear_greed(vix_series):
    """VIX 기반 Daily Sentiment Index (0=극단적 공포, 100=극단적 탐욕)."""
    vix_min, vix_max = 10, 40
    fg = 100 - (vix_series.clip(vix_min, vix_max) - vix_min) / (vix_max - vix_min) * 100
    return fg


def generate_risk_chart(market="US", period="3y", output_path=None):
    """지수 + Daily Sentiment 2단 패널 차트 (Jake Bernstein 스타일)."""
    if market == "KR":
        index_sym, index_name = "^KS11", "KOSPI"
    else:
        index_sym, index_name = "^IXIC", "NASDAQ"

    # 데이터 다운로드
    idx_data = yf.download(index_sym, period=period, interval="1d", progress=False)
    vix_data = yf.download("^VIX", period=period, interval="1d", progress=False)

    if idx_data.empty or vix_data.empty:
        return None

    # MultiIndex 처리
    if isinstance(idx_data.columns, pd.MultiIndex):
        idx_close = idx_data[("Close", idx_data.columns.get_level_values(1)[0])].dropna()
    else:
        idx_close = idx_data["Close"].dropna()

    if isinstance(vix_data.columns, pd.MultiIndex):
        vix_close = vix_data[("Close", vix_data.columns.get_level_values(1)[0])].dropna()
    else:
        vix_close = vix_data["Close"].dropna()

    # 공통 날짜 정렬
    common_dates = idx_close.index.intersection(vix_close.index)
    idx_close = idx_close.loc[common_dates]
    vix_close = vix_close.loc[common_dates]

    # 센티먼트 계산
    sentiment = compute_fear_greed(vix_close)
    sent_values = sentiment.values.flatten() if hasattr(sentiment.values, 'flatten') else sentiment.values
    idx_values = idx_close.values.flatten() if hasattr(idx_close.values, 'flatten') else idx_close.values
    dates = idx_close.index

    # 바닥 시그널 감지 (센티먼트 < 20 구간의 로컬 최저점)
    BOTTOM_THRESHOLD = 20
    bottom_dates = []
    bottom_sent = []
    bottom_idx = []
    in_bottom = False
    local_min_val = 999
    local_min_i = 0

    for i in range(len(sent_values)):
        if sent_values[i] < BOTTOM_THRESHOLD:
            if not in_bottom:
                in_bottom = True
                local_min_val = sent_values[i]
                local_min_i = i
            elif sent_values[i] < local_min_val:
                local_min_val = sent_values[i]
                local_min_i = i
        else:
            if in_bottom:
                bottom_dates.append(dates[local_min_i])
                bottom_sent.append(sent_values[local_min_i])
                bottom_idx.append(idx_values[local_min_i])
                in_bottom = False
                local_min_val = 999
    # 현재도 바닥 구간이면 추가
    if in_bottom:
        bottom_dates.append(dates[local_min_i])
        bottom_sent.append(sent_values[local_min_i])
        bottom_idx.append(idx_values[local_min_i])

    # ─── 2단 패널 차트 ───
    fig, (ax_top, ax_bot) = plt.subplots(2, 1, figsize=(14, 9),
                                          gridspec_kw={"height_ratios": [1.2, 1],
                                                       "hspace": 0.08})
    fig.patch.set_facecolor("#0d1117")

    now = datetime.now()
    last_sent = sent_values[-1]

    # ── 상단: 지수 ──
    ax_top.set_facecolor("#0d1117")
    ax_top.plot(dates, idx_values, color="#4a9eff", linewidth=1.5, zorder=2)
    ax_top.text(0.02, 0.92, index_name, transform=ax_top.transAxes,
                fontsize=22, fontweight="bold", color="#4a9eff", va="top")

    # 바닥 시그널 마킹 (지수 위)
    if bottom_dates:
        ax_top.scatter(bottom_dates, bottom_idx, s=200, facecolors="none",
                       edgecolors="#ff8c00", linewidth=2.5, zorder=3)

    # 현재값 마커
    ax_top.scatter([dates[-1]], [idx_values[-1]], color="#ff8c00", s=180,
                   facecolors="none", edgecolors="#ff8c00", linewidth=2.5, zorder=3)

    ax_top.set_xlim(dates[0], dates[-1])
    ax_top.tick_params(axis="y", labelcolor="#888888", labelsize=10)
    ax_top.tick_params(axis="x", labelbottom=False)
    ax_top.spines["top"].set_visible(False)
    ax_top.spines["right"].set_visible(False)
    ax_top.spines["bottom"].set_color("#333333")
    ax_top.spines["left"].set_color("#333333")
    ax_top.grid(True, alpha=0.15, color="#ffffff", linestyle="-")

    # ── 하단: Daily Sentiment Index ──
    ax_bot.set_facecolor("#0d1117")
    ax_bot.fill_between(dates, sent_values, 0, color="#2aa198", alpha=0.4)
    ax_bot.plot(dates, sent_values, color="#2aa198", linewidth=1.2, zorder=2)

    ax_bot.text(0.02, 0.92, "Daily Sentiment Index", transform=ax_bot.transAxes,
                fontsize=16, fontweight="bold", color="#2aa198", va="top")

    # 20 라인 (바닥 기준선)
    ax_bot.axhline(y=BOTTOM_THRESHOLD, color="#ff4444", linewidth=1.5,
                   linestyle="-", alpha=0.8, zorder=1)
    ax_bot.text(dates[0], BOTTOM_THRESHOLD + 2, f" All prior <{BOTTOM_THRESHOLD} = bottoms",
                color="#ff4444", fontsize=9, fontweight="bold", va="bottom")

    # 바닥 시그널 마킹 (센티먼트 위)
    if bottom_dates:
        ax_bot.scatter(bottom_dates, bottom_sent, s=200, facecolors="none",
                       edgecolors="#ff8c00", linewidth=2.5, zorder=3)

    # 현재값 마커 + 숫자
    ax_bot.scatter([dates[-1]], [last_sent], color="#ff8c00", s=180,
                   facecolors="none", edgecolors="#ff8c00", linewidth=2.5, zorder=3)
    ax_bot.annotate(f"{last_sent:.0f}", xy=(dates[-1], last_sent),
                    xytext=(12, 0), textcoords="offset points",
                    color="#ff8c00", fontsize=14, fontweight="bold", va="center")

    ax_bot.set_ylim(0, 100)
    ax_bot.set_xlim(dates[0], dates[-1])
    ax_bot.tick_params(axis="y", labelcolor="#888888", labelsize=10)
    ax_bot.tick_params(axis="x", labelcolor="#888888", labelsize=10, rotation=0)
    ax_bot.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    ax_bot.xaxis.set_major_locator(mdates.MonthLocator(interval=4))
    ax_bot.spines["top"].set_color("#333333")
    ax_bot.spines["right"].set_visible(False)
    ax_bot.spines["bottom"].set_color("#333333")
    ax_bot.spines["left"].set_color("#333333")
    ax_bot.grid(True, alpha=0.15, color="#ffffff", linestyle="-")

    # 타이틀
    fig.suptitle(f"{index_name} Sentiment {last_sent:.0f}  {now.strftime('%m/%d')}",
                 fontsize=14, fontweight="bold", color="#cccccc", y=0.98)

    fig.subplots_adjust(left=0.08, right=0.95, top=0.94, bottom=0.08)

    # 저장
    if not output_path:
        output_path = f"risk_chart_{market}_{now.strftime('%Y%m%d_%H%M')}.png"
    fig.savefig(output_path, dpi=150, facecolor=fig.get_facecolor(),
                edgecolor="none", bbox_inches="tight")
    plt.close(fig)
    print(f"  차트 저장: {output_path}", file=sys.stderr)
    return output_path


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

            # Forward PER
            try:
                info = t.info
                fwd_pe = info.get("forwardPE", None)
            except Exception:
                fwd_pe = None

            rows.append(dict(
                sym=sym, price=price, chg=chg, h52=h52, l52=l52,
                pct_h=pct_h, mc=mc, vol=vol, avg_vol=avg_vol,
                vol_r=vol_r, tv=tv, avg_tv=avg_tv, tv_ratio=tv_ratio, mkt=mkt,
                fwd_pe=fwd_pe,
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
    if sym in THEME_NAMES:
        return THEME_NAMES[sym]
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


def generate_report(all_data, pct_h_min=90, tv_top_pct=30, market="ALL"):
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
                fwd_pe_str = f"{r['fwd_pe']:.1f}" if pd.notna(r.get('fwd_pe')) and r.get('fwd_pe') else "-"
                w(f"      거래량 비율: {r['vol_r']:.1f}x  |  시가총액: {fmt_cap(r['mc'], mkt)}  |  Fwd P/E: {fwd_pe_str}")

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
            pe_note = f"  (Fwd P/E: {r['fwd_pe']:.1f})" if pd.notna(r.get('fwd_pe')) and r.get('fwd_pe') else ""
            w(f"    - {name}: 신고가 근접({r['pct_h']:.1f}%) + "
              f"거래대금 활발({r['tv_ratio']:.1f}x){pe_note} -> 추세 추종 매매 유리")
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


def scan_sector(symbols, mkt, sector_map):
    """섹터별 당일 등락률 스캔."""
    print(f"  [{mkt}] 섹터 성과 스캔 중...", file=sys.stderr)
    rows = []
    for sym in symbols:
        try:
            t = yf.Ticker(sym)
            fi = t.fast_info
            price = getattr(fi, "last_price", 0) or 0
            prev = getattr(fi, "previous_close", 0) or price
            chg = ((price - prev) / prev * 100) if prev else 0
            mc = getattr(fi, "market_cap", 0) or 0
            vol = getattr(fi, "last_volume", 0) or 0
            tv = price * vol
            # 섹터 찾기
            sector = "기타"
            for s, syms_list in sector_map.items():
                if sym in syms_list:
                    sector = s
                    break
            rows.append(dict(sym=sym, price=price, chg=chg, mc=mc, tv=tv, sector=sector, mkt=mkt))
        except Exception:
            continue
    return pd.DataFrame(rows)


def generate_sector_report(all_data, mkt_label, market="ALL"):
    """섹터별 성과 보고서 생성."""
    buf = StringIO()
    now = datetime.now()

    def w(text=""):
        buf.write(text + "\n")

    w("=" * 70)
    w(f"  {mkt_label} 섹터별 성과 보고서")
    w(f"  {now.strftime('%Y년 %m월 %d일 %H:%M')} 기준 (장마감 후)")
    w("=" * 70)
    w()

    # 리스크 대시보드
    try:
        risk = scan_risk_indicators(market)
        risk_section = format_risk_section(risk, market)
        if risk_section:
            buf.write(risk_section)
    except Exception as e:
        w(f"  [리스크 지표 로딩 실패: {e}]")
        w()

    if all_data.empty:
        w("  데이터 없음.")
        return buf.getvalue()

    # 섹터별 집계: 시총 가중 평균 등락률 + 단순 평균
    sector_stats = []
    for sector in all_data["sector"].unique():
        sdf = all_data[all_data["sector"] == sector]
        simple_avg = sdf["chg"].mean()
        total_mc = sdf["mc"].sum()
        # 시총 가중 평균
        if total_mc > 0:
            weighted_avg = (sdf["chg"] * sdf["mc"]).sum() / total_mc
        else:
            weighted_avg = simple_avg
        total_tv = sdf["tv"].sum()
        n = len(sdf)
        top_stock = sdf.loc[sdf["chg"].idxmax()]
        worst_stock = sdf.loc[sdf["chg"].idxmin()]
        sector_stats.append(dict(
            sector=sector, weighted_avg=weighted_avg, simple_avg=simple_avg,
            total_tv=total_tv, n=n, total_mc=total_mc,
            top_sym=top_stock["sym"], top_chg=top_stock["chg"],
            worst_sym=worst_stock["sym"], worst_chg=worst_stock["chg"],
            up_pct=len(sdf[sdf["chg"] > 0]) / n * 100 if n else 0,
        ))

    sdf = pd.DataFrame(sector_stats).sort_values("weighted_avg", ascending=False)
    mkt = all_data["mkt"].iloc[0]

    # ─── 섹터 순위표 ───
    w("-" * 70)
    w(f"  {'순위':>4}  {'섹터':<12}  {'등락률':>8}  {'거래대금':>12}  {'종목수':>4}")
    w("-" * 70)

    for rank, (_, r) in enumerate(sdf.iterrows(), 1):
        arrow = "▲" if r["weighted_avg"] > 0 else "▼" if r["weighted_avg"] < 0 else "─"
        w(f"  {rank:>4}  {r['sector']:<12}  {arrow}{abs(r['weighted_avg']):>6.2f}%"
          f"  {fmt_tv(r['total_tv'], mkt):>12}  {r['n']:>4}개")

    w()

    # ─── 섹터 액션 감지 ───
    ACTION_THRESHOLD = 1.5  # 섹터 평균 등락률 ±1.5% 이상이면 액션
    CONSENSUS_THRESHOLD = 80  # 섹터 내 80% 이상 같은 방향이면 강한 합의

    hot_sectors = sdf[sdf["weighted_avg"] >= ACTION_THRESHOLD]
    cold_sectors = sdf[sdf["weighted_avg"] <= -ACTION_THRESHOLD]
    consensus_up = sdf[sdf["up_pct"] >= CONSENSUS_THRESHOLD]
    consensus_dn = sdf[sdf["up_pct"] <= (100 - CONSENSUS_THRESHOLD)]

    has_action = not hot_sectors.empty or not cold_sectors.empty

    if has_action:
        w("=" * 70)
        w("  섹터 액션 감지")
        w("=" * 70)
        w()

        if not hot_sectors.empty:
            w("  [급등 섹터]")
            for _, r in hot_sectors.iterrows():
                top_name = get_name(r["top_sym"])
                consensus = ""
                if r["up_pct"] >= CONSENSUS_THRESHOLD:
                    consensus = f"  (종목 {r['up_pct']:.0f}% 동반 상승!)"
                w(f"    ▲ {r['sector']} +{r['weighted_avg']:.2f}%{consensus}")
                w(f"      주도주: {top_name} ({r['top_chg']:+.2f}%)")
                # 해당 섹터 종목들
                sec_stocks = all_data[all_data["sector"] == r["sector"]].sort_values("chg", ascending=False)
                syms_str = ", ".join(
                    f"{get_name(st['sym'])}({st['chg']:+.1f}%)"
                    for _, st in sec_stocks.head(5).iterrows()
                )
                w(f"      {syms_str}")
            w()

        if not cold_sectors.empty:
            w("  [급락 섹터]")
            for _, r in cold_sectors.iterrows():
                worst_name = get_name(r["worst_sym"])
                consensus = ""
                if r["up_pct"] <= (100 - CONSENSUS_THRESHOLD):
                    consensus = f"  (종목 {100 - r['up_pct']:.0f}% 동반 하락!)"
                w(f"    ▼ {r['sector']} {r['weighted_avg']:.2f}%{consensus}")
                w(f"      최약: {worst_name} ({r['worst_chg']:+.2f}%)")
                sec_stocks = all_data[all_data["sector"] == r["sector"]].sort_values("chg")
                syms_str = ", ".join(
                    f"{get_name(st['sym'])}({st['chg']:+.1f}%)"
                    for _, st in sec_stocks.head(5).iterrows()
                )
                w(f"      {syms_str}")
            w()

        # 액션 코멘트
        if not hot_sectors.empty and cold_sectors.empty:
            w("  -> 섹터 쏠림 상승: 특정 테마 강세장")
        elif hot_sectors.empty and not cold_sectors.empty:
            w("  -> 섹터 동반 하락: 리스크오프 장세 주의")
        elif not hot_sectors.empty and not cold_sectors.empty:
            w("  -> 섹터 로테이션 진행 중: 순환매 장세")
        w()
    else:
        w("-" * 70)
        w("  [섹터 액션 없음] 뚜렷한 섹터 쏠림 없이 혼조세")
        w("-" * 70)
        w()

    # ─── 강세 섹터 상세 ───
    strong = sdf[sdf["weighted_avg"] > 0]
    weak = sdf[sdf["weighted_avg"] < 0]

    if not strong.empty:
        w("=" * 70)
        w("  강세 섹터 상세")
        w("=" * 70)
        w()
        for _, r in strong.iterrows():
            w(f"  [{r['sector']}] +{r['weighted_avg']:.2f}%")
            top_name = get_name(r["top_sym"])
            w(f"    최고: {top_name} ({r['top_chg']:+.2f}%)")
            # 해당 섹터 전 종목
            sec_stocks = all_data[all_data["sector"] == r["sector"]].sort_values("chg", ascending=False)
            for _, st in sec_stocks.iterrows():
                name = get_name(st["sym"])
                ticker = st["sym"].replace(".KS", "").replace(".KQ", "")
                bar = "+" * min(int(abs(st["chg"])), 20) if st["chg"] > 0 else "-" * min(int(abs(st["chg"])), 20)
                w(f"      {name:<16} {st['chg']:+6.2f}%  {bar}")
            w()

    if not weak.empty:
        w("=" * 70)
        w("  약세 섹터 상세")
        w("=" * 70)
        w()
        for _, r in weak.iterrows():
            w(f"  [{r['sector']}] {r['weighted_avg']:.2f}%")
            worst_name = get_name(r["worst_sym"])
            w(f"    최저: {worst_name} ({r['worst_chg']:+.2f}%)")
            sec_stocks = all_data[all_data["sector"] == r["sector"]].sort_values("chg", ascending=False)
            for _, st in sec_stocks.iterrows():
                name = get_name(st["sym"])
                bar = "+" * min(int(abs(st["chg"])), 20) if st["chg"] > 0 else "-" * min(int(abs(st["chg"])), 20)
                w(f"      {name:<16} {st['chg']:+6.2f}%  {bar}")
            w()

    # ─── 요약 코멘트 ───
    w("=" * 70)
    w("  오늘의 시장 요약")
    w("=" * 70)
    w()

    mkt_avg = all_data["chg"].mean()
    up_cnt = len(all_data[all_data["chg"] > 0])
    dn_cnt = len(all_data[all_data["chg"] < 0])
    total = len(all_data)

    w(f"  전체 평균 등락률: {mkt_avg:+.2f}%")
    w(f"  상승/하락: {up_cnt}개 상승 vs {dn_cnt}개 하락 (총 {total}개)")
    w()

    if not strong.empty:
        top_sector = strong.iloc[0]
        w(f"  오늘의 최강 섹터: {top_sector['sector']} (+{top_sector['weighted_avg']:.2f}%)")
    if not weak.empty:
        bot_sector = weak.iloc[-1]
        w(f"  오늘의 최약 섹터: {bot_sector['sector']} ({bot_sector['weighted_avg']:.2f}%)")
    w()

    # 섹터 로테이션 힌트
    if len(strong) >= 2:
        top_names = ", ".join(strong["sector"].head(3).tolist())
        w(f"  자금 유입 섹터: {top_names}")
    if len(weak) >= 2:
        bot_names = ", ".join(weak["sector"].tail(3).tolist())
        w(f"  자금 이탈 섹터: {bot_names}")
    w()

    w("-" * 70)
    w("  주의: 본 보고서는 데이터 기반 자동 생성이며 투자 권유가 아닙니다.")
    w("-" * 70)
    w(f"  보고서 생성: {now.strftime('%Y-%m-%d %H:%M:%S')}")
    w()

    return buf.getvalue()


def run_sector(market="ALL", output=None, chart=True):
    """섹터 보고서 실행."""
    reports = []

    if market in ("US", "ALL"):
        us_syms = [s for syms in US_SECTORS.values() for s in syms]
        us_data = scan_sector(us_syms, "US", US_SECTORS)
        if not us_data.empty:
            reports.append(generate_sector_report(us_data, "미국", market="US"))

    if market in ("KR", "ALL"):
        kr_syms = [s for syms in KR_SECTORS.values() for s in syms]
        kr_data = scan_sector(kr_syms, "KR", KR_SECTORS)
        if not kr_data.empty:
            reports.append(generate_sector_report(kr_data, "한국", market="KR"))

    full_report = "\n".join(reports) if reports else "섹터 데이터 없음.\n"
    print(full_report)

    if output:
        filepath = output
    else:
        filepath = f"sector_{datetime.now().strftime('%Y%m%d_%H%M')}.txt"

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(full_report)
    print(f"  보고서 저장: {filepath}", file=sys.stderr)

    # 차트 생성
    chart_paths = []
    if chart:
        import os
        chart_markets = []
        if market in ("US", "ALL"):
            chart_markets.append("US")
        if market in ("KR", "ALL"):
            chart_markets.append("KR")
        for m in chart_markets:
            try:
                chart_dir = os.path.dirname(filepath) or "."
                chart_path = os.path.join(chart_dir, f"risk_chart_{m}_{datetime.now().strftime('%Y%m%d_%H%M')}.png")
                result = generate_risk_chart(market=m, output_path=chart_path)
                if result:
                    chart_paths.append(result)
            except Exception as e:
                print(f"  차트 생성 실패 ({m}): {e}", file=sys.stderr)

    return filepath, chart_paths


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


def scan_minervini(symbols, min_cap=5e9):
    """미너비니 SEPA 기준 피봇바이 종목 스캔 (나스닥).

    Stage 2 Trend Template:
    - 가격 > 50MA > 150MA > 200MA
    - 200MA 최소 1개월 이상 상승 추세
    - 가격이 52주 저점 대비 25% 이상 위
    - 가격이 52주 고점 대비 75% 이상 (25% 이내)

    VCP (Volatility Contraction Pattern):
    - 최근 수축 구간의 변동폭이 이전보다 좁아짐
    - 피봇 라인 = 최근 수축 구간의 고점

    Pivot Buy:
    - 당일 종가가 피봇 라인 돌파
    - 돌파 시 거래량이 평균 대비 1.5배 이상
    """
    print(f"  [미너비니] {len(symbols)}개 종목 피봇바이 스캔 중...", file=sys.stderr)
    raw = yf.download(symbols, period="1y", interval="1d",
                      group_by="ticker", progress=False, threads=True)
    results = []

    for i, sym in enumerate(symbols):
        try:
            t = yf.Ticker(sym)
            fi = t.fast_info
            mc = getattr(fi, "market_cap", 0) or 0
            if mc < min_cap:
                continue

            if len(symbols) == 1:
                closes = raw["Close"].dropna()
                highs = raw["High"].dropna()
                lows = raw["Low"].dropna()
                volumes = raw["Volume"].dropna()
            else:
                closes = raw[(sym, "Close")].dropna()
                highs = raw[(sym, "High")].dropna()
                lows = raw[(sym, "Low")].dropna()
                volumes = raw[(sym, "Volume")].dropna()

            if len(closes) < 200:
                continue

            price = closes.iloc[-1]
            ma50 = closes.tail(50).mean()
            ma150 = closes.tail(150).mean()
            ma200 = closes.tail(200).mean()

            # Stage 2 Trend Template
            if not (price > ma50 > ma150 > ma200):
                continue

            # 200MA 상승 확인 (20일 전 대비)
            ma200_prev = closes.iloc[-220:-200].mean() if len(closes) >= 220 else closes.head(200).mean()
            if ma200 <= ma200_prev:
                continue

            # 52주 고저 체크
            h52 = highs.max()
            l52 = lows.min()
            if l52 <= 0 or h52 <= 0:
                continue
            pct_above_low = ((price - l52) / l52) * 100
            pct_from_high = (price / h52) * 100
            if pct_above_low < 25:
                continue
            if pct_from_high < 75:
                continue

            # VCP 감지: 최근 60일 내 수축 패턴 찾기
            recent_60 = closes.tail(60)
            recent_highs = highs.tail(60)
            recent_lows = lows.tail(60)

            # 3구간으로 나눠서 변동폭 비교 (20일씩)
            ranges = []
            for j in range(3):
                seg_h = recent_highs.iloc[j*20:(j+1)*20]
                seg_l = recent_lows.iloc[j*20:(j+1)*20]
                if len(seg_h) > 0 and len(seg_l) > 0:
                    seg_range = (seg_h.max() - seg_l.min()) / seg_l.min() * 100
                    ranges.append(seg_range)

            if len(ranges) < 3:
                continue

            # 수축 확인: 마지막 구간이 첫 구간보다 좁아야 함
            if ranges[2] >= ranges[0]:
                continue

            # 피봇 라인 = 최근 20일 고점
            pivot_line = recent_highs.tail(20).max()

            # 피봇 돌파 체크 (당일 종가가 피봇 이상)
            if price < pivot_line * 0.98:
                continue

            # 거래량 체크
            vol_today = volumes.iloc[-1]
            avg_vol = volumes.tail(50).mean()
            vol_ratio = vol_today / avg_vol if avg_vol > 0 else 1.0

            # 점수 계산
            score = 0
            if price >= pivot_line:
                score += 3  # 피봇 돌파
            elif price >= pivot_line * 0.98:
                score += 1  # 피봇 근접

            if vol_ratio >= 2.0:
                score += 3
            elif vol_ratio >= 1.5:
                score += 2
            elif vol_ratio >= 1.0:
                score += 1

            # 수축률 (클수록 좋음)
            contraction = (1 - ranges[2] / ranges[0]) * 100
            if contraction >= 60:
                score += 2
            elif contraction >= 40:
                score += 1

            # Fwd P/E
            try:
                info = t.info
                fwd_pe = info.get("forwardPE", None)
            except Exception:
                fwd_pe = None

            results.append(dict(
                sym=sym,
                price=price,
                pivot=pivot_line,
                pct_from_pivot=((price / pivot_line) - 1) * 100,
                ma50=ma50, ma150=ma150, ma200=ma200,
                h52=h52, l52=l52,
                pct_from_high=pct_from_high,
                pct_above_low=pct_above_low,
                vol_ratio=vol_ratio,
                contraction=contraction,
                ranges=ranges,
                mc=mc,
                score=score,
                fwd_pe=fwd_pe,
            ))

            if (i + 1) % 20 == 0:
                print(f"  ... {i+1}/{len(symbols)}", file=sys.stderr)
        except Exception:
            continue

    return pd.DataFrame(results)


def generate_minervini_report(df):
    """미너비니 피봇바이 보고서 생성."""
    buf = StringIO()
    now = datetime.now()

    def w(text=""):
        buf.write(text + "\n")

    w("=" * 70)
    w("  미너비니 Pivot Buy 스캔 (나스닥)")
    w(f"  {now.strftime('%Y년 %m월 %d일 %H:%M')} 기준")
    w(f"  조건: Stage 2 추세 + VCP 수축 + 피봇 돌파/근접")
    w("=" * 70)
    w()

    if df.empty:
        w("  조건을 충족하는 종목이 없습니다.")
        w()
        w("  미너비니 기준:")
        w("    - 가격 > 50MA > 150MA > 200MA (Stage 2)")
        w("    - 200일선 상승 중")
        w("    - 52주 저점 대비 25%↑, 고점 대비 25% 이내")
        w("    - 변동성 수축 패턴 (VCP)")
        w("    - 피봇 라인 돌파/근접 + 거래량 증가")
        w()
        return buf.getvalue()

    df = df.sort_values("score", ascending=False)

    # 피봇 돌파 vs 근접 분리
    breakout = df[df["pct_from_pivot"] >= 0]
    near_pivot = df[df["pct_from_pivot"] < 0]

    w(f"  피봇 돌파: {len(breakout)}개  |  피봇 근접 (2% 이내): {len(near_pivot)}개")
    w()

    if not breakout.empty:
        w("-" * 70)
        w("  [피봇 돌파] - 매수 타이밍!")
        w("-" * 70)
        w()
        for _, r in breakout.iterrows():
            name = get_name(r["sym"])
            grade = "S" if r["score"] >= 7 else "A" if r["score"] >= 5 else "B"
            w(f"  [{grade}] {name} ({r['sym']})")
            w(f"      현재가: ${r['price']:,.2f}  |  피봇: ${r['pivot']:,.2f}  (+{r['pct_from_pivot']:.1f}% 돌파)")
            w(f"      50MA: ${r['ma50']:,.2f}  >  150MA: ${r['ma150']:,.2f}  >  200MA: ${r['ma200']:,.2f}")
            w(f"      52주 고가 대비: {r['pct_from_high']:.1f}%  |  52주 저점 대비: +{r['pct_above_low']:.0f}%")
            w(f"      거래량: 평균 대비 {r['vol_ratio']:.1f}x  |  VCP 수축률: {r['contraction']:.0f}%")
            fwd_pe_str = f"{r['fwd_pe']:.1f}" if pd.notna(r.get('fwd_pe')) and r.get('fwd_pe') else "-"
            w(f"      시총: {fmt_cap(r['mc'], 'US')}  |  Fwd P/E: {fwd_pe_str}")
            # 코멘트
            comments = []
            if r["vol_ratio"] >= 2.0:
                comments.append("강한 거래량 돌파")
            elif r["vol_ratio"] >= 1.5:
                comments.append("거래량 확인됨")
            else:
                comments.append("거래량 미흡 - 내일 확인 필요")
            if r["contraction"] >= 60:
                comments.append("교과서적 VCP")
            if r["pct_from_high"] >= 95:
                comments.append("52주 신고가 임박")
            w(f"      -> {', '.join(comments)}")
            w()

    if not near_pivot.empty:
        w("-" * 70)
        w("  [피봇 근접] - 매수 대기 (돌파 시 진입)")
        w("-" * 70)
        w()
        for _, r in near_pivot.iterrows():
            name = get_name(r["sym"])
            w(f"  - {name} ({r['sym']}): ${r['price']:,.2f}  |  피봇: ${r['pivot']:,.2f} ({r['pct_from_pivot']:+.1f}%)")
            w(f"    MA정렬: 50>{r['ma50']:,.0f} > 150>{r['ma150']:,.0f} > 200>{r['ma200']:,.0f}")
            w(f"    VCP 수축: {r['contraction']:.0f}%  |  거래량: {r['vol_ratio']:.1f}x")
            w()

    w("=" * 70)
    w("  매매 전략")
    w("=" * 70)
    w()
    w("  [피봇 돌파 종목]")
    w("    - 거래량 1.5x 이상 확인 후 진입")
    w("    - 손절: 피봇 라인 -5~7% (또는 50MA 이탈)")
    w("    - 목표: 1차 +10~15%, 2차 +20~25%")
    w()
    w("  [피봇 근접 종목]")
    w("    - 돌파 확인 전까지 관망")
    w("    - 돌파일 거래량 반드시 확인")
    w("    - 가짜 돌파 (당일 장대 윗꼬리) 주의")
    w()
    w("-" * 70)
    w("  주의: 본 보고서는 데이터 기반 자동 생성이며 투자 권유가 아닙니다.")
    w("-" * 70)
    w(f"  보고서 생성: {now.strftime('%Y-%m-%d %H:%M:%S')}")
    w()

    return buf.getvalue()


def run_minervini(output=None):
    """미너비니 피봇바이 스캔 실행."""
    df = scan_minervini(US, min_cap=5e9)
    report = generate_minervini_report(df)

    print(report)

    if output:
        filepath = output
    else:
        filepath = f"minervini_{datetime.now().strftime('%Y%m%d_%H%M')}.txt"

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"  보고서 저장: {filepath}", file=sys.stderr)

    return filepath


def scan_longbase(symbols, min_cap=5e9):
    """롱베이스 돌파 + 첫 HTF 스캔.

    롱베이스: 3개월(60거래일) 이상 횡보 구간 형성
    돌파: 당일 종가가 베이스 상단을 넘김
    첫 HTF: 최근 6개월 내 이전 돌파 이력 없음
    거래량: 돌파일 거래량 평균 대비 증가
    """
    print(f"  [롱베이스] {len(symbols)}개 종목 스캔 중...", file=sys.stderr)
    raw = yf.download(symbols, period="1y", interval="1d",
                      group_by="ticker", progress=False, threads=True)
    results = []

    for i, sym in enumerate(symbols):
        try:
            t = yf.Ticker(sym)
            fi = t.fast_info
            mc = getattr(fi, "market_cap", 0) or 0
            if mc < min_cap:
                continue

            if len(symbols) == 1:
                closes = raw["Close"].dropna()
                highs = raw["High"].dropna()
                lows = raw["Low"].dropna()
                volumes = raw["Volume"].dropna()
            else:
                closes = raw[(sym, "Close")].dropna()
                highs = raw[(sym, "High")].dropna()
                lows = raw[(sym, "Low")].dropna()
                volumes = raw[(sym, "Volume")].dropna()

            if len(closes) < 120:
                continue

            price = closes.iloc[-1]

            # --- 롱베이스 감지 ---
            # 최근 60~120일 구간에서 횡보 베이스 찾기
            # 베이스 = 가격 범위가 좁은 구간 (레인지 15% 이내)
            best_base = None
            for base_len in [90, 75, 60]:
                if len(closes) < base_len + 10:
                    continue
                # 베이스 구간: 돌파 전일까지 (최근 5일 제외)
                base_closes = closes.iloc[-(base_len+5):-5]
                base_highs = highs.iloc[-(base_len+5):-5]
                base_lows = lows.iloc[-(base_len+5):-5]

                base_top = base_highs.max()
                base_bottom = base_lows.min()
                if base_bottom <= 0:
                    continue
                base_range_pct = (base_top - base_bottom) / base_bottom * 100

                # 베이스 범위 25% 이내면 횡보로 인정
                if base_range_pct <= 25:
                    best_base = dict(
                        length=base_len,
                        top=base_top,
                        bottom=base_bottom,
                        range_pct=base_range_pct,
                        mid=(base_top + base_bottom) / 2,
                    )
                    break

            if not best_base:
                continue

            # --- 돌파 확인 ---
            # 당일 종가가 베이스 상단 돌파
            if price < best_base["top"]:
                # 근접 체크 (2% 이내)
                if price < best_base["top"] * 0.98:
                    continue
                breakout_status = "near"
            else:
                breakout_status = "breakout"

            # --- 첫 HTF 확인 ---
            # 최근 6개월(120일) 내 베이스 상단 위에서 마감한 적이 거의 없어야 함
            recent_120 = closes.tail(120)
            days_above = (recent_120 > best_base["top"]).sum()
            # 5일 이하만 허용 (첫 돌파에 가까움)
            if days_above > 10:
                continue

            # --- 거래량 확인 ---
            vol_today = volumes.iloc[-1]
            avg_vol = volumes.tail(50).mean()
            vol_ratio = vol_today / avg_vol if avg_vol > 0 else 1.0

            # --- 추세 확인 ---
            ma50 = closes.tail(50).mean()
            ma200 = closes.tail(200).mean() if len(closes) >= 200 else closes.mean()

            # 52주 고저
            h52 = highs.max()
            l52 = lows.min()
            pct_from_high = (price / h52 * 100) if h52 > 0 else 0

            # --- 등급 ---
            score = 0
            # 돌파 여부
            if breakout_status == "breakout":
                score += 3
            else:
                score += 1

            # 거래량
            if vol_ratio >= 2.0:
                score += 3
            elif vol_ratio >= 1.5:
                score += 2
            elif vol_ratio >= 1.0:
                score += 1

            # 베이스 길이 (길수록 에너지 축적)
            if best_base["length"] >= 90:
                score += 2
            elif best_base["length"] >= 75:
                score += 1

            # 베이스 타이트함
            if best_base["range_pct"] <= 12:
                score += 2
            elif best_base["range_pct"] <= 18:
                score += 1

            # 첫 HTF (이전 돌파 적을수록)
            if days_above <= 3:
                score += 2
            elif days_above <= 5:
                score += 1

            # 추세 보너스
            if price > ma50 > ma200:
                score += 1

            # Fwd P/E
            try:
                info = t.info
                fwd_pe = info.get("forwardPE", None)
            except Exception:
                fwd_pe = None

            results.append(dict(
                sym=sym,
                price=price,
                base_top=best_base["top"],
                base_bottom=best_base["bottom"],
                base_length=best_base["length"],
                base_range=best_base["range_pct"],
                breakout_status=breakout_status,
                pct_above_base=((price / best_base["top"]) - 1) * 100,
                vol_ratio=vol_ratio,
                days_above=days_above,
                ma50=ma50, ma200=ma200,
                h52=h52, l52=l52,
                pct_from_high=pct_from_high,
                mc=mc,
                score=score,
                fwd_pe=fwd_pe,
            ))

            if (i + 1) % 20 == 0:
                print(f"  ... {i+1}/{len(symbols)}", file=sys.stderr)
        except Exception:
            continue

    return pd.DataFrame(results)


def generate_longbase_report(df):
    """롱베이스 돌파 보고서 생성."""
    buf = StringIO()
    now = datetime.now()

    def w(text=""):
        buf.write(text + "\n")

    w("=" * 70)
    w("  롱베이스 돌파 + 첫 HTF 스캔 (나스닥)")
    w(f"  {now.strftime('%Y년 %m월 %d일 %H:%M')} 기준")
    w(f"  조건: 3개월+ 횡보 베이스 → 상단 돌파 + 거래량 확인")
    w("=" * 70)
    w()

    if df.empty:
        w("  조건을 충족하는 종목이 없습니다.")
        w()
        w("  롱베이스 돌파 기준:")
        w("    - 60~90일 이상 횡보 (가격 범위 25% 이내)")
        w("    - 베이스 상단 돌파 (또는 2% 이내 근접)")
        w("    - 최근 6개월 내 첫 돌파 (HTF)")
        w("    - 거래량 증가 확인")
        w()
        return buf.getvalue()

    df = df.sort_values("score", ascending=False)

    breakout = df[df["breakout_status"] == "breakout"]
    near = df[df["breakout_status"] == "near"]

    w(f"  돌파 확정: {len(breakout)}개  |  돌파 임박 (2% 이내): {len(near)}개")
    w()

    if not breakout.empty:
        w("-" * 70)
        w("  [롱베이스 돌파] - 첫 HTF! 보유 진입 타이밍")
        w("-" * 70)
        w()
        for _, r in breakout.iterrows():
            name = get_name(r["sym"])
            grade = "S" if r["score"] >= 10 else "A" if r["score"] >= 7 else "B"
            w(f"  [{grade}] {name} ({r['sym']})")
            w(f"      현재가: ${r['price']:,.2f}  |  베이스 상단: ${r['base_top']:,.2f}  (+{r['pct_above_base']:.1f}% 돌파)")
            w(f"      베이스: {r['base_length']}일간 횡보  |  범위: {r['base_range']:.1f}% (${r['base_bottom']:,.2f}~${r['base_top']:,.2f})")
            w(f"      거래량: 평균 대비 {r['vol_ratio']:.1f}x  |  52주 고가 대비: {r['pct_from_high']:.1f}%")
            fwd_pe_str = f"{r['fwd_pe']:.1f}" if pd.notna(r.get('fwd_pe')) and r.get('fwd_pe') else "-"
            w(f"      시총: {fmt_cap(r['mc'], 'US')}  |  Fwd P/E: {fwd_pe_str}")
            w(f"      첫 HTF 확인: 최근 120일 중 상단 위 마감 {r['days_above']}일뿐")
            comments = []
            if r["vol_ratio"] >= 2.0:
                comments.append("강한 거래량 돌파!")
            elif r["vol_ratio"] >= 1.5:
                comments.append("거래량 확인됨")
            else:
                comments.append("거래량 미흡 - 추가 확인 필요")
            if r["base_length"] >= 90:
                comments.append(f"{r['base_length']}일 장기 베이스 (에너지 축적)")
            if r["base_range"] <= 12:
                comments.append("타이트한 베이스 (기관 매집 가능성)")
            if r["pct_from_high"] >= 95:
                comments.append("52주 신고가 임박")
            if r["price"] > r["ma50"] > r["ma200"]:
                comments.append("상승 추세 정렬")
            w(f"      -> {', '.join(comments)}")
            w()

    if not near.empty:
        w("-" * 70)
        w("  [돌파 임박] - 베이스 상단 2% 이내, 돌파 대기")
        w("-" * 70)
        w()
        for _, r in near.iterrows():
            name = get_name(r["sym"])
            grade = "S" if r["score"] >= 10 else "A" if r["score"] >= 7 else "B"
            w(f"  [{grade}] {name} ({r['sym']}): ${r['price']:,.2f}  |  상단: ${r['base_top']:,.2f} ({r['pct_above_base']:+.1f}%)")
            w(f"      베이스 {r['base_length']}일 / 범위 {r['base_range']:.1f}%  |  거래량: {r['vol_ratio']:.1f}x")
            w()

    w("=" * 70)
    w("  매매 전략 (롱베이스 돌파)")
    w("=" * 70)
    w()
    w("  [핵심] 롱베이스 돌파 + 첫 HTF = 보유해야 하는 자리")
    w("    - 따라 들어가는 것보다 돌파 시점에 잡는 게 중요")
    w("    - 거래량 1.5x 이상 확인 후 진입")
    w()
    w("  [진입]")
    w("    - 베이스 상단 돌파 확인 (종가 기준)")
    w("    - 돌파일 거래량 필수 확인")
    w("    - 갭업 돌파 시 시초가 진입 가능")
    w()
    w("  [손절]")
    w("    - 베이스 상단 아래 재진입 시 (-3~5%)")
    w("    - 또는 50MA 이탈 시")
    w()
    w("  [목표]")
    w("    - 1차: 베이스 범위만큼 (측정 목표치)")
    w("    - 2차: 추세 추종, 20MA 이탈 시 청산")
    w()
    w("-" * 70)
    w("  주의: 본 보고서는 데이터 기반 자동 생성이며 투자 권유가 아닙니다.")
    w("-" * 70)
    w(f"  보고서 생성: {now.strftime('%Y-%m-%d %H:%M:%S')}")
    w()

    return buf.getvalue()


def run_longbase(output=None):
    """롱베이스 돌파 스캔 실행."""
    df = scan_longbase(US, min_cap=5e9)
    report = generate_longbase_report(df)

    print(report)

    if output:
        filepath = output
    else:
        filepath = f"longbase_{datetime.now().strftime('%Y%m%d_%H%M')}.txt"

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"  보고서 저장: {filepath}", file=sys.stderr)

    return filepath


def scan_kr_new_highs(top_n=100):
    """전체 코스피+코스닥에서 거래대금 TOP N 뽑고, 그중 52주 신고가 종목 스캔 (pykrx).

    - 거래대금 순위: 당일 전체 시장 기준 (KRX 데이터)
    - 신고가: 당일 고가가 직전 52주 최고가 이상
    - 근접(97%+)은 관찰 대상으로 별도 표시
    """
    from pykrx import stock as krx

    end = krx.get_nearest_business_day_in_a_week()
    start = (datetime.strptime(end, "%Y%m%d") - timedelta(days=380)).strftime("%Y%m%d")

    print(f"  [국장] {end} 기준 전체 시장 거래대금 TOP {top_n} 조회 중...", file=sys.stderr)
    snap = krx.get_market_ohlcv_by_ticker(end, market="ALL")
    snap = snap[snap["거래대금"] > 0]
    top = snap.sort_values("거래대금", ascending=False).head(top_n)

    rows = []
    for rank, (ticker, s) in enumerate(top.iterrows(), 1):
        try:
            name = krx.get_market_ticker_name(ticker)
            if "스팩" in name:
                continue

            hist = krx.get_market_ohlcv_by_date(start, end, ticker)
            if len(hist) < 30:
                continue

            close = hist["종가"].iloc[-1]
            today_high = hist["고가"].iloc[-1]
            prior_high = hist["고가"].iloc[:-1].max()
            h52 = hist["고가"].max()
            if h52 <= 0 or prior_high <= 0:
                continue

            broke = today_high >= prior_high        # 장중 신고가 갱신
            closed_above = close >= prior_high       # 신고가 위에서 마감
            pct_h = close / h52 * 100

            # 신고가 갱신 or 97% 이상 근접만 수집
            if not broke and pct_h < 97:
                continue

            rows.append(dict(
                rank=rank, sym=ticker, name=name, price=close,
                chg=s.get("등락률", 0) or 0, tv=s["거래대금"],
                h52=h52, prior_high=prior_high, pct_h=pct_h,
                broke=broke, closed_above=closed_above,
            ))
            time.sleep(0.15)
        except Exception:
            continue

    print(f"  [국장] TOP {top_n} 중 신고가/근접 {len(rows)}개 발견", file=sys.stderr)
    return pd.DataFrame(rows), end


def grade_kr_high(r):
    """국장 신고가 종목 등급 산정: S/A/B."""
    score = 0
    if r["closed_above"]:
        score += 3      # 신고가 위 마감 (가장 강함)
    elif r["broke"]:
        score += 2      # 장중 돌파 후 되밀림
    else:
        score += 1      # 근접
    if r["rank"] <= 20:
        score += 2      # 거래대금 최상위
    elif r["rank"] <= 50:
        score += 1
    if r["chg"] >= 5:
        score += 2
    elif r["chg"] >= 2:
        score += 1
    if score >= 6:
        return "S"
    if score >= 4:
        return "A"
    return "B"


def generate_kr_highs_report(df, base_date):
    """국장 거래대금 TOP100 x 52주 신고가 보고서 생성."""
    buf = StringIO()
    now = datetime.now()

    def w(text=""):
        buf.write(text + "\n")

    date_str = f"{base_date[:4]}-{base_date[4:6]}-{base_date[6:]}"
    w("=" * 70)
    w("  국장 신고가 스캔 (코스피 + 코스닥 전체)")
    w(f"  {date_str} 장마감 기준")
    w("  조건: 거래대금 TOP 100 AND 52주 신고가 갱신")
    w("=" * 70)
    w()

    if df.empty:
        w("  오늘은 거래대금 TOP 100 중 52주 신고가 종목이 없습니다.")
        w()
        return buf.getvalue()

    df = df.copy()
    df["grade"] = df.apply(grade_kr_high, axis=1)

    new_highs = df[df["broke"]].sort_values(["grade", "rank"])
    near = df[~df["broke"]].sort_values("pct_h", ascending=False)

    w(f"  신고가 갱신: {len(new_highs)}개  |  신고가 근접(97%+): {len(near)}개")
    for g in ["S", "A", "B"]:
        cnt = len(new_highs[new_highs["grade"] == g])
        if cnt:
            w(f"    등급 {g}: {cnt}개")
    w()

    if not new_highs.empty:
        for grade in ["S", "A", "B"]:
            gdf = new_highs[new_highs["grade"] == grade]
            if gdf.empty:
                continue
            grade_label = {"S": "최우선 관심", "A": "관심", "B": "모니터링"}[grade]
            w("-" * 70)
            w(f"  === 등급 {grade} ({grade_label}) ===")
            w("-" * 70)
            w()
            for _, r in gdf.iterrows():
                status = "신고가 마감!" if r["closed_above"] else "장중 신고가 후 되밀림"
                w(f"  [{grade}] {r['name']} ({r['sym']})  -- {status}")
                w(f"      종가: {r['price']:,.0f}원  |  등락: {r['chg']:+.2f}%  |  거래대금 {r['rank']}위 ({fmt_tv(r['tv'], 'KR')})")
                w(f"      직전 52주 고가: {r['prior_high']:,.0f}원  |  고가 대비: {r['pct_h']:.1f}%")
                comments = []
                if r["closed_above"]:
                    comments.append("신고가 위 마감 - 추세 지속 가능성")
                else:
                    comments.append("윗꼬리 - 내일 재돌파 확인 필요")
                if r["rank"] <= 20:
                    comments.append("수급 최상위 (시장 주도주)")
                if r["chg"] >= 5:
                    comments.append("강한 상승")
                w(f"      -> {', '.join(comments)}")
                w()

    if not near.empty:
        w("-" * 70)
        w("  [신고가 근접] (52주 고가 대비 97% 이상, 돌파 대기)")
        w("-" * 70)
        w()
        for _, r in near.iterrows():
            w(f"  - {r['name']} ({r['sym']}): {r['price']:,.0f}원 ({r['chg']:+.2f}%)"
              f"  고가대비 {r['pct_h']:.1f}%  |  거래대금 {r['rank']}위")
        w()

    w("-" * 70)
    w("  주의: 본 보고서는 데이터 기반 자동 생성이며 투자 권유가 아닙니다.")
    w("-" * 70)
    w(f"  보고서 생성: {now.strftime('%Y-%m-%d %H:%M:%S')}")
    w()

    return buf.getvalue()


def run_kr_highs(output=None):
    """국장 거래대금 TOP100 신고가 스캔 실행. KRX 실패 시 yfinance 방식으로 대체."""
    try:
        df, base_date = scan_kr_new_highs(top_n=100)
        report = generate_kr_highs_report(df, base_date)
    except Exception as e:
        print(f"  KRX 전체 스캔 실패 ({e}) -> yfinance 유니버스 방식으로 대체", file=sys.stderr)
        dfs = [scan(KOSPI, "KR", 0), scan(KOSDAQ, "KR", 0)]
        combined = pd.concat([d for d in dfs if not d.empty], ignore_index=True) if any(not d.empty for d in dfs) else pd.DataFrame()
        report = generate_report(combined, pct_h_min=97, tv_top_pct=50, market="KR")

    print(report)

    if output:
        filepath = output
    else:
        filepath = f"kr_highs_{datetime.now().strftime('%Y%m%d_%H%M')}.txt"

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"  보고서 저장: {filepath}", file=sys.stderr)

    return filepath


def _dw(s):
    """문자열 표시 폭. 한글/전각/이모지는 2칸으로 계산."""
    return sum(2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1 for ch in str(s))


def _pad(s, width, align="left"):
    """표시 폭 기준 패딩 (한글 정렬용)."""
    s = str(s)
    gap = max(0, width - _dw(s))
    return (" " * gap + s) if align == "right" else (s + " " * gap)


def _series(raw, sym, field):
    """batch download 결과에서 (sym, field) 시계열 추출."""
    try:
        if isinstance(raw.columns, pd.MultiIndex):
            return raw[(sym, field)].dropna()
        return raw[field].dropna()
    except Exception:
        return pd.Series(dtype=float)


def scan_theme_universe(tickers, chunk_size=80):
    """테마 종목 일괄 스캔. OHLCV만 사용해서 .info 호출 없이 빠르게 처리."""
    uniq = sorted(set(tickers))
    print(f"  [테마] {len(uniq)}개 종목 스캔 중...", file=sys.stderr)
    rows = []

    for start in range(0, len(uniq), chunk_size):
        chunk = uniq[start:start + chunk_size]
        raw = None
        for attempt in range(3):
            try:
                raw = yf.download(chunk, period="1y", interval="1d", group_by="ticker",
                                  progress=False, threads=True, auto_adjust=False)
                if raw is not None and not raw.empty:
                    break
            except Exception:
                pass
            time.sleep(2 * (attempt + 1))
        if raw is None or raw.empty:
            print(f"  ... {start+1}-{start+len(chunk)} 실패 (스킵)", file=sys.stderr)
            continue

        for sym in chunk:
            try:
                closes = _series(raw, sym, "Close")
                highs = _series(raw, sym, "High")
                vols = _series(raw, sym, "Volume")
                if len(closes) < 30:
                    continue

                price = float(closes.iloc[-1])
                prev = float(closes.iloc[-2])
                if price <= 0 or prev <= 0:
                    continue
                chg = (price / prev - 1) * 100

                c5 = float(closes.iloc[-6]) if len(closes) >= 6 else prev
                c20 = float(closes.iloc[-21]) if len(closes) >= 21 else float(closes.iloc[0])
                chg_5d = (price / c5 - 1) * 100 if c5 > 0 else 0
                chg_20d = (price / c20 - 1) * 100 if c20 > 0 else 0

                h52 = float(highs.max()) if len(highs) else price
                pct_h = (price / h52 * 100) if h52 > 0 else 0

                if len(vols) >= 21:
                    avg_v = float(vols.iloc[-21:-1].mean())
                    vol_r = float(vols.iloc[-1]) / avg_v if avg_v > 0 else 1.0
                else:
                    vol_r = 1.0

                rows.append(dict(sym=sym, price=price, chg=chg, chg_5d=chg_5d,
                                 chg_20d=chg_20d, h52=h52, pct_h=pct_h, vol_r=vol_r))
            except Exception:
                continue

        print(f"  ... {min(start+chunk_size, len(uniq))}/{len(uniq)}", file=sys.stderr)

    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.set_index("sym")
    print(f"  [테마] {len(df)}개 종목 데이터 확보", file=sys.stderr)
    return df


def generate_theme_report(data):
    """테마별 관심종목 탭 보고서 생성."""
    buf = StringIO()
    now = datetime.now()

    def w(text=""):
        buf.write(text + "\n")

    w("=" * 78)
    w("  미장 테마별 관심종목")
    w(f"  {now.strftime('%Y년 %m월 %d일 %H:%M')} 기준 (장마감)")
    w("=" * 78)
    w()

    if data.empty:
        w("  데이터를 가져오지 못했습니다.")
        return buf.getvalue()

    # 테마별 집계
    stats = {}
    for theme, syms in US_THEMES.items():
        have = [s for s in syms if s in data.index]
        if not have:
            continue
        sub = data.loc[have]
        stats[theme] = dict(
            avg=sub["chg"].mean(),
            avg_5d=sub["chg_5d"].mean(),
            avg_20d=sub["chg_20d"].mean(),
            up=int((sub["chg"] > 0).sum()),
            n=len(sub),
            near_high=int((sub["pct_h"] >= 97).sum()),
            leader=sub["chg"].idxmax(),
            leader_chg=sub["chg"].max(),
        )

    if not stats:
        w("  테마 데이터 없음.")
        return buf.getvalue()

    ranked = sorted(stats.items(), key=lambda kv: kv[1]["avg"], reverse=True)

    def box(title):
        w("┌" + "─" * 76 + "┐")
        w("│  " + _pad(title, 74) + "│")
        w("└" + "─" * 76 + "┘")

    def rank_header(with_leader=True):
        head = ("  " + _pad("순위", 4, "right") + "  " + _pad("테마", 20)
                + _pad("당일", 8, "right") + _pad("5일", 9, "right")
                + _pad("20일", 9, "right") + "  " + _pad("상승", 7, "right"))
        if with_leader:
            head += "  주도주"
        w(head)
        w("  " + "─" * 74)

    def rank_row(i, theme, s, with_leader=True):
        row = ("  " + _pad(i, 4, "right") + "  " + _pad(theme, 20)
               + _pad(f"{s['avg']:+.2f}%", 8, "right")
               + _pad(f"{s['avg_5d']:+.2f}%", 9, "right")
               + _pad(f"{s['avg_20d']:+.2f}%", 9, "right")
               + "  " + _pad(f"{s['up']}/{s['n']}", 7, "right"))
        if with_leader:
            row += f"  {get_name(s['leader'])} ({s['leader_chg']:+.1f}%)"
        w(row)

    # ─── 테마 순위 요약 ───
    box("오늘 강세 테마 TOP 15")
    rank_header()
    for i, (theme, s) in enumerate(ranked[:15], 1):
        rank_row(i, theme, s)
    w()

    box("오늘 약세 테마 TOP 10")
    rank_header(with_leader=False)
    for i, (theme, s) in enumerate(reversed(ranked[-10:]), 1):
        rank_row(i, theme, s, with_leader=False)
    w()

    # ─── 신고가권 종목 (테마 무관 전체) ───
    near = data[data["pct_h"] >= 98].sort_values("pct_h", ascending=False)
    if not near.empty:
        sym_theme = {}
        for theme, syms in US_THEMES.items():
            for s in syms:
                sym_theme.setdefault(s, theme)
        box(f"52주 신고가권 종목 {len(near)}개 (고가대비 98% 이상)")
        for sym, r in near.iterrows():
            w("    " + _pad(sym, 7) + _pad(get_name(sym), 25)
              + _pad(f"${r['price']:,.2f}", 11, "right")
              + _pad(f"{r['chg']:+.2f}%", 9, "right")
              + f"   52H {r['pct_h']:>5.1f}%   [{sym_theme.get(sym, '-')}]")
        w()

    # ─── 대분류 → 테마 탭 ───
    for group, themes in THEME_GROUPS.items():
        present = [t for t in themes if t in stats]
        if not present:
            continue
        present.sort(key=lambda t: stats[t]["avg"], reverse=True)

        w()
        w("=" * 78)
        w(f"  ▓▓  {group}  ▓▓")
        w("=" * 78)

        for theme in present:
            s = stats[theme]
            syms = [x for x in US_THEMES[theme] if x in data.index]
            sub = data.loc[syms].sort_values("chg", ascending=False)

            label = f"┌─[ {theme} ]"
            label += "─" * max(2, 42 - _dw(label))
            tail = f" 평균 {s['avg']:+.2f}%  |  상승 {s['up']}/{s['n']}"
            if s["near_high"]:
                tail += f"  |  신고가권 {s['near_high']}"
            w()
            w("  " + label + tail)

            for sym, r in sub.iterrows():
                mark = "★" if r["pct_h"] >= 98 else "◆" if r["pct_h"] >= 95 else " "
                vol_mark = "*" if r["vol_r"] >= 2.0 else " "
                w("  │ " + _pad(sym, 7) + _pad(get_name(sym), 23)
                  + _pad(f"${r['price']:,.2f}", 11, "right")
                  + _pad(f"{r['chg']:+.2f}%", 9, "right")
                  + f"  52H {r['pct_h']:>5.1f}% {mark}{vol_mark}")
            w("  └" + "─" * 74)

    w()
    w("=" * 78)
    w("  표기 안내")
    w("=" * 78)
    w("    ★  52주 고가 대비 98% 이상 (신고가권)")
    w("    ◆  52주 고가 대비 95% 이상 (고가 근접)")
    w("    *  거래량 20일 평균 대비 2배 이상 (수급 급증)")
    w()
    w("  각 테마의 '평균'은 소속 종목 등락률의 단순 평균입니다.")
    w("  테마 탭은 그룹 내에서 당일 성과가 좋은 순서로 정렬됩니다.")
    w()
    w("-" * 78)
    w("  주의: 본 보고서는 데이터 기반 자동 생성이며 투자 권유가 아닙니다.")
    w("-" * 78)
    w(f"  보고서 생성: {now.strftime('%Y-%m-%d %H:%M:%S')}")
    w()

    return buf.getvalue()


def run_themes(output=None):
    """테마별 관심종목 보고서 실행."""
    all_syms = [s for syms in US_THEMES.values() for s in syms]
    data = scan_theme_universe(all_syms)
    report = generate_theme_report(data)

    print(report)

    if output:
        filepath = output
    else:
        filepath = f"themes_{datetime.now().strftime('%Y%m%d_%H%M')}.txt"

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"  보고서 저장: {filepath}", file=sys.stderr)

    return filepath


def run_report(market="ALL", output=None, chart=True):
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
    report = generate_report(combined, market=market)

    print(report)

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
    parser.add_argument("--sector", action="store_true",
                        help="섹터별 성과 보고서 생성")
    parser.add_argument("--minervini", action="store_true",
                        help="미너비니 SEPA 피봇바이 스캔 (나스닥)")
    parser.add_argument("--longbase", action="store_true",
                        help="롱베이스 돌파 + 첫 HTF 스캔 (나스닥)")
    parser.add_argument("--kr-highs", action="store_true",
                        help="국장 거래대금 TOP100 x 52주 신고가 스캔 (전체 시장)")
    parser.add_argument("--themes", action="store_true",
                        help="미장 테마별 관심종목 보고서 (디램/CPU/원자력 등 세부 테마)")
    parser.add_argument("--no-chart", action="store_true",
                        help="차트 생성 비활성화")
    args = parser.parse_args()
    if args.themes:
        run_themes(output=args.output)
    elif args.kr_highs:
        run_kr_highs(output=args.output)
    elif args.minervini:
        run_minervini(output=args.output)
    elif args.longbase:
        run_longbase(output=args.output)
    elif args.premarket:
        run_premarket(output=args.output)
    elif args.sector:
        run_sector(market=args.market, output=args.output, chart=not args.no_chart)
    else:
        run_report(market=args.market, output=args.output)


if __name__ == "__main__":
    main()
