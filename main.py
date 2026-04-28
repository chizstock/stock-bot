#!/usr/bin/env python3
"""
주식 아침 브리핑 자동화 (GitHub Actions용)
"""
import os
import sys
import json
from datetime import datetime

# memories 폴더 경로 추가
sys.path.insert(0, 'memories')

# kis_utils에서 함수 임포트
from kis_utils import (
    get_price_naver,
    get_daily_chart_naver,
    calc_technical,
    dante_score,
    analyze_portfolio,
    send_telegram_long,
    PORTFOLIO
)

def get_market_summary():
    """시장 개요 조회"""
    kospi = get_price_naver('KOSPI')
    kosdaq = get_price_naver('KOSDAQ')
    
    lines = ["🌏 시장 개요\n"]
    
    if kospi:
        emoji = "🟢" if kospi['change'] > 0 else "🔴"
        lines.append(f"{emoji} 코스피: {kospi['price']:,} ({kospi['change']:+.2f}%)")
    
    if kosdaq:
        emoji = "🟢" if kosdaq['change'] > 0 else "🔴"
        lines.append(f"{emoji} 코스닥: {kosdaq['price']:,} ({kosdaq['change']:+.2f}%)")
    
    return "\n".join(lines)

def scan_dante_candidates():
    """단테 후보 스캔 (간단 버전)"""
    # 코스피 대형주 + 코스닥 성장주 샘플
    candidates = [
        # 코스피
        {'name': 'LG화학', 'code': '051910', 'type': '코스피'},
        {'name': '포스코퓨처엠', 'code': '003670', 'type': '코스피'},
        {'name': '신한지주', 'code': '055550', 'type': '코스피'},
        {'name': 'NAVER', 'code': '035420', 'type': '코스피'},
        {'name': '카카오', 'code': '035720', 'type': '코스피'},
        {'name': '삼성SDI', 'code': '006400', 'type': '코스피'},
        
        # 코스닥
        {'name': '에스티팜', 'code': '237690', 'type': '코스닥'},
        {'name': '잉글우드랩', 'code': '950140', 'type': '코스닥'},
        {'name': '네패스', 'code': '033640', 'type': '코스닥'},
        {'name': '한미반도체', 'code': '042700', 'type': '코스닥'},
    ]
    
    results = []
    
    print("단테 스코어링 중...")
    for i, stock in enumerate(candidates, 1):
        print(f"  {i}/{len(candidates)} {stock['name']} 분석 중...")
        
        ta = calc_technical(stock['code'], days=100)
        if not ta:
            continue
        
        score = dante_score(ta)
        if not score:
            continue
        
        # 필수 4점 이상만 선정
        if score['mandatory'] >= 4:
            results.append({
                'name': stock['name'],
                'code': stock['code'],
                'type': stock['type'],
                'price': ta['current'],
                'change': ta['change'],
                'score': score,
                'ma': ta['ma']
            })
    
    # 점수순 정렬
    results.sort(key=lambda x: x['score']['total'], reverse=True)
    return results[:6]  # TOP 6만 반환

def format_dante_recommendations(stocks):
    """단테 추천 종목 포맷팅"""
    if not stocks:
        return "🔍 단테 추천 종목: 없음 (적합한 종목 미발견)"
    
    lines = ["🔥 단테 추천 TOP 6\n"]
    
    for i, s in enumerate(stocks, 1):
        sc = s['score']
        price = s['price']
        ma224 = s['ma'].get('224', price * 0.9)
        
        # 진입가 계산
        entry_type = "A" if price > ma224 * 1.05 else "B"
        buy1 = int(price * 1.01)  # 1% 위
        buy2 = int(ma224 * 1.01) if ma224 else int(price * 0.95)
        stop = int(ma224 * 0.98) if ma224 else int(price * 0.90)
        
        emoji = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else "📌"
        
        lines.append(
            f"{emoji} {i}. {s['name']}({s['code']}) | {s['type']}\n"
            f"   현재가: {price:,}원 ({s['change']:+.2f}%)\n"
            f"   점수: 필수 {sc['mandatory']}/6 + 우대 {sc['bonus']}/4 = {sc['total']}\n"
            f"   진입{entry_type} | 1차매수: {buy1:,}원 | 2차매수: {buy2:,}원 | 손절: {stop:,}원"
        )
    
    return "\n\n".join(lines)

def main():
    """메인 실행"""
    now = datetime.now()
    date_str = now.strftime("%Y년 %m월 %d일")
    weekday = ["월", "화", "수", "목", "금", "토", "일"][now.weekday()]
    
    print(f"=" * 50)
    print(f"📈 아침 브리핑 생성: {date_str} ({weekday}요일)")
    print(f"=" * 50)
    
    # 1. 헤더
    header = f"📈 {date_str} ({weekday}요일) 아침 브리핑\n"
    
    # 2. 시장 개요
    print("시장 개요 조회 중...")
    market = get_market_summary()
    
    # 3. 포트폴리오
    print("포트폴리오 분석 중...")
    portfolio = analyze_portfolio()
    
    # 4. 단테 추천
    print("단테 스크리닝 중...")
    dante_stocks = scan_dante_candidates()
    dante = format_dante_recommendations(dante_stocks)
    
    # 5. 푸터
    footer = f"\n⏰ 생성시간: {now.strftime('%H:%M')}\n🤖 GitHub Actions 자동 실행"
    
    # 조합
    full_message = f"{header}\n{market}\n\n{portfolio}\n\n{dante}\n{footer}"
    
    # 6. 텔레그램 전송
    print("텔레그램 전송 중...")
    success = send_telegram_long(full_message)
    
    if success:
        print("✅ 브리핑 전송 완료!")
    else:
        print("❌ 브리핑 전송 실패")
        # 콘솔에 출력
        print("\n" + "=" * 50)
        print(full_message)
    
    return success

if __name__ == "__main__":
    main()
