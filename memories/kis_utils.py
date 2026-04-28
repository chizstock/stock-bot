# === AUTH (한투 API, 해외 IP 대응) ===
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
    """한투 API 토큰 (파일 캐싱 + 재시도)"""
    now = time.time()
    if _token_cache["token"] and now < _token_cache["expires"]:
        return _token_cache["token"]

    file_token, file_expires = _load_token_from_file()
    if file_token and now < file_expires:
        _token_cache["token"] = file_token
        _token_cache["expires"] = file_expires
        return file_token

    # 신규 발급 (최대 3회 재시도, 충분한 대기)
    url = f"{BASE_URL}/oauth2/tokenP"
    body = json.dumps({
        "grant_type": "client_credentials",
        "appkey": APP_KEY,
        "appsecret": APP_SECRET
    }).encode()

    for attempt in range(3):
        try:
            print(f"  🔑 토큰 발급 시도 ({attempt+1}/3)...")
            result = _http_request(url,
                headers={"Content-Type": "application/json"},
                data=body, method='POST', timeout=30)

            if not result or 'access_token' not in result:
                print(f"  ❌ 토큰 응답 이상: {result}")
                time.sleep(5)
                continue

            token = result["access_token"]
            expires = now + 80000
            _token_cache["token"] = token
            _token_cache["expires"] = expires
            _save_token_to_file(token, expires)
            print(f"  ✅ 토큰 발급 성공")
            return token

        except Exception as e:
            print(f"  ❌ 토큰 발급 실패 ({attempt+1}/3): {e}")
            if attempt < 2:
                wait = 5 * (attempt + 1)
                print(f"  ⏳ {wait}초 대기 후 재시도...")
                time.sleep(wait)

    raise Exception("한투 API 토큰 발급 3회 실패")

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
        "Accept": "application/json",
    }

def _kis_get(path, tr_id, params, timeout=20):
    """한투 API GET (재시도 3회, 충분한 대기)"""
    url = f"{BASE_URL}{path}?{params}"
    hdrs = _kis_headers(tr_id)

    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers=hdrs)
            with urllib.request.urlopen(req, timeout=timeout, context=SSL_CTX) as resp:
                body = resp.read().decode('utf-8')
                result = json.loads(body)

                # API 에러 체크
                rt_cd = result.get('rt_cd', '')
                if rt_cd != '0':
                    msg = result.get('msg1', 'unknown error')
                    print(f"  ⚠️ API 응답 에러 (rt_cd={rt_cd}): {msg}")
                    if attempt < 2:
                        time.sleep(3 * (attempt + 1))
                        continue
                return result

        except Exception as e:
            print(f"  ❌ API 호출 실패 ({attempt+1}/3): {e}")
            if attempt < 2:
                wait = 3 * (attempt + 1)
                print(f"  ⏳ {wait}초 대기 후 재시도...")
                time.sleep(wait)
            else:
                raise

    return {"output": []}

# === 거래량 순위 (한투 API, 해외 IP 대응) ===
def _get_volume_rank_raw(market='J', price_min=0, price_max=0):
    """거래량순위 단일 조회 (최대 30건)"""
    path = "/uapi/domestic-stock/v1/quotations/volume-rank"
    params = (f"FID_COND_MRKT_DIV_CODE={market}"
              f"&FID_COND_SCR_DIV_CODE=20171"
              f"&FID_INPUT_ISCD=0000"
              f"&FID_DIV_CLS_CODE=0"
              f"&FID_BLNG_CLS_CODE=0"
              f"&FID_TRGT_CLS_CODE=111111111"
              f"&FID_TRGT_EXLS_CLS_CODE=000000"
              f"&FID_INPUT_PRICE_1={price_min}"
              f"&FID_INPUT_PRICE_2={price_max}"
              f"&FID_VOL_CNT=0"
              f"&FID_INPUT_DATE_1=")

    result = _kis_get(path, "FHKST130000C0", params)
    items = result.get("output", [])
    print(f"    가격대 {price_min:,}~{price_max:,}: {len(items)}건")
    return items

def get_volume_rank_top(market='J', count=100):
    """
    거래량 순위 상위 N개 (가격대 분할 조회)
    market: J=코스피, Q=코스닥

    가격대를 세분화하여 분할 조회 → 중복제거 → 거래량순 정렬
    각 구간 사이에 충분한 대기(3초)를 두어 차단 방지
    """
    market_name = "코스피" if market == 'J' else "코스닥"
    print(f"\n  📊 {market_name} 거래량 순위 조회 시작")

    # 가격대 세분화 (겹침 없이 7구간 → 최대 210건)
    if market == 'J':
        price_ranges = [
            (0, 3000),
            (3000, 10000),
            (10000, 30000),
            (30000, 70000),
            (70000, 150000),
            (150000, 500000),
            (500000, 0),        # 0 = 상한 없음
        ]
    else:
        price_ranges = [
            (0, 1000),
            (1000, 3000),
            (3000, 7000),
            (7000, 15000),
            (15000, 40000),
            (40000, 100000),
            (100000, 0),
        ]

    all_stocks = {}
    api_call_count = 0

    for p_min, p_max in price_ranges:
        try:
            # 호출 전 대기 (첫 호출 제외)
            if api_call_count > 0:
                print(f"    ⏳ 3초 대기...")
                time.sleep(3)

            items = _get_volume_rank_raw(market, p_min, p_max)
            api_call_count += 1

            for item in items:
                code = str(item.get('mksc_shrn_iscd', '')).strip()
                if not code or code in all_stocks:
                    continue

                vol_str = str(item.get('acml_vol', '0')).replace(',', '')
                price_str = str(item.get('stck_prpr', '0')).replace(',', '')
                name = str(item.get('hts_kor_isnm', '')).strip()

                all_stocks[code] = {
                    'code': code,
                    'name': name,
                    'volume': int(vol_str) if vol_str.isdigit() else 0,
                    'price': int(price_str) if price_str.isdigit() else 0,
                    'change_pct': float(str(item.get('prdy_ctrt', '0')).replace(',', '') or '0'),
                }

        except Exception as e:
            p_max_str = f"{p_max:,}" if p_max > 0 else "∞"
            print(f"  ❌ 구간 {p_min:,}~{p_max_str} 실패: {e}")
            print(f"    ⏳ 5초 대기 후 다음 구간 진행...")
            time.sleep(5)

    # 거래량순 정렬
    sorted_stocks = sorted(all_stocks.values(), key=lambda x: x['volume'], reverse=True)
    print(f"  ✅ {market_name} 총 {len(sorted_stocks)}개 종목 수집 완료")

    return sorted_stocks[:count]
