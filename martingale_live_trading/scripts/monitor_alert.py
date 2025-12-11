#!/usr/bin/env python3
"""
Grid Martingale 모니터링 & 텔레그램 알림

감지 항목:
1. 포지션 있는데 TP/BE 주문 없음
2. 프로세스(trade_btc.py, trade_eth.py) OFF 상태

실행: python scripts/monitor_alert.py
"""

import asyncio
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
import httpx
from dotenv import load_dotenv

# 경로 설정
SCRIPT_DIR = Path(__file__).parent
PROJECT_DIR = SCRIPT_DIR.parent
STATE_DIR = PROJECT_DIR / 'state'

# 환경변수 로드
load_dotenv(PROJECT_DIR / '.env')

# 텔레그램 설정
TELEGRAM_BOT_TOKEN = '8084981809:AAF1MV_omet1l2PeK8KObpS5qyuZe_og3bg'
TELEGRAM_CHAT_ID = '8084935783'

# 모니터링 설정
CHECK_INTERVAL = 60  # 체크 주기 (초)
ALERT_COOLDOWN = 300  # 같은 알림 재발송 방지 (초)

# 알림 쿨다운 추적
last_alerts = {}


async def send_telegram(message: str):
    """텔레그램 메시지 전송"""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(url, data={
                'chat_id': TELEGRAM_CHAT_ID,
                'text': message,
                'parse_mode': 'HTML'
            })
            if response.status_code == 200:
                print(f"[{datetime.now()}] 텔레그램 전송 성공")
            else:
                print(f"[{datetime.now()}] 텔레그램 전송 실패: {response.text}")
        except Exception as e:
            print(f"[{datetime.now()}] 텔레그램 전송 에러: {e}")


def should_alert(alert_key: str) -> bool:
    """쿨다운 체크 - 같은 알림 반복 방지"""
    now = datetime.now()
    if alert_key in last_alerts:
        if now - last_alerts[alert_key] < timedelta(seconds=ALERT_COOLDOWN):
            return False
    last_alerts[alert_key] = now
    return True


def check_process_running(process_name: str) -> bool:
    """프로세스 실행 중인지 확인"""
    try:
        result = subprocess.run(
            ['pgrep', '-f', process_name],
            capture_output=True,
            text=True
        )
        return result.returncode == 0
    except Exception:
        return False


def load_state(symbol: str) -> dict:
    """상태 파일 로드"""
    state_file = STATE_DIR / f'state_{symbol}.json'
    if not state_file.exists():
        return None

    try:
        with open(state_file, 'r') as f:
            return json.load(f)
    except Exception as e:
        print(f"상태 파일 로드 실패 ({symbol}): {e}")
        return None


def check_order_status(state: dict, symbol: str) -> list:
    """
    포지션이 있는데 TP/BE 주문이 없는지 확인

    Returns:
        문제 목록
    """
    issues = []

    if not state:
        return issues

    position = state.get('position')
    orders = state.get('orders', {})

    if not position:
        return issues

    current_level = position.get('current_level', 0)
    has_position = position.get('total_size', 0) > 0

    if not has_position:
        return issues

    # Level 1: TP 주문 필요
    if current_level == 1:
        if not orders.get('tp_order'):
            issues.append(f"⚠️ [{symbol.upper()}] Level 1 포지션인데 TP 주문 없음!")

    # Level 2+: BE 주문 필요
    elif current_level >= 2:
        if not orders.get('be_order'):
            issues.append(f"⚠️ [{symbol.upper()}] Level {current_level} 포지션인데 BE 주문 없음!")

    return issues


async def monitor_loop():
    """메인 모니터링 루프"""
    print(f"[{datetime.now()}] Grid Martingale 모니터링 시작")
    print(f"체크 주기: {CHECK_INTERVAL}초, 알림 쿨다운: {ALERT_COOLDOWN}초")
    print("-" * 50)

    # 시작 알림
    await send_telegram("🟢 <b>Grid Martingale 모니터링 시작</b>\n\n감지 항목:\n• 포지션 있는데 TP/BE 주문 없음\n• 프로세스 OFF 상태")

    while True:
        try:
            alerts = []

            # 1. 프로세스 상태 체크
            btc_running = check_process_running('trade_btc.py')
            eth_running = check_process_running('trade_eth.py')

            if not btc_running:
                alert_key = 'btc_process_off'
                if should_alert(alert_key):
                    alerts.append("🔴 <b>[BTC] 프로세스 OFF!</b>\ntrade_btc.py가 실행되지 않고 있습니다.")

            if not eth_running:
                alert_key = 'eth_process_off'
                if should_alert(alert_key):
                    alerts.append("🔴 <b>[ETH] 프로세스 OFF!</b>\ntrade_eth.py가 실행되지 않고 있습니다.")

            # 2. 상태 파일 체크 (프로세스가 켜져있을 때만)
            if btc_running:
                btc_state = load_state('btc')
                btc_issues = check_order_status(btc_state, 'btc')
                for issue in btc_issues:
                    alert_key = f'btc_order_{issue}'
                    if should_alert(alert_key):
                        alerts.append(issue)

            if eth_running:
                eth_state = load_state('eth')
                eth_issues = check_order_status(eth_state, 'eth')
                for issue in eth_issues:
                    alert_key = f'eth_order_{issue}'
                    if should_alert(alert_key):
                        alerts.append(issue)

            # 알림 전송
            for alert in alerts:
                await send_telegram(alert)

            # 상태 로그
            status = f"BTC: {'🟢' if btc_running else '🔴'} | ETH: {'🟢' if eth_running else '🔴'}"
            print(f"[{datetime.now()}] {status}")

        except Exception as e:
            print(f"[{datetime.now()}] 모니터링 에러: {e}")

        await asyncio.sleep(CHECK_INTERVAL)


async def main():
    """메인 함수"""
    try:
        await monitor_loop()
    except KeyboardInterrupt:
        print("\n모니터링 종료")
        await send_telegram("🔴 <b>Grid Martingale 모니터링 종료</b>")


if __name__ == "__main__":
    asyncio.run(main())
