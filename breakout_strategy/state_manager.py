"""
State Manager
포지션 및 주문 상태 스냅샷 저장/복구 모듈

프로그램 이상 종료 시 상태를 복구할 수 있도록
주기적으로 상태를 JSON 파일에 저장합니다.
"""

import json
import os
from datetime import datetime
from typing import Dict, Any, Optional, List
import logging
import pytz


class StateManager:
    """
    상태 관리 클래스

    저장되는 정보:
    - grid_center: 그리드 기준가
    - position: 포지션 정보 (direction, entries, avg_price, total_size 등)
    - pending_orders: 대기 중인 주문 목록
    - current_level: 현재 진입 레벨
    - last_updated: 마지막 업데이트 시간

    Usage:
        state_mgr = StateManager('state/state_btc.json')

        # 상태 저장
        state_mgr.save_state({
            'grid_center': 95000.0,
            'position': {...},
            'pending_orders': [...]
        })

        # 상태 복구
        state = state_mgr.load_state()
        if state:
            grid_center = state['grid_center']
    """

    def __init__(self, state_path: str, logger: Optional[logging.Logger] = None):
        """
        Args:
            state_path: 상태 파일 경로
            logger: 로거 (None이면 기본 로거 사용)
        """
        self.state_path = state_path
        self.logger = logger or logging.getLogger(__name__)

        # 디렉토리 생성
        os.makedirs(os.path.dirname(state_path), exist_ok=True)

    def save_state(self, state: Dict[str, Any]) -> bool:
        """
        상태 저장

        Args:
            state: 저장할 상태 딕셔너리

        Returns:
            성공 여부
        """
        try:
            # 타임스탬프 추가
            state['last_updated'] = datetime.now(pytz.UTC).isoformat()

            # 임시 파일에 먼저 쓰고 원자적으로 이동
            temp_path = self.state_path + '.tmp'
            with open(temp_path, 'w') as f:
                json.dump(state, f, indent=2, default=str)

            # 원자적 이동
            os.replace(temp_path, self.state_path)

            self.logger.debug(f"상태 저장 완료: {self.state_path}")
            return True

        except Exception as e:
            self.logger.error(f"상태 저장 실패: {e}")
            return False

    def load_state(self) -> Optional[Dict[str, Any]]:
        """
        상태 복구

        Returns:
            상태 딕셔너리 또는 None (파일 없음/오류)
        """
        try:
            if not os.path.exists(self.state_path):
                self.logger.info("상태 파일 없음 - 새로 시작")
                return None

            with open(self.state_path, 'r') as f:
                content = f.read()

            # 빈 파일 체크
            if not content.strip():
                self.logger.warning("상태 파일이 비어있음 - 새로 시작")
                return None

            state = json.loads(content)

            self.logger.info(f"상태 복구 완료: {state.get('last_updated', 'unknown')}")
            return state

        except json.JSONDecodeError as e:
            self.logger.error(f"상태 복구 실패 (JSON 파싱 오류): {e}")
            self.logger.error(f"파일 경로: {self.state_path}")
            # 손상된 파일 내용 일부 출력
            try:
                with open(self.state_path, 'r') as f:
                    preview = f.read(200)
                self.logger.error(f"파일 내용 미리보기: {repr(preview)}")
            except:
                pass
            return None
        except Exception as e:
            self.logger.error(f"상태 복구 실패: {e}")
            return None

    def clear_state(self) -> bool:
        """
        상태 초기화 (파일 삭제)

        Returns:
            성공 여부
        """
        try:
            if os.path.exists(self.state_path):
                os.remove(self.state_path)
                self.logger.info("상태 파일 삭제 완료")
            return True
        except Exception as e:
            self.logger.error(f"상태 파일 삭제 실패: {e}")
            return False


class PositionState:
    """
    포지션 상태 관리 헬퍼 클래스

    StateManager와 함께 사용하여 포지션 정보를 구조화
    """

    def __init__(self):
        self.reset()

    def reset(self):
        """포지션 초기화"""
        self.direction: Optional[str] = None  # 'LONG' or 'SHORT'
        self.entries: List[Dict] = []  # [(price, btc_amount), ...]
        self.avg_price: float = 0.0
        self.total_size: float = 0.0
        self.current_level: int = 0
        self.level_prices: List[Optional[float]] = [None, None, None, None]
        self.level1_btc_amount: float = 0.0
        self.entry_fees: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        """딕셔너리로 변환"""
        return {
            'direction': self.direction,
            'entries': self.entries,
            'avg_price': self.avg_price,
            'total_size': self.total_size,
            'current_level': self.current_level,
            'level_prices': self.level_prices,
            'level1_btc_amount': self.level1_btc_amount,
            'entry_fees': self.entry_fees
        }

    def from_dict(self, data: Dict[str, Any]):
        """딕셔너리에서 복구"""
        self.direction = data.get('direction')
        self.entries = data.get('entries', [])
        self.avg_price = data.get('avg_price', 0.0)
        self.total_size = data.get('total_size', 0.0)
        self.current_level = data.get('current_level', 0)
        self.level_prices = data.get('level_prices', [None, None, None, None])
        self.level1_btc_amount = data.get('level1_btc_amount', 0.0)
        self.entry_fees = data.get('entry_fees', 0.0)

    def has_position(self) -> bool:
        """포지션 존재 여부"""
        return self.direction is not None and self.total_size > 0

    def add_entry(self, price: float, btc_amount: float, level: int):
        """진입 추가"""
        self.entries.append({'price': price, 'btc_amount': btc_amount, 'level': level})
        self.total_size += btc_amount
        self.level_prices[level] = price

        if level == 0:
            self.level1_btc_amount = btc_amount

        self.current_level = level + 1
        self._recalculate_avg_price()

    def _recalculate_avg_price(self):
        """평균 진입가 재계산"""
        if self.total_size == 0:
            self.avg_price = 0.0
            return

        total_value = sum(e['price'] * e['btc_amount'] for e in self.entries)
        self.avg_price = total_value / self.total_size


class OrderState:
    """
    주문 상태 관리 헬퍼 클래스
    """

    def __init__(self):
        self.pending_entry_orders: List[Dict] = []  # 진입 지정가 주문
        self.tp_order: Optional[Dict] = None  # 익절 주문
        self.be_order: Optional[Dict] = None  # 본절 주문
        self.sl_order: Optional[Dict] = None  # 손절 주문

    def to_dict(self) -> Dict[str, Any]:
        """딕셔너리로 변환"""
        return {
            'pending_entry_orders': self.pending_entry_orders,
            'tp_order': self.tp_order,
            'be_order': self.be_order,
            'sl_order': self.sl_order
        }

    def from_dict(self, data: Dict[str, Any]):
        """딕셔너리에서 복구"""
        self.pending_entry_orders = data.get('pending_entry_orders', [])
        self.tp_order = data.get('tp_order')
        self.be_order = data.get('be_order')
        self.sl_order = data.get('sl_order')

    def clear_all(self):
        """모든 주문 정보 초기화"""
        self.pending_entry_orders = []
        self.tp_order = None
        self.be_order = None
        self.sl_order = None

    def add_entry_order(self, order_id: str, level: int, price: float, quantity: float):
        """진입 주문 추가"""
        self.pending_entry_orders.append({
            'order_id': order_id,
            'level': level,
            'price': price,
            'quantity': quantity
        })

    def remove_entry_order(self, level: int):
        """진입 주문 제거 (체결 시)"""
        self.pending_entry_orders = [
            o for o in self.pending_entry_orders if o['level'] != level
        ]

    def set_tp_order(self, order_id: str, price: float, quantity: float):
        """익절 주문 설정"""
        self.tp_order = {
            'order_id': order_id,
            'price': price,
            'quantity': quantity
        }

    def set_be_order(self, order_id: str, price: float, quantity: float):
        """본절 주문 설정"""
        self.be_order = {
            'order_id': order_id,
            'price': price,
            'quantity': quantity
        }

    def set_sl_order(self, order_id: str, price: float):
        """손절 주문 설정"""
        self.sl_order = {
            'order_id': order_id,
            'price': price
        }
