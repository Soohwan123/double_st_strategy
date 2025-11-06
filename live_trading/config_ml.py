"""
Configuration loader for ML Strategy
머신러닝 트레이딩 전략 설정
"""

import os
from dotenv import load_dotenv

# Load environment variables from .env_ml file
load_dotenv('.env_ml')

class Config:
    """Configuration class for ML strategy"""

    # API Configuration
    BINANCE_API_KEY = os.getenv('BINANCE_API_KEY', '')
    BINANCE_API_SECRET = os.getenv('BINANCE_API_SECRET', '')
    USE_TESTNET = os.getenv('USE_TESTNET', 'False').lower() == 'true'

    # Trading Configuration
    INITIAL_CAPITAL = float(os.getenv('INITIAL_CAPITAL', '1000.0'))
    RISK_PER_TRADE = float(os.getenv('RISK_PER_TRADE', '0.03'))  # 3% risk per trade
    SYMBOL = os.getenv('SYMBOL', 'BTCUSDC')

    # ML Model Paths
    ML_MODEL_PATH = os.getenv('ML_MODEL_PATH', '../ml_trading_strategy/saved_models/rf_model.pkl')
    ML_SCALER_PATH = os.getenv('ML_SCALER_PATH', '../ml_trading_strategy/saved_models/scaler.pkl')
    ML_FEATURE_COLUMNS_PATH = os.getenv('ML_FEATURE_COLUMNS_PATH', '../ml_trading_strategy/saved_models/feature_columns.pkl')

    # Indicator Parameters (백테스트와 동일)
    # RSI settings
    RSI_LENGTH = 14
    RSI_EMA_LENGTH = 14

    # Stochastic settings
    STOCH_K_LENGTH = 14
    STOCH_K_SMOOTH = 3
    STOCH_D_SMOOTH = 3

    # TRIX settings
    TRIX_LENGTH = 14

    # EMA settings
    EMA_LENGTHS = [200, 150, 50]

    # SuperTrend settings
    SUPERTREND_ATR_LENGTH = 12
    SUPERTREND_MULTIPLIER = 3

    # Stop loss lookback
    STOP_LOSS_LOOKBACK = 10

    # Profit ratio
    PROFIT_RATIO = 2.0  # 1:2 ratio

    # Trading fees (BTCUSDC uses USDC margin - 0.0275% taker fee)
    TAKER_FEE = 0.000275  # 0.0275%
    MAKER_FEE = 0.0  # 0% for limit orders
    

    # WebSocket URLs - 5분봉, 15분봉, 1시간봉, 4시간봉, 실시간 Ticker
    WS_URL_5M_LIVE = f"wss://fstream.binance.com/ws/{SYMBOL.lower()}@kline_5m"
    WS_URL_5M_TESTNET = f"wss://stream.binancefuture.com/ws/{SYMBOL.lower()}@kline_5m"

    WS_URL_15M_LIVE = f"wss://fstream.binance.com/ws/{SYMBOL.lower()}@kline_15m"
    WS_URL_15M_TESTNET = f"wss://stream.binancefuture.com/ws/{SYMBOL.lower()}@kline_15m"

    WS_URL_1H_LIVE = f"wss://fstream.binance.com/ws/{SYMBOL.lower()}@kline_1h"
    WS_URL_1H_TESTNET = f"wss://stream.binancefuture.com/ws/{SYMBOL.lower()}@kline_1h"

    WS_URL_4H_LIVE = f"wss://fstream.binance.com/ws/{SYMBOL.lower()}@kline_4h"
    WS_URL_4H_TESTNET = f"wss://stream.binancefuture.com/ws/{SYMBOL.lower()}@kline_4h"

    WS_URL_TICKER_LIVE = f"wss://fstream.binance.com/ws/{SYMBOL.lower()}@ticker"
    WS_URL_TICKER_TESTNET = f"wss://stream.binancefuture.com/ws/{SYMBOL.lower()}@ticker"

    @classmethod
    def get_ws_url_5m(cls):
        """Get 5m WebSocket URL based on testnet setting"""
        return cls.WS_URL_5M_TESTNET if cls.USE_TESTNET else cls.WS_URL_5M_LIVE

    @classmethod
    def get_ws_url_15m(cls):
        """Get 15m WebSocket URL based on testnet setting"""
        return cls.WS_URL_15M_TESTNET if cls.USE_TESTNET else cls.WS_URL_15M_LIVE

    @classmethod
    def get_ws_url_1h(cls):
        """Get 1h WebSocket URL based on testnet setting"""
        return cls.WS_URL_1H_TESTNET if cls.USE_TESTNET else cls.WS_URL_1H_LIVE

    @classmethod
    def get_ws_url_4h(cls):
        """Get 4h WebSocket URL based on testnet setting"""
        return cls.WS_URL_4H_TESTNET if cls.USE_TESTNET else cls.WS_URL_4H_LIVE

    @classmethod
    def get_ws_url_ticker(cls):
        """Get Ticker WebSocket URL based on testnet setting"""
        return cls.WS_URL_TICKER_TESTNET if cls.USE_TESTNET else cls.WS_URL_TICKER_LIVE

    @classmethod
    def validate(cls):
        """Validate configuration"""
        if not cls.BINANCE_API_KEY or not cls.BINANCE_API_SECRET:
            raise ValueError("API keys not configured. Please set BINANCE_API_KEY and BINANCE_API_SECRET")

        if cls.INITIAL_CAPITAL <= 0:
            raise ValueError("Initial capital must be positive")

        if cls.RISK_PER_TRADE <= 0 or cls.RISK_PER_TRADE > 0.1:
            raise ValueError("Risk per trade must be between 0 and 0.1 (10%)")

        # Check ML model files exist
        if not os.path.exists(cls.ML_MODEL_PATH):
            raise ValueError(f"ML model file not found: {cls.ML_MODEL_PATH}")

        if not os.path.exists(cls.ML_SCALER_PATH):
            raise ValueError(f"ML scaler file not found: {cls.ML_SCALER_PATH}")

        if not os.path.exists(cls.ML_FEATURE_COLUMNS_PATH):
            raise ValueError(f"ML feature columns file not found: {cls.ML_FEATURE_COLUMNS_PATH}")

        return True
