#!/usr/bin/env python3
"""
Grid Martingale 모니터링 & 텔레그램 알림

감지 항목:
1. 포지션 있는데 TP/BE 주문 없음
2. 프로세스(trade_btc.py, trade_eth.py, trade_btc_usdt.py, trade_eth_usdt.py) OFF 상태

실행: python scripts/monitor_alert.py
"""

import asyncio
import json
import os
import subprocess
import sys
import urllib.request
import urllib.parse
from datetime import datetime, timedelta
from pathlib import Path

# 경로 설정
SCRIPT_DIR = Path(__file__).parent
PROJECT_DIR = SCRIPT_DIR.parent
STATE_DIR = PROJECT_DIR / 'state'

# 텔레그램 설정
TELEGRAM_BOT_TOKEN = '8084981809:AAF1MV_omet1l2PeK8KObpS5qyuZe_og3bg'
TELEGRAM_CHAT_ID = '8084935783'

# 모니터링 설정
CHECK_INTERVAL = 60  # 체크 주기 (초)
ALERT_COOLDOWN = 300  # 같은 알림 재발송 방지 (초)

# 알림 쿨다운 추적
last_alerts = {}


def send_telegram(message: str):
    """텔레그램 메시지 전송 (동기)"""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

    try:
        data = urllib.parse.urlencode({
            'chat_id': TELEGRAM_CHAT_ID,
            'text': message,
            'parse_mode': 'HTML'
        }).encode('utf-8')

        req = urllib.request.Request(url, data=data, method='POST')
        with urllib.request.urlopen(req, timeout=10) as response:
            if response.status == 200:
                print(f"[{datetime.now()}] 텔레그램 전송 성공")
            else:
                print(f"[{datetime.now()}] 텔레그램 전송 실패: {response.status}")
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
    send_telegram("🟢 <b>Grid Martingale 모니터링 시작</b>\n\n감지 항목:\n• 포지션 있는데 TP/BE 주문 없음\n• 프로세스 OFF 상태\n\n모니터링 대상:\n• BTCUSDC, ETHUSDC\n• BTCUSDT, ETHUSDT")

    # 모니터링 대상 정의
    targets = [
        {'name': 'BTCUSDC', 'process': 'trade_btc.py', 'state_key': 'btc'},
        {'name': 'ETHUSDC', 'process': 'trade_eth.py', 'state_key': 'eth'},
        {'name': 'BTCUSDT', 'process': 'trade_btc_usdt.py', 'state_key': 'btc_usdt'},
        {'name': 'ETHUSDT', 'process': 'trade_eth_usdt.py', 'state_key': 'eth_usdt'},
    ]

    while True:
        try:
            alerts = []
            status_parts = []

            for target in targets:
                name = target['name']
                process = target['process']
                state_key = target['state_key']

                # 1. 프로세스 상태 체크
                is_running = check_process_running(process)

                if not is_running:
                    alert_key = f'{state_key}_process_off'
                    if should_alert(alert_key):
                        alerts.append(f"🔴 <b>[{name}] 프로세스 OFF!</b>\n{process}가 실행되지 않고 있습니다.")

                # 2. 상태 파일 체크 (프로세스가 켜져있을 때만)
                if is_running:
                    state = load_state(state_key)
                    issues = check_order_status(state, name)
                    for issue in issues:
                        alert_key = f'{state_key}_order_{issue}'
                        if should_alert(alert_key):
                            alerts.append(issue)

                status_parts.append(f"{name}: {'🟢' if is_running else '🔴'}")

            # 알림 전송
            for alert in alerts:
                send_telegram(alert)

            # 상태 로그
            status = " | ".join(status_parts)
            print(f"[{datetime.now()}] {status}")

        except Exception as e:
            print(f"[{datetime.now()}] 모니터링 에러: {e}")

        await asyncio.sleep(CHECK_INTERVAL)


def main():
    """메인 함수"""
    try:
        asyncio.run(monitor_loop())
    except KeyboardInterrupt:
        print("\n모니터링 종료")
        send_telegram("🔴 <b>Grid Martingale 모니터링 종료</b>")


if __name__ == "__main__":
    main()
