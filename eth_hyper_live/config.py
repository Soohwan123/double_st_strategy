"""
ETH Hyper Scalper Strategy Configuration
동적 파라미터 로딩 지원
"""

import os
from dotenv import load_dotenv
from typing import Dict, Any
import logging

load_dotenv()


class DynamicConfig:
    """동적 파라미터 로딩을 지원하는 설정 클래스"""

    def __init__(self, symbol_type: str, config_dir: str = None):
        self.symbol_type = symbol_type.lower()
        self.config_dir = config_dir or os.path.dirname(os.path.abspath(__file__))
        self.config_file = os.path.join(self.config_dir, f'config_{self.symbol_type}.txt')
        self._params: Dict[str, str] = {}
        self._last_modified = 0
        self.reload()

    def reload(self) -> bool:
        try:
            mtime = os.path.getmtime(self.config_file)
            if mtime == self._last_modified:
                return False

            self._last_modified = mtime
            self._params = {}

            with open(self.config_file, 'r') as f:
                for line in f:
                    line = line.strip()
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
        if key not in self._params:
            return default

        value = self._params[key]

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

    def get_raw(self, key: str, default: str = '') -> str:
        return self._params.get(key, default)


class Config:
    """정적 설정 (API 키, 심볼 등)"""

    API_KEY = os.getenv('BINANCE_API_KEY', '')
    API_SECRET = os.getenv('BINANCE_API_SECRET', '')
    USE_TESTNET = os.getenv('USE_TESTNET', 'False').lower() == 'true'

    SYMBOLS = {
        'eth_hyper': 'ETHUSDT'
    }

    PRICE_PRECISION = {
        'eth_hyper': 2       # ETHUSDT: $2500.12
    }

    QTY_PRECISION = {
        'eth_hyper': 3       # ETHUSDT: 0.001
    }

    QUOTE_ASSET = {
        'eth_hyper': 'USDT'
    }

    LOGS_DIR = 'logs'
    TRADES_DIR = 'trades'
    STATE_DIR = 'state'

    WS_RECONNECT_DELAY = 5

    @classmethod
    def get_symbol(cls, symbol_type: str) -> str:
        return cls.SYMBOLS.get(symbol_type.lower(), 'ETHUSDT')

    @classmethod
    def get_price_precision(cls, symbol_type: str) -> int:
        return cls.PRICE_PRECISION.get(symbol_type.lower(), 2)

    @classmethod
    def get_qty_precision(cls, symbol_type: str) -> int:
        return cls.QTY_PRECISION.get(symbol_type.lower(), 3)

    @classmethod
    def get_quote_asset(cls, symbol_type: str) -> str:
        return cls.QUOTE_ASSET.get(symbol_type.lower(), 'USDT')

    @classmethod
    def get_ws_stream_url_15m(cls, symbol_type: str) -> str:
        """웹소켓 스트림 URL (15분봉 + aggTrade)"""
        symbol = cls.get_symbol(symbol_type).lower()
        base_url = "wss://stream.binancefuture.com" if cls.USE_TESTNET else "wss://fstream.binance.com"
        return f"{base_url}/stream?streams={symbol}@kline_15m/{symbol}@aggTrade"

    @classmethod
    def get_trades_path(cls, symbol_type: str) -> str:
        return f"{cls.TRADES_DIR}/trades_{symbol_type.lower()}.csv"

    @classmethod
    def get_state_path(cls, symbol_type: str) -> str:
        return f"{cls.STATE_DIR}/state_{symbol_type.lower()}.json"

    @classmethod
    def get_log_prefix(cls, symbol_type: str) -> str:
        return symbol_type.lower()

    @classmethod
    def validate(cls) -> bool:
        if not cls.API_KEY or not cls.API_SECRET:
            raise ValueError("API keys not configured. Check .env file")
        return True


# ETH Hyper Scalper 기본 파라미터
ETH_HYPER_DEFAULT_PARAMS = {
    'DRY_RUN': True,
    'INITIAL_CAPITAL': 1000.0,
    'RISK_PER_TRADE': 0.07,
    'MAX_LEVERAGE': 90,
    'TRADE_DIRECTION': 'BOTH',
    'EMA_FAST': 20,
    'EMA_MID': 100,
    'EMA_SLOW': 200,
    'ADX_LENGTH': 14,
    'ADX_THRESHOLD': 40.0,
    'RETEST_LOOKBACK': 15,
    'SL_LOOKBACK': 50,
    'MAX_SL_DISTANCE': 0.035,
    'ATR_LENGTH': 10,
    'TP_ATR_MULT_LONG': 10.0,
    'TP_ATR_MULT_SHORT': 2.0,
    'MAKER_FEE': 0.0002,
    'TAKER_FEE': 0.0005,
    'FEE_PROTECTION': True
}
