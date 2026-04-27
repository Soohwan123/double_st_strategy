"""
OB Retest Strategy Configuration (단일 심볼 SOL, hyper_v2 와 동일 부계정 API)
"""

import os
from dotenv import load_dotenv
from typing import Dict, Any
import logging

load_dotenv()


class DynamicConfig:
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
    API_KEY = os.getenv('BINANCE_API_KEY', '')
    API_SECRET = os.getenv('BINANCE_API_SECRET', '')
    USE_TESTNET = os.getenv('USE_TESTNET', 'False').lower() == 'true'

    SYMBOLS = {
        'ob_sol': 'SOLUSDT',
        'ob_eth': 'ETHUSDT',
    }

    PRICE_PRECISION = {
        'ob_sol': 2,
        'ob_eth': 2,
    }

    QTY_PRECISION = {
        'ob_sol': 0,
        'ob_eth': 3,
    }

    QUOTE_ASSET = {
        'ob_sol': 'USDT',
        'ob_eth': 'USDT',
    }

    LOGS_DIR = 'logs'
    TRADES_DIR = 'trades'
    STATE_DIR = 'state'
    WS_RECONNECT_DELAY = 5

    @classmethod
    def get_symbol(cls, symbol_type: str) -> str:
        return cls.SYMBOLS.get(symbol_type.lower(), 'SOLUSDT')

    @classmethod
    def get_price_precision(cls, symbol_type: str) -> int:
        return cls.PRICE_PRECISION.get(symbol_type.lower(), 2)

    @classmethod
    def get_qty_precision(cls, symbol_type: str) -> int:
        return cls.QTY_PRECISION.get(symbol_type.lower(), 0)

    @classmethod
    def get_quote_asset(cls, symbol_type: str) -> str:
        return cls.QUOTE_ASSET.get(symbol_type.lower(), 'USDT')

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


# OB 전략 default 파라미터 (config 파일에서 override 가능)
OB_DEFAULT_PARAMS = {
    'DRY_RUN': True,
    'INITIAL_CAPITAL': 200.0,
    'TF': '5m',
    'IMPULSE_LOOKBACK': 17,
    'IMPULSE_MIN_PCT': 0.025,
    'SL_BUFFER_PCT': 0.0025,
    'RR': 0.35,
    'MAX_WAIT': 550,
    'RISK_PER_TRADE': 0.12,
    'MAX_LEVERAGE': 90,
    'TRADE_DIRECTION': 'BOTH',
    'USE_HTF': True,
    'HTF_EMA_LEN': 200,
    'MAX_OB_QUEUE': 16,
    'TAKER_FEE': 0.0005,
    'MAKER_FEE': 0.0002,
    'STRATEGY_MODE': 'BT_LONG_FIRST',  # LONG-priority (BT _common_swap.py 의 entry block 순서 매칭)
}
