"""
Hyper Scalper V2 Strategy Configuration
동적 파라미터 로딩 지원

파라미터 파일(config_hyper.txt)을 주기적으로 읽어
프로그램 실행 중에도 설정 변경을 반영합니다.
"""

import os
from dotenv import load_dotenv
from typing import Dict, Any, List
import logging

# Load environment variables from .env file
load_dotenv()


class DynamicConfig:
    """
    동적 파라미터 로딩을 지원하는 설정 클래스

    Usage:
        config = DynamicConfig('hyper')  # config_hyper.txt 사용
        config.reload()  # 파일에서 다시 로드

        risk = config.get('RISK_PER_TRADE', 0.07)
        adx_threshold = config.get('ADX_THRESHOLD', 30.0)
    """

    def __init__(self, symbol_type: str, config_dir: str = None):
        """
        Args:
            symbol_type: 'hyper' (Hyper Scalper V2)
            config_dir: 설정 파일 디렉토리 (None이면 현재 디렉토리)
        """
        self.symbol_type = symbol_type.lower()
        self.config_dir = config_dir or os.path.dirname(os.path.abspath(__file__))
        self.config_file = os.path.join(self.config_dir, f'config_{self.symbol_type}.txt')
        self._params: Dict[str, str] = {}
        self._last_modified = 0

        # 초기 로드
        self.reload()

    def reload(self) -> bool:
        """
        설정 파일 다시 로드

        Returns:
            파일이 변경되어 다시 로드했으면 True
        """
        try:
            # 파일 수정 시간 확인
            mtime = os.path.getmtime(self.config_file)
            if mtime == self._last_modified:
                return False

            self._last_modified = mtime
            self._params = {}

            with open(self.config_file, 'r') as f:
                for line in f:
                    line = line.strip()
                    # 주석과 빈 줄 무시
                    if not line or line.startswith('#'):
                        continue

                    if '=' in line:
                        key, value = line.split('=', 1)
                        self._params[key.strip()] = value.strip()

            return True

        except Exception as e:
            logging.error(f"설정 파일 로드 실패: {e}")
            return False

    def get(self, key: str, default: Any = None) -> Any:
        """
        설정값 가져오기 (자동 타입 변환)

        Args:
            key: 설정 키
            default: 기본값 (타입 추론에도 사용)

        Returns:
            설정값 (default와 같은 타입으로 변환)
        """
        if key not in self._params:
            return default

        value = self._params[key]

        # default 타입에 맞춰 변환
        if default is None:
            return value

        try:
            if isinstance(default, bool):
                return value.lower() in ('true', '1', 'yes')
            elif isinstance(default, int):
                return int(value)
            elif isinstance(default, float):
                return float(value)
            else:
                return value
        except (ValueError, TypeError):
            return default

    def get_list(self, key: str, default: List = None) -> List[float]:
        """
        쉼표로 구분된 리스트 가져오기

        Args:
            key: 설정 키
            default: 기본값

        Returns:
            float 리스트
        """
        if key not in self._params:
            return default or []

        try:
            value = self._params[key]
            return [float(x.strip()) for x in value.split(',')]
        except (ValueError, TypeError):
            return default or []

    def get_raw(self, key: str, default: str = '') -> str:
        """원본 문자열 그대로 가져오기"""
        return self._params.get(key, default)


class Config:
    """
    정적 설정 (API 키, 심볼 등)
    """

    # API Configuration
    API_KEY = os.getenv('BINANCE_API_KEY', '')
    API_SECRET = os.getenv('BINANCE_API_SECRET', '')
    USE_TESTNET = os.getenv('USE_TESTNET', 'False').lower() == 'true'

    # Symbol mapping (Hyper Scalper V2)
    SYMBOLS = {
        'hyper': 'BTCUSDC',       # Hyper Scalper V2 - BTC/USDC 15분봉
        'hyper_usdt': 'BTCUSDT'   # Hyper Scalper V2 - BTC/USDT 15분봉
    }

    # Price precision (소수점 자릿수)
    PRICE_PRECISION = {
        'hyper': 1,         # BTCUSDC: $95000.1
        'hyper_usdt': 1     # BTCUSDT: $95000.1
    }

    # Quantity precision (소수점 자릿수)
    QTY_PRECISION = {
        'hyper': 3,         # BTCUSDC: 0.001
        'hyper_usdt': 3     # BTCUSDT: 0.001
    }

    # Quote asset (담보 자산)
    QUOTE_ASSET = {
        'hyper': 'USDC',        # BTCUSDC → USDC 담보
        'hyper_usdt': 'USDT'    # BTCUSDT → USDT 담보
    }

    # 파일 경로 템플릿
    LOGS_DIR = 'logs'
    TRADES_DIR = 'trades'
    STATE_DIR = 'state'

    # 웹소켓 설정
    WS_RECONNECT_DELAY = 5

    @classmethod
    def get_symbol(cls, symbol_type: str) -> str:
        """심볼 이름 반환"""
        return cls.SYMBOLS.get(symbol_type.lower(), 'BTCUSDC')

    @classmethod
    def get_price_precision(cls, symbol_type: str) -> int:
        """가격 소수점 자릿수"""
        return cls.PRICE_PRECISION.get(symbol_type.lower(), 1)

    @classmethod
    def get_qty_precision(cls, symbol_type: str) -> int:
        """수량 소수점 자릿수"""
        return cls.QTY_PRECISION.get(symbol_type.lower(), 3)

    @classmethod
    def get_quote_asset(cls, symbol_type: str) -> str:
        """담보 자산 반환 (USDC 또는 USDT)"""
        return cls.QUOTE_ASSET.get(symbol_type.lower(), 'USDT')

    @classmethod
    def get_ws_stream_url_15m(cls, symbol_type: str) -> str:
        """웹소켓 스트림 URL (15분봉 + aggTrade) - Hyper Scalper V2"""
        symbol = cls.get_symbol(symbol_type).lower()
        base_url = "wss://stream.binancefuture.com" if cls.USE_TESTNET else "wss://fstream.binance.com"
        return f"{base_url}/stream?streams={symbol}@kline_15m/{symbol}@aggTrade"

    @classmethod
    def get_trades_path(cls, symbol_type: str) -> str:
        """거래 기록 CSV 경로"""
        return f"{cls.TRADES_DIR}/trades_{symbol_type.lower()}.csv"

    @classmethod
    def get_state_path(cls, symbol_type: str) -> str:
        """상태 스냅샷 경로"""
        return f"{cls.STATE_DIR}/state_{symbol_type.lower()}.json"

    @classmethod
    def get_log_prefix(cls, symbol_type: str) -> str:
        """로그 파일 prefix"""
        return symbol_type.lower()

    @classmethod
    def validate(cls) -> bool:
        """설정 검증"""
        if not cls.API_KEY or not cls.API_SECRET:
            raise ValueError("API keys not configured. Check .env file")
        return True


# Hyper Scalper V2 기본 파라미터 (설정 파일 로드 실패 시 사용)
HYPER_DEFAULT_PARAMS = {
    'DRY_RUN': True,  # 기본값은 dry 모드 (안전)
    'INITIAL_CAPITAL': 1000.0,
    'RISK_PER_TRADE': 0.07,
    'MAX_LEVERAGE': 90,
    'TRADE_DIRECTION': 'BOTH',
    'EMA_FAST': 25,
    'EMA_MID': 100,
    'EMA_SLOW': 200,
    'ADX_LENGTH': 14,
    'ADX_THRESHOLD': 30.0,
    'RETEST_LOOKBACK': 5,
    'SL_LOOKBACK': 29,
    'MAX_SL_DISTANCE': 0.03,
    'ATR_LENGTH': 14,
    'TP_ATR_MULT_LONG': 4.2,
    'TP_ATR_MULT_SHORT': 3.2,
    'MAKER_FEE': 0.0,
    'TAKER_FEE': 0.000275
}
