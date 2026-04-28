"""
한국투자증권 Open API + 기술적 분석 유틸리티
GitHub Actions용 환경변수 지원
"""
import urllib.request
import urllib.parse
import json
import os
import datetime
import statistics
import time

# 환경변수에서 API 키 읽기 (GitHub Actions용)
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '')
APP_KEY = os.environ.get('KIS_APP_KEY', '')
APP_SECRET = os.environ.get('KIS_APP_SECRET', '')
ACCOUNT_NO = os.environ.get('KIS_ACCOUNT', '')

BASE_URL = "https://openapi.koreainvestment.com:9443"

# ============ 토큰 관리 ============
def get_access_token():
    """한투 API 액세스 토큰 발급"""
    url = f"{BASE_URL}/oauth2/tokenP"
    headers = {"Content-Type": "application/json"}
    body = {
        "grant_type": "client_credentials",
        "appkey": APP_KEY,
        "appsecret": APP_SECRET
    }
    
    req = urllib.request.Request(
        url, 
        data=json.dumps(body).encode('utf-8'),
        headers=headers,
        method='POST'
    )
    
    try:
        with urllib.request.urlopen(req, timeout=10) as res:
            data = json.loads(res.read().decode('utf-8'))
            return data.get('access_token')
    except Exception as e:
        print(f"토큰 발급 실패: {e}")
        return None

# ============ 네이버 API (무료, 무제한) ============
def get_price_naver(code):
    """네이버에서 현재가 조회"""
    try:
        url = f"https://m.stock.naver.com/api/stock/{code}/basic"
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.0"
        })
        
        with urllib.request.urlopen(req, timeout=10) as res:
            data = json.loads(res.read().decode('utf-8'))
            return {
                'code': code,
                'name': data.get('stockName', ''),
                'price': int(data.get('closePrice', '0').replace(',', '')),
                'change': float(data.get('fluctuationsRatio', 0)),
                'volume': int(data.get('accumulatedTradingVolume', '0').replace(',', ''))
            }
    except Exception as e:
        print(f"네이버 시세 오류 ({code}): {e}")
        return None

def get_daily_chart_naver(code, days=500):
    """네이버에서 일봉 데이터 조회"""
    try:
        end_date = datetime.datetime.now()
        start_date = end_date - datetime.timedelta(days=days + 100)
        
        url = f"https://m.stock.naver.com/api/stock/{code}/price"
        url += f"?startDate={start_date.strftime('%Y%m%d')}"
        url += f"&endDate={end_date.strftime('%Y%m%d')}"
        
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.0"
        })
        
        with urllib.request.urlopen(req, timeout=10) as res:
            data = json.loads(res.read().decode('utf-8'))
            chart = data.get('result', {}).get('chart', [])
            
            ohlcv = []
            for item in chart:
                ohlcv.append({
                    'date': item.get('localTradedAt', ''),
                    'open': int(item.get('openPrice', 0)),
                    'high': int(item.get('highPrice', 0)),
                    'low': int(item.get('lowPrice', 0)),
                    'close': int(item.get('closePrice', 0)),
                    'volume': int(item.get('accumulatedTradingVolume', 0))
                })
            return ohlcv[-days:] if len(ohlcv) > days else ohlcv
            
    except Exception as e:
        print(f"네이버 차트 오류 ({code}): {e}")
        return []

# ============ 기술적 분석 ============
def calc_ma(data, period):
    """이동평균 계산"""
    if len(data) < period:
        return None
    return statistics.mean([d['close'] for d in data[-period:]])

def calc_technical(code, days=500):
    """종합 기술적 분석"""
    chart = get_daily_chart_naver(code, days)
    if not chart or len(chart) < 60:
        return None
    
    current = chart[-1]
    prev = chart[-2] if len(chart) > 1 else current
    
    # 이평선
    ma5 = calc_ma(chart, 5)
    ma20 = calc_ma(chart, 20)
    ma33 = calc_ma(chart, 33)
    ma56 = calc_ma(chart, 56)
    ma112 = calc_ma(chart, 112)
    ma224 = calc_ma(chart, 224)
    
    # 볼린저밴드 (20일)
    closes = [d['close'] for d in chart[-20:]]
    bb_mid = statistics.mean(closes)
    bb_std = statistics.stdev(closes) if len(closes) > 1 else 0
    bb_upper = bb_mid + 2 * bb_std
    bb_lower = bb_mid - 2 * bb_std
    
    # 거래량 분석
    vol_avg = statistics.mean([d['volume'] for d in chart[-20:]])
    vol_ratio = current['volume'] / vol_avg if vol_avg > 0 else 1
    
    return {
        'code': code,
        'current': current['close'],
        'change': round((current['close'] - prev['close']) / prev['close'] * 100, 2),
        'ma': {'5': ma5, '20': ma20, '33': ma33, '56': ma56, '112': ma112, '224': ma224},
        'bb': {'upper': bb_upper, 'mid': bb_mid, 'lower': bb_lower},
        'volume_ratio': round(vol_ratio, 2),
        'chart': chart
    }

# ============ 단테 스코어링 ============
def dante_score(ta):
    """단테 밥그릇 전략 스코어링"""
    if not ta:
        return None
    
    score = {'mandatory': 0, 'bonus': 0, 'details': []}
    price = ta['current']
    ma = ta['ma']
    
    # 필수 조건 (6개)
    # 1. 224일선 위
    if ma['224'] and price > ma['224']:
        score['mandatory'] += 1
        score['details'].append('✓ 224일선 위')
    else:
        score['details'].append('✗ 224일선 아래')
    
    # 2. 112 > 56 > 33 정배열
    if ma['112'] and ma['56'] and ma['33']:
        if ma['112'] > ma['56'] > ma['33']:
            score['mandatory'] += 1
            score['details'].append('✓ 이평선 정배열')
        else:
            score['details'].append('✗ 이평선 역배열')
    
    # 3. 5 > 20 (단기 정배열)
    if ma['5'] and ma['20']:
        if ma['5'] > ma['20']:
            score['mandatory'] += 1
            score['details'].append('✓ 단기 정배열')
        else:
            score['details'].append('✗ 단기 역배열')
    
    # 4. 볼린저밴드 중간 이상
    if price > ta['bb']['mid']:
        score['mandatory'] += 1
        score['details'].append('✓ 볼린저 중간 이상')
    else:
        score['details'].append('✗ 볼린저 중간 아래')
    
    # 5. 거래량 증가
    if ta['volume_ratio'] > 1.5:
        score['mandatory'] += 1
        score['details'].append(f'✓ 거래량 증가 ({ta["volume_ratio"]:.1f}배)')
    else:
        score['details'].append(f'✗ 거래량 부족 ({ta["volume_ratio"]:.1f}배)')
    
    # 6. 양봉 또는 전일 대비 상승
    if ta['change'] > 0:
        score['mandatory'] += 1
        score['details'].append(f'✓ 당일 상승 ({ta["change"]:+.2f}%)')
    else:
        score['details'].append(f'✗ 당일 하 ({ta["change"]:+.2f}%)')
    
    # 우대 조건 (4개)
    # 1. 5 > 33 (골든크로스)
    if ma['5'] and ma['33'] and ma['5'] > ma['33']:
        score['bonus'] += 1
        score['details'].append('★ 5>33 GC')
    
    # 2. 56 > 33 (중기 GC)
    if ma['56'] and ma['33'] and ma['56'] > ma['33']:
        score['bonus'] += 1
        score['details'].append('★ 56>33 GC')
    
    # 3. 거래량 2배 이상
    if ta['volume_ratio'] > 2:
        score['bonus'] += 1
        score['details'].append(f'★ 거래량 폭발 ({ta["volume_ratio"]:.1f}배)')
    
    # 4. 224일선 대비 10% 이내 (진입 적기)
    if ma['224']:
        gap = (price - ma['224']) / ma['224'] * 100
        if 0 < gap < 15:
            score['bonus'] += 1
            score['details'].append(f'★ 224선 근접 ({gap:.1f}%)')
    
    score['total'] = score['mandatory'] + score['bonus']
    return score

# ============ 포트폴리오 ============
PORTFOLIO = [
    {'name': '두산에너빌리티', 'code': '034020', 'qty': 416, 'avg': 100441},
    {'name': '삼성전자', 'code': '005930', 'qty': 151, 'avg': 200301},
    {'name': '에코프로비엠', 'code': '247540', 'qty': 27, 'avg': 308555},
    {'name': '에스피소프트', 'code': '407820', 'qty': 200, 'avg': 6070},
    {'name': '인투셀', 'code': '456570', 'qty': 84, 'avg': 38450},
    {'name': '하나금융지주', 'code': '086790', 'qty': 70, 'avg': 117657},
    {'name': '현대로템', 'code': '079160', 'qty': 33, 'avg': 166600},
    {'name': '현대차', 'code': '005380', 'qty': 10, 'avg': 516500},
    {'name': 'KB금융', 'code': '105560', 'qty': 101, 'avg': 157692},
    {'name': 'LG', 'code': '003550', 'qty': 51, 'avg': 98625},
    {'name': 'LX인터내셔널', 'code': '001120', 'qty': 480, 'avg': 41401},
    {'name': 'NICE인프라', 'code': '063570', 'qty': 300, 'avg': 4550},
    {'name': 'POSCO홀딩스', 'code': '005490', 'qty': 15, 'avg': 543800},
    {'name': 'SK하이닉스', 'code': '000660', 'qty': 30, 'avg': 984583},
]

def analyze_portfolio():
    """포트폴리오 분석"""
    lines = ["📊 포트폴리오 현황\n"]
    total_invested = 0
    total_value = 0
    
    for item in PORTFOLIO:
        info = get_price_naver(item['code'])
        if not info:
            lines.append(f"⚠️ {item['name']}: 조회 실패")
            continue
        
        current = info['price']
        qty = item['qty']
        avg = item['avg']
        
        invested = avg * qty
        value = current * qty
        profit = value - invested
        profit_pct = (current - avg) / avg * 100
        
        total_invested += invested
        total_value += value
        
        emoji = "🟢" if profit > 0 else "🔴" if profit < 0 else "⚪"
        lines.append(
            f"{emoji} {item['name']}: {current:,}원 ({info['change']:+.2f}%) | "
            f"수익률 {profit_pct:+.1f}%"
        )
    
    total_profit = total_value - total_invested
    total_profit_pct = total_profit / total_invested * 100 if total_invested > 0 else 0
    
    lines.append(f"\n💰 총 평가: {total_value:,}원")
    lines.append(f"📈 총 수익: {total_profit:,}원 ({total_profit_pct:+.1f}%)")
    
    return "\n".join(lines)

# ============ 텔레그램 ============
def send_telegram(message):
    """텔레그램 메시지 전송"""
    if not TELEGRAM_BOT_TOKEN:
        print("텔레그램 토큰 없음")
        return False
    
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    chat_id = "6006891840"  # 사용자 채팅 ID
    
    data = {
        'chat_id': chat_id,
        'text': message,
        'parse_mode': 'HTML'
    }
    
    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(data).encode('utf-8'),
            headers={'Content-Type': 'application/json'},
            method='POST'
        )
        
        with urllib.request.urlopen(req, timeout=10) as res:
            result = json.loads(res.read().decode('utf-8'))
            return result.get('ok', False)
    except Exception as e:
        print(f"텔레그램 전송 실패: {e}")
        return False

def send_telegram_long(message):
    """긴 메시지 분할 전송"""
    MAX_LEN = 4000
    
    if len(message) <= MAX_LEN:
        return send_telegram(message)
    
    # 분할 전송
    parts = []
    while len(message) > MAX_LEN:
        split_point = message.rfind('\n', 0, MAX_LEN)
        if split_point == -1:
            split_point = MAX_LEN
        parts.append(message[:split_point])
        message = message[split_point:].lstrip()
    parts.append(message)
    
    for i, part in enumerate(parts, 1):
        header = f"📄 ({i}/{len(parts)})\n" if len(parts) > 1 else ""
        send_telegram(header + part)
        time.sleep(0.5)
    
    return True
