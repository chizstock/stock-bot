"""
한국투자증권 Open API + 기술적 분석 유틸리티
GitHub Actions용 (해외 IP 대응, 환경변수 지원)
"""
import urllib.request, urllib.error, json, datetime, statistics, time, re, os, ssl

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

# === HTTP 유틸 (해외 IP 대응) ===
COMMON_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
    'Accept': 'application/json, text/plain, */*',
    'Accept-Language': 'ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7',
    'Accept-Encoding': 'identity',
}

# SSL 컨텍스트 (해외 서버에서 인증서 문제 방지)
SSL_CTX = ssl.create_default_context()

def _http_request(url, headers=None, data=None, method=None, max_retries=3, timeout=15):
    """재시도 로직 포함 HTTP 요청"""
    hdrs = dict(COMMON_HEADERS)
    if headers:
        hdrs.update(headers)
    
    for attempt in range(max_retries):
        try:
            req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
            with urllib.request.urlopen(req, timeout=timeout, context=SSL_CTX) as resp:
                return json.loads(resp.read().decode('utf-8'))
        except urllib.error.HTTPError as e:
            if e.code == 429:  # Too Many Requests
                wait = (2 ** attempt) * 2
                print(f"  ⏳ Rate limit, {wait}초 대기...")
                time.sleep(wait)
            elif e.code >= 500 and attempt < max_retries - 1:
                time.sleep(2 ** attempt)
            else:
                raise
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            if attempt < max_retries - 1:
                wait = 2 ** attempt
                print(f"  ⏳ 연결 재시도 ({attempt+1}/{max_retries}): {e}")
                time.sleep(wait)
            else:
                raise
    return None

# === AUTH (한투 API) ===
_token_cache = {"token": None, "expires": 0}
TOKEN_FILE = "kis_token.json"

def _load_token_from_file():
    try:
        with open(TOKEN_FILE, 'r') as f:
            data = json.load(f)
            return data.get("token"), data.get("expires", 0)
    except:
        return None, 0

def _save_token_to_file(token, expires):
    try:
        with open(TOKEN_FILE, 'w') as f:
            json.dump({"token": token, "expires": expires}, f)
    except:
        pass

def get_token():
    """한투 API 토큰 (파일 캐싱 + 메모리 캐싱)"""
    now = time.time()
    if _token_cache["token"] and now < _token_cache["expires"]:
        return _token_cache["token"]
    
    file_token, file_expires = _load_token_from_file()
    if file_token and now < file_expires:
        _token_cache["token"] = file_token
        _token_cache["expires"] = file_expires
        return file_token
    
    url = f"{BASE_URL}/oauth2/tokenP"
    body = json.dumps({
        "grant_type": "client_credentials",
        "appkey": APP_KEY,
        "appsecret": APP_SECRET
    }).encode()
    
    result = _http_request(url, 
        headers={"Content-Type": "application/json"},
        data=body, method='POST')
    
    token = result["access_token"]
    expires = now + 80000
    _token_cache["token"] = token
    _token_cache["expires"] = expires
    _save_token_to_file(token, expires)
    return token

def _kis_headers(tr_id):
    """한투 API 공통 헤더"""
    token = get_token()
    return {
        "Content-Type": "application/json; charset=utf-8",
        "authorization": f"Bearer {token}",
        "appkey": APP_KEY,
        "appsecret": APP_SECRET,
        "tr_id": tr_id,
        "User-Agent": COMMON_HEADERS['User-Agent'],
    }

def _kis_get(path, tr_id, params):
    """한투 API GET 요청 (재시도 포함)"""
    url = f"{BASE_URL}{path}?{params}"
    hdrs = _kis_headers(tr_id)
    
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers=hdrs)
            with urllib.request.urlopen(req, timeout=15, context=SSL_CTX) as resp:
                return json.loads(resp.read().decode('utf-8'))
        except Exception as e:
            if attempt < 2:
                time.sleep(1 + attempt)
            else:
                raise

# === 거래량 순위 (한투 API) ===
def _get_volume_rank_raw(market='J', price_min=0, price_max=0):
    """거래량순위 단일 조회 (최대 30건)"""
    path = "/uapi/domestic-stock/v1/quotations/volume-rank"
    params = (f"FID_COND_MRKT_DIV_CODE={market}"
              f"&FID_COND_SCR_DIV_CODE=20171"
              f"&FID_INPUT_ISCD=0000"
              f"&FID_DIV_CLS_CODE=0"
              f"&FID_BLNG_CLS_CODE=1"       # 보통주만
              f"&FID_TRGT_CLS_CODE=111111111"
              f"&FID_TRGT_EXLS_CLS_CODE=000000"
              f"&FID_INPUT_PRICE_1={price_min}"
              f"&FID_INPUT_PRICE_2={price_max}"
              f"&FID_VOL_CNT=0"
              f"&FID_INPUT_DATE_1=")
    
    result = _kis_get(path, "FHKST130000C0", params)
    return result.get("output", [])

def get_volume_rank_top(market='J', count=100):
    """
    거래량 순위 상위 N개 조회 (가격대별 분할 → 중복제거 → 거래량순 정렬)
    market: J=코스피, Q=코스닥
    """
    if market == 'J':
        price_ranges = [(0, 5000), (5000, 20000), (20000, 100000), (100000, 0)]
    else:
        price_ranges = [(0, 3000), (3000, 10000), (10000, 50000), (50000, 0)]
    
    all_stocks = {}
    
    for p_min, p_max in price_ranges:
        try:
            items = _get_volume_rank_raw(market, p_min, p_max)
            for item in items:
                code = item.get('mksc_shrn_iscd', '').strip()
                if not code or code in all_stocks:
                    continue
                
                vol_str = item.get('acml_vol', '0').replace(',', '')
                price_str = item.get('stck_prpr', '0').replace(',', '')
                
                all_stocks[code] = {
                    'code': code,
                    'name': item.get('hts_kor_isnm', '').strip(),
                    'volume': int(vol_str) if vol_str.isdigit() else 0,
                    'price': int(price_str) if price_str.isdigit() else 0,
                    'change_pct': float(item.get('prdy_ctrt', '0').replace(',', '') or '0'),
                }
            time.sleep(0.5)
        except Exception as e:
            print(f"  ⚠️ 거래량순위 조회 실패 ({market}, {p_min}-{p_max}): {e}")
    
    # 거래량순 정렬 → 상위 N개
    sorted_stocks = sorted(all_stocks.values(), key=lambda x: x['volume'], reverse=True)
    return sorted_stocks[:count]

# === 네이버 시세 (해외 IP 대응) ===
def get_price_naver(code):
    """네이버 실시간 시세 (재시도 포함)"""
    try:
        url = f'https://m.stock.naver.com/api/stock/{code}/basic'
        result = _http_request(url)
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

# === 일봉 차트 (네이버, 해외 IP 대응) ===
def get_daily_chart_naver(code, page=1, page_size=60):
    """네이버 일봉 차트 (페이지네이션, 재시도 포함)"""
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
    except Exception as e:
        return []

def get_daily_chart_long_naver(code, days=500):
    """네이버 장기 일봉 (페이지네이션)"""
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
    """종목의 기술적 지표 전체 계산"""
    data = get_daily_chart_long_naver(code, days)
    if len(data) < 56:
        return None

    closes = [int(d['stck_clpr']) for d in data]
    highs = [int(d['stck_hgpr']) for d in data]
    lows = [int(d['stck_lwpr']) for d in data]
    volumes = [int(d['acml_vol']) for d in data]
    opens = [int(d['stck_oprc']) for d in data]

    result = {"price": closes[0], "data_days": len(data)}

    # 이동평균선
    for period in [5, 20, 33, 56, 112, 224, 448]:
        if len(closes) >= period:
            result[f"ma{period}"] = sum(closes[:period]) / period

    # 골든크로스
    if "ma56" in result and "ma33" in result:
        result["gc_56_33"] = result["ma56"] > result["ma33"]
    if "ma112" in result and "ma56" in result:
        result["gc_112_56"] = result["ma112"] > result["ma56"]

    # 이평선 배열
    if all(f"ma{p}" in result for p in [112, 224, 448]):
        m112, m224, m448 = result["ma112"], result["ma224"], result["ma448"]
        if m112 > m224 > m448:
            result["ma_arrangement"] = "BULLISH"
        elif m112 < m224 < m448:
            result["ma_arrangement"] = "BEARISH"
        else:
            result["ma_arrangement"] = "TRANSITIONING"

    # 거래량비율 (당일 vs 20일 평균)
    if len(volumes) >= 20:
        vol_avg20 = sum(volumes[:20]) / 20
        result["vol_ratio"] = volumes[0] / vol_avg20 * 100 if vol_avg20 > 0 else 0
        result["vol_today"] = volumes[0]
        result["vol_avg20"] = vol_avg20

    # 볼린저밴드 (20일)
    if len(closes) >= 20:
        bb = closes[:20]
        bbm = statistics.mean(bb)
        bbs = statistics.stdev(bb)
        result["bb_upper"] = bbm + 2 * bbs
        result["bb_mid"] = bbm
        result["bb_lower"] = bbm - 2 * bbs
        result["bb_width"] = (result["bb_upper"] - result["bb_lower"]) / bbm * 100

    # 일목균형표
    if len(data) >= 52:
        tenkan = (max(highs[:9]) + min(lows[:9])) / 2
        kijun = (max(highs[:26]) + min(lows[:26])) / 2
        senkou_a = (tenkan + kijun) / 2
        senkou_b = (max(highs[:52]) + min(lows[:52])) / 2
        cloud_top = max(senkou_a, senkou_b)
        cloud_bottom = min(senkou_a, senkou_b)
        result["ichimoku"] = {
            "tenkan": tenkan, "kijun": kijun,
            "senkou_a": senkou_a, "senkou_b": senkou_b,
            "cloud_top": cloud_top, "cloud_bottom": cloud_bottom
        }
        if closes[0] > cloud_top:
            result["cloud_position"] = "ABOVE"
        elif closes[0] < cloud_bottom:
            result["cloud_position"] = "BELOW"
        else:
            result["cloud_position"] = "INSIDE"

    # 세력봉 감지
    if len(data) >= 20:
        body_ratio = abs(closes[0] - opens[0]) / max(highs[0] - lows[0], 1)
        is_bullish = closes[0] > opens[0]
        vol_spike = result.get("vol_ratio", 0) > 200
        result["power_candle"] = is_bullish and body_ratio > 0.7 and vol_spike

    # 224일선 대비 위치
    if "ma224" in result:
        result["above_ma224"] = closes[0] > result["ma224"]
        result["ma224_dist"] = (closes[0] - result["ma224"]) / result["ma224"] * 100

    return result

# === 단테 스코어링 ===
def dante_score(ta):
    """단테 밥그릇 3번 자리 점수 (필수 6 + 우대 4)"""
    if ta is None:
        return {"mandatory": 0, "bonus": 0, "total": 0, "details": []}

    mandatory = 0
    optional = 0
    reasons = []

    # 필수 1: 이평선 역배열→수렴/정배열 전환
    arr = ta.get("ma_arrangement", "")
    if arr in ("TRANSITIONING", "BULLISH"):
        mandatory += 1
        reasons.append(f"이평선 {arr}")

    # 필수 2: 구름대 위 안착
    if ta.get("cloud_position") == "ABOVE":
        mandatory += 1
        reasons.append("구름대 위 안착")

    # 필수 3: 224일선 돌파/근접
    if ta.get("above_ma224"):
        mandatory += 1
        reasons.append(f"224일선 돌파 ({ta.get('ma224_dist',0):.1f}%)")
    elif ta.get("ma224_dist", -999) > -3:
        mandatory += 1
        reasons.append(f"224일선 근접 ({ta.get('ma224_dist',0):.1f}%)")

    # 필수 4: 거래량 150%+
    if ta.get("vol_ratio", 0) >= 150:
        mandatory += 1
        reasons.append(f"거래량 {ta.get('vol_ratio',0):.0f}%")

    # 필수 5: 골든크로스
    if ta.get("gc_56_33") or ta.get("gc_112_56"):
        mandatory += 1
        gc_type = "56>33" if ta.get("gc_56_33") else "112>56"
        reasons.append(f"GC {gc_type}")

    # 필수 6: 세력봉
    if ta.get("power_candle"):
        mandatory += 1
        reasons.append("세력봉 감지")

    # 우대 1: 볼밴 수렴 후 상단 돌파
    if ta.get("bb_width", 999) < 10 and ta.get("price", 0) > ta.get("bb_upper", 999999):
        optional += 1
        reasons.append("볼밴 수렴 돌파")

    # 우대 2: 구름대 상방 전환
    ichi = ta.get("ichimoku", {})
    if ichi.get("senkou_a", 0) > ichi.get("senkou_b", 0):
        optional += 1
        reasons.append("구름대 상방")

    return {"mandatory": mandatory, "bonus": optional, "total": mandatory * 2 + optional, "details": reasons}

# === 텔레그램 ===
def send_telegram(text):
    """텔레그램 메시지 전송 (재시도 포함)"""
    data = json.dumps({"chat_id": int(TELEGRAM_CHAT_ID), "text": text}).encode()
    _http_request(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
        headers={"Content-Type": "application/json"},
        data=data, method='POST')

def send_telegram_long(text):
    """긴 메시지 분할 전송 (4096자 제한)"""
    while text:
        chunk = text[:4096]
        # 중간 잘림 방지: 줄바꿈 기준으로 자르기
        if len(text) > 4096:
            last_nl = chunk.rfind('\n')
            if last_nl > 3000:
                chunk = text[:last_nl]
        send_telegram(chunk)
        text = text[len(chunk):].lstrip('\n')
        if text:
            time.sleep(0.5)

# === 포트폴리오 ===
def analyze_portfolio():
    """포트폴리오 전 종목 실시간 분석"""
    results = []
    for code, info in PORTFOLIO.items():
        try:
            price_data = get_price_naver(code)
            if 'error' in price_data:
                raise Exception(price_data['error'])
            
            cur_price = price_data['price']
            pnl_pct = (cur_price - info["avg"]) / info["avg"] * 100
            pnl_amt = (cur_price - info["avg"]) * info["qty"]
            
            results.append({
                "code": code,
                "name": info["name"],
                "qty": info["qty"],
                "avg": info["avg"],
                "cur_price": cur_price,
                "change_pct": price_data.get('change_pct', 0),
                "pnl_pct": pnl_pct,
                "pnl_amt": pnl_amt,
                "volume": price_data.get('volume', 0),
            })
            time.sleep(0.15)
        except Exception as e:
            results.append({"code": code, "name": info["name"], "error": str(e)})
    return results
