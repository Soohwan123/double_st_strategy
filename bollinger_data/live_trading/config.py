"""
Configuration for Double Bollinger Band Strategy
Double BB 전략 설정
"""

import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv('.env')

class Config:
    """Configuration class for Double BB strategy"""

    # ============================================================================
    # API Configuration
    # ============================================================================
    API_KEY = os.getenv('BINANCE_API_KEY', '')
    API_SECRET = os.getenv('BINANCE_API_SECRET', '')
    USE_TESTNET = os.getenv('USE_TESTNET', 'False').lower() == 'true'

    # ============================================================================
    # 심볼 설정
    # ============================================================================
    SYMBOL = os.getenv('SYMBOL', 'BTCUSDC')

    # ============================================================================
    # 포지션 설정
    # ============================================================================
    LEVERAGE = 10                   # 레버리지 고정
    POSITION_SIZE_PCT = 1.0         # 자본의 100% 사용

    # ============================================================================
    # 익절/손절 설정
    # ============================================================================
    TAKE_PROFIT_PCT = 0.003         # 익절 비율 (0.3%)
    FEE_RATE = 0.000275             # 수수료율 (0.0275%)

    # ============================================================================
    # 데이터 설정
    # ============================================================================
    MAX_5M_CANDLES = 200            # 5분봉 최대 보관 수
    MIN_CANDLES_FOR_INDICATORS = 20 # 지표 계산 최소 캔들 수

    # ============================================================================
    # 파일 경로
    # ============================================================================
    TRADES_CSV_PATH = 'trade_results/double_st_trades.csv'
    LIVE_INDICATOR_CSV = 'live_data/live_indicators.csv'
    LOGS_DIR = 'logs'

    # ============================================================================
    # 웹소켓 설정
    # ============================================================================
    WS_RECONNECT_DELAY = 5  # 재연결 대기 시간 (초)

    # ============================================================================
    # WebSocket URLs
    # ============================================================================

    @classmethod
    def get_ws_stream_url(cls):
        """5분봉 + aggTrade 스트림 URL"""
        symbol_lower = cls.SYMBOL.lower()
        base_url = "wss://stream.binancefuture.com" if cls.USE_TESTNET else "wss://fstream.binance.com"
        return f"{base_url}/stream?streams={symbol_lower}@kline_5m/{symbol_lower}@aggTrade"

    @classmethod
    def get_rest_api_url(cls):
        """REST API Base URL"""
        if cls.USE_TESTNET:
            return "https://testnet.binancefuture.com"
        else:
            return "https://fapi.binance.com"

    # ============================================================================
    # Validation
    # ============================================================================

    @classmethod
    def validate(cls):
        """설정 검증"""
        if not cls.API_KEY or not cls.API_SECRET:
            raise ValueError("API keys not configured. Please set BINANCE_API_KEY and BINANCE_API_SECRET in .env file")

        if cls.LEVERAGE <= 0 or cls.LEVERAGE > 125:
            raise ValueError("Leverage must be between 1 and 125")

        if cls.TAKE_PROFIT_PCT <= 0 or cls.TAKE_PROFIT_PCT > 0.1:
            raise ValueError("Take profit percentage must be between 0 and 0.1 (10%)")

        return True
