#!/usr/bin/env python3
"""
주식 아침 브리핑 (GitHub Actions용)
한투 API 거래량 TOP100 → 네이버 차트 → 단테 스코어링
"""
import sys, time
from datetime import datetime

sys.path.insert(0, 'memories')

from kis_utils import (
    get_volume_rank_top,
    get_price_naver,
    calc_technical,
    dante_score,
    analyze_portfolio,
    send_telegram_long,
)

def get_scan_candidates():
    """한투 API에서 코스피/코스닥 각 거래량 TOP 100 추출"""
    print("=" * 50)
    print("[1/4] 한투 API 거래량 순위 조회")
    print("=" * 50)

    kospi = get_volume_rank_top(market='J', count=100)
    print(f"\n  코스피: {len(kospi)}개 추출 완료")

    print(f"\n  ⏳ 5초 대기 (API 안정화)...")
    time.sleep(5)

    kosdaq = get_volume_rank_top(market='Q', count=100)
    print(f"\n  코스닥: {len(kosdaq)}개 추출 완료")

    if len(kospi) == 0 and len(kosdaq) == 0:
        print("\n  ❌ 한투 API에서 종목을 가져오지 못했습니다.")
        print("  가능한 원인:")
        print("    1. 해외 IP 차단")
        print("    2. API 키/시크릿 오류 → GitHub Secrets 확인")
        print("    3. 장 시작 전 데이터 미갱신")

    return kospi, kosdaq

def scan_dante(candidates, market_name):
    """단테 스코어링"""
    results = []
    total = len(candidates)

    for i, stock in enumerate(candidates, 1):
        code = stock['code']
        name = stock['name']

        if i % 20 == 0 or i == 1:
            print(f"  [{market_name}] {i}/{total} 분석 중...")

        try:
            ta = calc_technical(code, days=500)
            if not ta:
                continue

            score = dante_score(ta)

            if score['mandatory'] >= 3:
                results.append({
                    'name': name, 'code': code,
                    'price': ta['price'],
                    'change_pct': stock.get('change_pct', 0),
                    'volume': stock.get('volume', 0),
                    'score': score, 'ta': ta,
                })
            time.sleep(0.15)
        except:
            pass

    results.sort(key=lambda x: x['score']['total'], reverse=True)
    return results

def format_portfolio(data):
    """포트폴리오 텍스트"""
    lines = []
    total_invested = 0
    total_value = 0

    for p in data:
        if 'error' in p:
            lines.append(f"⚠️ {p['name']}: 조회 실패")
            continue
        invested = p['avg'] * p['qty']
        value = p['cur_price'] * p['qty']
        total_invested += invested
        total_value += value
        emoji = "🟢" if p['pnl_pct'] > 0 else "🔴" if p['pnl_pct'] < 0 else "⚪"
        lines.append(
            f"{emoji} {p['name']}: {p['cur_price']:,}원 ({p['change_pct']:+.2f}%) "
            f"| 수익률 {p['pnl_pct']:+.1f}%"
        )

    if total_invested > 0:
        total_pnl = (total_value - total_invested) / total_invested * 100
        lines.append(f"\n💰 총 평가: {total_value:,.0f}원 ({total_pnl:+.1f}%)")
    return "\n".join(lines)

def format_dante_top3(results, market_name):
    """단테 TOP3 텍스트"""
    top3 = results[:3]
    if not top3:
        return f"📭 {market_name}: 필수 3점 이상 종목 없음"

    emojis = ["1️⃣", "2️⃣", "3️⃣"]
    lines = []

    for i, item in enumerate(top3):
        s = item['score']
        price = item['price']
        ta = item.get('ta', {})
        ma224 = ta.get('ma224', price * 0.9)

        entry = "A" if ta.get('ma224_dist', 0) > 5 else "B"
        buy1 = int(price * 1.01)
        stop = int(ma224 * 0.98) if ma224 else int(price * 0.92)
        r_value = max(buy1 - stop, 1)
        buy2 = stop + int(r_value * 0.3)
        target1 = buy1 + r_value * 2
        target2 = buy1 + r_value * 3
        details = ", ".join(s['details'][:4])

        lines.append(
            f"{emojis[i]} {item['name']}({item['code']})\n"
            f"   현재: {price:,}원 ({item['change_pct']:+.2f}%) "
            f"| 필수 {s['mandatory']}/6 우대 {s['bonus']}/4\n"
            f"   진입{entry} | 1차: {buy1:,}(30%) | 2차: {buy2:,}(70%)\n"
            f"   손절: {stop:,} | 1차익절: {int(target1):,} | 2차익절: {int(target2):,}\n"
            f"   📋 {details}"
        )
    return "\n\n".join(lines)

def main():
    now = datetime.now()
    date_str = now.strftime("%Y년 %m월 %d일")
    weekday = ["월", "화", "수", "목", "금", "토", "일"][now.weekday()]

    print(f"\n{'='*50}")
    print(f"📈 아침 브리핑: {date_str} ({weekday}요일)")
    print(f"{'='*50}")

    # 1. 거래량 TOP 100 (한투 API)
    kospi_cand, kosdaq_cand = get_scan_candidates()

    # 2. 포트폴리오 (네이버)
    print(f"\n{'='*50}")
    print("[2/4] 포트폴리오 분석")
    print("=" * 50)
    portfolio_data = analyze_portfolio()
    portfolio_text = format_portfolio(portfolio_data)

    # 3. 단테 스캔 (네이버 차트)
    print(f"\n{'='*50}")
    print(f"[3/4] 단테 스크리닝")
    print("=" * 50)

    print(f"  코스피 {len(kospi_cand)}개 스캔...")
    kospi_results = scan_dante(kospi_cand, "코스피")
    print(f"  → 코스피 후보: {len(kospi_results)}개")

    print(f"\n  코스닥 {len(kosdaq_cand)}개 스캔...")
    kosdaq_results = scan_dante(kosdaq_cand, "코스닥")
    print(f"  → 코스닥 후보: {len(kosdaq_results)}개")

    kospi_top = format_dante_top3(kospi_results, "코스피")
    kosdaq_top = format_dante_top3(kosdaq_results, "코스닥")

    # 4. 메시지 조합
    scan_info = f"코스피 {len(kospi_cand)}개 + 코스닥 {len(kosdaq_cand)}개"

    msg = f"""📈 {date_str} ({weekday}요일) 아침 브리핑

💼 포트폴리오 (14종목)
{'─'*30}
{portfolio_text}

🔵 코스피 TOP3 (단테 점수순)
{'─'*30}
{kospi_top}

🟢 코스닥 TOP3 (단테 점수순)
{'─'*30}
{kosdaq_top}

📊 스캔: 거래량 상위 {scan_info}
⏰ {now.strftime('%H:%M')} | 🤖 GitHub Actions"""

    # 5. 전송
    print(f"\n{'='*50}")
    print(f"[4/4] 텔레그램 전송 ({len(msg)}자)")
    print("=" * 50)
    send_telegram_long(msg)
    print("✅ 전송 완료!")

if __name__ == "__main__":
    main()
