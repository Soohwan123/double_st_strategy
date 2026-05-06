"""
Breakout Strategy Configuration (Hyper 부계정 — hyper_v2/eth_hyper 와 같은 계정)

심볼:
  - breakout_sol: SOLUSDT 5m bt_02 v4 best
  - breakout_xrp: XRPUSDT 5m bt_03 v4 best
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
        'breakout_sol': 'SOLUSDT',
        'breakout_xrp': 'XRPUSDT',
    }

    PRICE_PRECISION = {
        'breakout_sol': 2,  # SOLUSDT tickSize=0.0100 (Binance API pricePrecision=4 인데 실제 tick 은 0.01)
        'breakout_xrp': 4,  # XRPUSDT tickSize=0.0001 → precision 4 정확
    }

    QTY_PRECISION = {
        'breakout_sol': 2,  # Binance: SOLUSDT stepSize=0.01 (qty=0.01 단위)
        'breakout_xrp': 1,  # XRPUSDT stepSize=0.1
    }

    QUOTE_ASSET = {
        'breakout_sol': 'USDT',
        'breakout_xrp': 'USDT',
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


# Breakout 기본 파라미터 (config 파일에서 override 가능)
BREAKOUT_DEFAULT_PARAMS = {
    'DRY_RUN': True,
    'INITIAL_CAPITAL': 200.0,
    'TF': '5m',
    'LENGTH': 180,
    'MULT': 0.47,
    'SL_ATR_MULT': 4.2,
    'RR': 1.1,
    'RISK_PER_TRADE': 0.08,
    'MAX_LEVERAGE': 90,
    'TAKER_FEE': 0.0005,
    'MAKER_FEE': 0.0002,
}
