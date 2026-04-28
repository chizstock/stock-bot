"""
한국투자증권 Open API + 기술적 분석 유틸리티
GitHub Actions용 (해외 IP 대응, 환경변수 지원)
테스트 완료: 2026-04-28 로컬 PC에서 검증
"""
import urllib.request, urllib.error, json, datetime, statistics, time, os, ssl

# === CONFIG ===
APP_KEY = os.environ.get('KIS_APP_KEY', '')
APP_SECRET = os.environ.get('KIS_APP_SECRET', '')
BASE_URL = "https://openapi.koreainvestment.com:9443"

TELEGRAM_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '')
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID', '6006891840')

PORTFOLIO = {
    '034020': {'name': '두산에너빌리티', 'qty': 416, 'avg': 100441},
    '005930': {'name': '삼성전자', 'qty': 151, 'avg': 200301},
    '247540': {'name': '에코프로비엠', 'qty': 27, 'avg': 308555},
    '407820': {'name': '에스피소프트', 'qty': 200, 'avg': 6070},
    '456570': {'name': '인투셀', 'qty': 84, 'avg': 38450},
    '086790': {'name': '하나금융지주', 'qty': 70, 'avg': 117657},
    '064350': {'name': '현대로템', 'qty': 33, 'avg': 166600},
    '005380': {'name': '현대차', 'qty': 10, 'avg': 516500},
    '105560': {'name': 'KB금융', 'qty': 101, 'avg': 157692},
    '003550': {'name': 'LG(지주)', 'qty': 51, 'avg': 98625},
    '001120': {'name': 'LX인터내셔널', 'qty': 480, 'avg': 41401},
    '063570': {'name': 'NICE인프라', 'qty': 300, 'avg': 4550},
    '005490': {'name': 'POSCO홀딩스', 'qty': 15, 'avg': 543800},
    '000660': {'name': 'SK하이닉스', 'qty': 30, 'avg': 984583},
}

# ETF/ETN 키워드 필터 (거래량순위에서 제외)
ETF_KEYWORDS = ['KODEX', 'TIGER', 'RISE', 'KBSTAR', 'HANARO', 'SOL', 'KOSEF',
                'ACE', 'ARIRANG', 'ETN', 'PLUS', '레버리지', '인버스', '선물']

# === HTTP 유틸 (해외 IP 대응) ===
COMMON_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
    'Accept': 'application/json, text/plain, */*',
    'Accept-Language': 'ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7',
    'Accept-Encoding': 'identity',
}

SSL_CTX = ssl.create_default_context()

def _http_request(url, headers=None, data=None, method=None, max_retries=3, timeout=20):
    """재시도 포함 HTTP 요청"""
    hdrs = dict(COMMON_HEADERS)
    if headers:
        hdrs.update(headers)
    for attempt in range(max_retries):
        try:
            req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
            with urllib.request.urlopen(req, timeout=timeout, context=SSL_CTX) as resp:
                return json.loads(resp.read().decode('utf-8'))
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep((2 ** attempt) * 3)
            elif e.code >= 500 and attempt < max_retries - 1:
                time.sleep(2 ** attempt)
            else:
                raise
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
            if attempt < max_retries - 1:
                print(f"  ⏳ 재시도 ({attempt+1}/{max_retries}): {e}")
                time.sleep(3 * (attempt + 1))
            else:
                raise
    return None

# === AUTH (한투 API) ===
_token_cache = {"token": None, "expires": 0}
TOKEN_FILE = "kis_token.json"

def _load_token_from_file():
    try:
        with open(TOKEN_FILE, 'r') as f:
            d = json.load(f)
            return d.get("token"), d.get("expires", 0)
    except:
        return None, 0

def _save_token_to_file(token, expires):
    try:
        with open(TOKEN_FILE, 'w') as f:
            json.dump({"token": token, "expires": expires}, f)
    except:
        pass

def get_token():
    """한투 API 토큰 (파일 캐싱 + 재시도)"""
    now = time.time()
    if _token_cache["token"] and now < _token_cache["expires"]:
        return _token_cache["token"]
    ft, fe = _load_token_from_file()
    if ft and now < fe:
        _token_cache["token"] = ft
        _token_cache["expires"] = fe
        return ft

    url = f"{BASE_URL}/oauth2/tokenP"
    body = json.dumps({"grant_type": "client_credentials", "appkey": APP_KEY, "appsecret": APP_SECRET}).encode()
    for attempt in range(3):
        try:
            print(f"  🔑 토큰 발급 시도 ({attempt+1}/3)...")
            result = _http_request(url, headers={"Content-Type": "application/json"}, data=body, method='POST', timeout=30)
            if result and 'access_token' in result:
                token = result["access_token"]
                expires = now + 80000
                _token_cache["token"] = token
                _token_cache["expires"] = expires
                _save_token_to_file(token, expires)
                print(f"  ✅ 토큰 발급 성공")
                return token
            print(f"  ❌ 응답 이상: {result}")
        except Exception as e:
            print(f"  ❌ 토큰 실패 ({attempt+1}/3): {e}")
        time.sleep(5 * (attempt + 1))
    raise Exception("한투 API 토큰 발급 3회 실패")

def _kis_headers(tr_id):
    token = get_token()
    return {
        "Content-Type": "application/json; charset=utf-8",
        "authorization": f"Bearer {token}",
        "appkey": APP_KEY, "appsecret": APP_SECRET,
        "tr_id": tr_id,
        "User-Agent": COMMON_HEADERS['User-Agent'],
    }

def _kis_get(path, tr_id, params):
    url = f"{BASE_URL}{path}?{params}"
    hdrs = _kis_headers(tr_id)
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers=hdrs)
            with urllib.request.urlopen(req, timeout=20, context=SSL_CTX) as resp:
                result = json.loads(resp.read().decode('utf-8'))
                if result.get('rt_cd') != '0':
                    print(f"  ⚠️ API (rt_cd={result.get('rt_cd')}): {result.get('msg1','')}")
                return result
        except Exception as e:
            if attempt < 2:
                time.sleep(3 * (attempt + 1))
            else:
                raise
    return {"output": []}

# === 거래량 순위 (한투 API, 검증 완료) ===
def _is_etf(name):
    """ETF/ETN 종목 필터"""
    return any(kw in name for kw in ETF_KEYWORDS)

def get_volume_rank_all(count=200):
    """
    거래량 순위 보통주 전체 수집 (코스피+코스닥 통합)
    - tr_id: FHPST01710000
    - FID_BLNG_CLS_CODE=3 (보통주만)
    - 가격대 9구간 분할 → 중복제거 → 거래량순
    - 네이버 API로 코스피/코스닥 시장 구분
    """
    print(f"\n  📊 거래량 순위 수집 시작 (보통주, 가격대 9구간)")

    price_ranges = [
        (0, 1000), (1000, 3000), (3000, 5000), (5000, 10000),
        (10000, 20000), (20000, 50000), (50000, 100000),
        (100000, 300000), (300000, 0),
    ]

    path = "/uapi/domestic-stock/v1/quotations/volume-rank"
    all_stocks = {}
    call_count = 0

    for p_min, p_max in price_ranges:
        try:
            if call_count > 0:
                time.sleep(3)

            p2_str = str(p_max) if p_max > 0 else ""
            params = ("FID_COND_MRKT_DIV_CODE=J"
                      "&FID_COND_SCR_DIV_CODE=20171"
                      "&FID_INPUT_ISCD=0000"
                      "&FID_DIV_CLS_CODE=0"
                      "&FID_BLNG_CLS_CODE=3"
                      "&FID_TRGT_CLS_CODE=111111111"
                      "&FID_TRGT_EXLS_CLS_CODE=0000000000"
                      f"&FID_INPUT_PRICE_1={p_min}"
                      f"&FID_INPUT_PRICE_2={p2_str}"
                      "&FID_VOL_CNT="
                      "&FID_INPUT_DATE_1=")

            result = _kis_get(path, "FHPST01710000", params)
            items = result.get("output", [])
            call_count += 1

            new_count = 0
            for item in items:
                code = str(item.get('mksc_shrn_iscd', '')).strip()
                name = str(item.get('hts_kor_isnm', '')).strip()
                if not code or code in all_stocks:
                    continue
                if _is_etf(name):
                    continue

                vol_str = str(item.get('acml_vol', '0')).replace(',', '')
                price_str = str(item.get('stck_prpr', '0')).replace(',', '')
                all_stocks[code] = {
                    'code': code,
                    'name': name,
                    'volume': int(vol_str) if vol_str.isdigit() else 0,
                    'price': int(price_str) if price_str.isdigit() else 0,
                    'change_pct': float(str(item.get('prdy_ctrt', '0')).replace(',', '') or '0'),
                    'market': '',  # 나중에 네이버로 구분
                }
                new_count += 1

            label = f"{p_max:,}" if p_max > 0 else "무제한"
            print(f"    {p_min:>7,}~{label:>7}: {len(items)}건 (신규 {new_count})")

        except Exception as e:
            print(f"  ❌ 구간 실패: {e}")
            time.sleep(5)

    sorted_stocks = sorted(all_stocks.values(), key=lambda x: x['volume'], reverse=True)
    print(f"  ✅ 보통주 총 {len(sorted_stocks)}개 수집 (ETF 제외)")

    # 상위 N개만 시장 구분 (네이버 API)
    top_stocks = sorted_stocks[:count]
    print(f"\n  📊 상위 {len(top_stocks)}개 시장 구분 중...")
    for i, s in enumerate(top_stocks):
        try:
            url = f"https://m.stock.naver.com/api/stock/{s['code']}/basic"
            data = _http_request(url)
            if data:
                market_name = data.get('stockExchangeType', {}).get('name', '')
                s['market'] = 'KOSPI' if 'KOSPI' in market_name.upper() else 'KOSDAQ'
            time.sleep(0.1)
        except:
            s['market'] = ''
        if (i + 1) % 50 == 0:
            print(f"    {i+1}/{len(top_stocks)} 완료")

    kospi = [s for s in top_stocks if s['market'] == 'KOSPI']
    kosdaq = [s for s in top_stocks if s['market'] == 'KOSDAQ']
    unknown = [s for s in top_stocks if s['market'] == '']
    print(f"  ✅ 코스피 {len(kospi)}개 / 코스닥 {len(kosdaq)}개 / 미분류 {len(unknown)}개")

    return kospi, kosdaq

# === 네이버 시세 ===
def get_price_naver(code):
    """네이버 실시간 시세"""
    try:
        url = f'https://m.stock.naver.com/api/stock/{code}/basic'
        result = _http_request(url)
        if not result:
            return {'code': code, 'error': 'empty response'}
        return {
            'code': code,
            'name': result.get('stockName', ''),
            'price': int(result.get('closePrice', '0').replace(',', '')),
            'change': int(result.get('compareToPreviousClosePrice', '0').replace(',', '')),
            'change_pct': float(result.get('fluctuationsRatio', 0)),
            'open': int(result.get('openPrice', '0').replace(',', '')),
            'high': int(result.get('highPrice', '0').replace(',', '')),
            'low': int(result.get('lowPrice', '0').replace(',', '')),
            'volume': int(result.get('accumulatedTradingVolume', 0)),
            'foreign_ratio': float(result.get('foreignOwnershipRatio', 0)),
        }
    except Exception as e:
        return {'code': code, 'error': str(e)}

def get_price(code, source='naver'):
    return get_price_naver(code)

# === 일봉 차트 (네이버) ===
def get_daily_chart_naver(code, page=1, page_size=60):
    try:
        url = f'https://m.stock.naver.com/api/stock/{code}/price?pageSize={page_size}&page={page}'
        items = _http_request(url)
        if not isinstance(items, list):
            return []
        result = []
        for item in items:
            result.append({
                'stck_bsop_date': item['localTradedAt'].replace('-', ''),
                'stck_oprc': item['openPrice'].replace(',', ''),
                'stck_hgpr': item['highPrice'].replace(',', ''),
                'stck_lwpr': item['lowPrice'].replace(',', ''),
                'stck_clpr': item['closePrice'].replace(',', ''),
                'acml_vol': str(item['accumulatedTradingVolume'])
            })
        return result
    except:
        return []

def get_daily_chart_long_naver(code, days=500):
    all_data = []
    page = 1
    while len(all_data) < days:
        items = get_daily_chart_naver(code, page=page, page_size=60)
        if not items:
            break
        all_data.extend(items)
        page += 1
        time.sleep(0.15)
    return all_data[:days]

# === 기술적 분석 ===
def calc_technical(code, days=500):
    data = get_daily_chart_long_naver(code, days)
    if len(data) < 56:
        return None

    closes = [int(d['stck_clpr']) for d in data]
    highs = [int(d['stck_hgpr']) for d in data]
    lows = [int(d['stck_lwpr']) for d in data]
    volumes = [int(d['acml_vol']) for d in data]
    opens = [int(d['stck_oprc']) for d in data]

    result = {"price": closes[0], "data_days": len(data)}

    for period in [5, 20, 33, 56, 112, 224, 448]:
        if len(closes) >= period:
            result[f"ma{period}"] = sum(closes[:period]) / period

    if "ma56" in result and "ma33" in result:
        result["gc_56_33"] = result["ma56"] > result["ma33"]
    if "ma112" in result and "ma56" in result:
        result["gc_112_56"] = result["ma112"] > result["ma56"]

    if all(f"ma{p}" in result for p in [112, 224, 448]):
        m112, m224, m448 = result["ma112"], result["ma224"], result["ma448"]
        if m112 > m224 > m448:
            result["ma_arrangement"] = "BULLISH"
        elif m112 < m224 < m448:
            result["ma_arrangement"] = "BEARISH"
        else:
            result["ma_arrangement"] = "TRANSITIONING"

    if len(volumes) >= 20:
        vol_avg20 = sum(volumes[:20]) / 20
        result["vol_ratio"] = volumes[0] / vol_avg20 * 100 if vol_avg20 > 0 else 0

    if len(closes) >= 20:
        bb = closes[:20]
        bbm = statistics.mean(bb)
        bbs = statistics.stdev(bb)
        result["bb_upper"] = bbm + 2 * bbs
        result["bb_mid"] = bbm
        result["bb_lower"] = bbm - 2 * bbs
        result["bb_width"] = (result["bb_upper"] - result["bb_lower"]) / bbm * 100

    if len(data) >= 52:
        tenkan = (max(highs[:9]) + min(lows[:9])) / 2
        kijun = (max(highs[:26]) + min(lows[:26])) / 2
        senkou_a = (tenkan + kijun) / 2
        senkou_b = (max(highs[:52]) + min(lows[:52])) / 2
        cloud_top = max(senkou_a, senkou_b)
        cloud_bottom = min(senkou_a, senkou_b)
        result["ichimoku"] = {"tenkan": tenkan, "kijun": kijun, "senkou_a": senkou_a, "senkou_b": senkou_b, "cloud_top": cloud_top, "cloud_bottom": cloud_bottom}
        if closes[0] > cloud_top:
            result["cloud_position"] = "ABOVE"
        elif closes[0] < cloud_bottom:
            result["cloud_position"] = "BELOW"
        else:
            result["cloud_position"] = "INSIDE"

    if len(data) >= 20:
        body_ratio = abs(closes[0] - opens[0]) / max(highs[0] - lows[0], 1)
        result["power_candle"] = (closes[0] > opens[0]) and body_ratio > 0.7 and result.get("vol_ratio", 0) > 200

    if "ma224" in result:
        result["above_ma224"] = closes[0] > result["ma224"]
        result["ma224_dist"] = (closes[0] - result["ma224"]) / result["ma224"] * 100

    return result

# === 단테 스코어링 ===
def dante_score(ta):
    if ta is None:
        return {"mandatory": 0, "bonus": 0, "total": 0, "details": []}

    mandatory = 0
    optional = 0
    reasons = []

    arr = ta.get("ma_arrangement", "")
    if arr in ("TRANSITIONING", "BULLISH"):
        mandatory += 1
        reasons.append(f"이평선 {arr}")

    if ta.get("cloud_position") == "ABOVE":
        mandatory += 1
        reasons.append("구름대 위")

    if ta.get("above_ma224"):
        mandatory += 1
        reasons.append(f"224선 돌파({ta.get('ma224_dist',0):.1f}%)")
    elif ta.get("ma224_dist", -999) > -3:
        mandatory += 1
        reasons.append(f"224선 근접({ta.get('ma224_dist',0):.1f}%)")

    if ta.get("vol_ratio", 0) >= 150:
        mandatory += 1
        reasons.append(f"거래량 {ta.get('vol_ratio',0):.0f}%")

    if ta.get("gc_56_33") or ta.get("gc_112_56"):
        mandatory += 1
        reasons.append(f"GC {'56>33' if ta.get('gc_56_33') else '112>56'}")

    if ta.get("power_candle"):
        mandatory += 1
        reasons.append("세력봉")

    if ta.get("bb_width", 999) < 10 and ta.get("price", 0) > ta.get("bb_upper", 999999):
        optional += 1
        reasons.append("볼밴 돌파")

    ichi = ta.get("ichimoku", {})
    if ichi.get("senkou_a", 0) > ichi.get("senkou_b", 0):
        optional += 1
        reasons.append("구름대 상방")

    return {"mandatory": mandatory, "bonus": optional, "total": mandatory * 2 + optional, "details": reasons}

# === 텔레그램 ===
def send_telegram(text):
    data = json.dumps({"chat_id": int(TELEGRAM_CHAT_ID), "text": text}).encode()
    _http_request(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
        headers={"Content-Type": "application/json"}, data=data, method='POST')

def send_telegram_long(text):
    while text:
        chunk = text[:4096]
        if len(text) > 4096:
            nl = chunk.rfind('\n')
            if nl > 3000:
                chunk = text[:nl]
        send_telegram(chunk)
        text = text[len(chunk):].lstrip('\n')
        if text:
            time.sleep(0.5)

# === 포트폴리오 ===
def analyze_portfolio():
    results = []
    for code, info in PORTFOLIO.items():
        try:
            p = get_price_naver(code)
            if 'error' in p:
                raise Exception(p['error'])
            cur = p['price']
            pnl = (cur - info["avg"]) / info["avg"] * 100
            results.append({
                "code": code, "name": info["name"], "qty": info["qty"], "avg": info["avg"],
                "cur_price": cur, "change_pct": p.get('change_pct', 0),
                "pnl_pct": pnl, "pnl_amt": (cur - info["avg"]) * info["qty"],
                "volume": p.get('volume', 0),
            })
            time.sleep(0.15)
        except Exception as e:
            results.append({"code": code, "name": info["name"], "error": str(e)})
    return results
