#!/usr/bin/env python3
"""
Machine Learning Model API Connection Test
Tests Binance API connectivity for Machine Learning Model trading
"""

import asyncio
import sys
import os

# Add parent directory to path to import config
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config_ml import Config
from binance.client import Client
from binance.exceptions import BinanceAPIException

async def test_api_connection():
    """Test Binance API connection and permissions"""

    print("🔍 SRT Strategy API Connection Test")
    print("=" * 50)

    # Validate configuration
    try:
        Config.validate()
        print("✅ Configuration validated")
    except ValueError as e:
        print(f"❌ Configuration error: {e}")
        return False

    # Initialize client
    try:
        client = Client(
            api_key=Config.BINANCE_API_KEY,
            api_secret=Config.BINANCE_API_SECRET,
            testnet=Config.USE_TESTNET
        )
        print(f"✅ Client initialized ({'Testnet' if Config.USE_TESTNET else 'Live'})")
    except Exception as e:
        print(f"❌ Client initialization failed: {e}")
        return False

    # Test server time
    try:
        server_time = client.get_server_time()
        print(f"✅ Server connection OK (Time: {server_time['serverTime']})")
    except BinanceAPIException as e:
        print(f"❌ Server connection failed: {e}")
        return False

    # Test futures account
    try:
        account = client.futures_account()
        balance_usdc = None
        for asset in account['assets']:
            if asset['asset'] == 'USDC':
                balance_usdc = float(asset['walletBalance'])
                break

        if balance_usdc is not None:
            print(f"✅ Futures account access OK")
            print(f"💰 USDC Balance: {balance_usdc:.2f}")

            if balance_usdc < Config.INITIAL_CAPITAL:
                print(f"⚠️  Warning: Balance ({balance_usdc:.2f}) < Initial Capital ({Config.INITIAL_CAPITAL})")
        else:
            print("❌ USDC balance not found")
            return False

    except BinanceAPIException as e:
        print(f"❌ Futures account access failed: {e}")
        print("💡 Check API permissions: Enable Futures trading")
        return False

    # Test symbol info
    try:
        symbol_info = client.futures_exchange_info()
        btcusdc_info = None
        for symbol in symbol_info['symbols']:
            if symbol['symbol'] == Config.SYMBOL:
                btcusdc_info = symbol
                break

        if btcusdc_info:
            print(f"✅ Symbol {Config.SYMBOL} found")
            print(f"📊 Status: {btcusdc_info['status']}")

            # Find minimum order quantity
            min_qty = None
            for filter_item in btcusdc_info['filters']:
                if filter_item['filterType'] == 'LOT_SIZE':
                    min_qty = float(filter_item['minQty'])
                    break

            if min_qty:
                print(f"📏 Minimum order size: {min_qty}")
        else:
            print(f"❌ Symbol {Config.SYMBOL} not found")
            return False

    except BinanceAPIException as e:
        print(f"❌ Symbol info failed: {e}")
        return False

    # Test current price
    try:
        ticker = client.futures_symbol_ticker(symbol=Config.SYMBOL)
        current_price = float(ticker['price'])
        print(f"✅ Current {Config.SYMBOL} price: ${current_price:,.2f}")
    except BinanceAPIException as e:
        print(f"❌ Price fetch failed: {e}")
        return False

    # Test WebSocket URLs
    ws_url_5m = Config.get_ws_url_5m()
    print(f"✅ WebSocket 5m URL: {ws_url_5m}")
    ws_url_1h = Config.get_ws_url_1h()
    print(f"✅ WebSocket 1h URL: {ws_url_1h}")
    ws_url_4h = Config.get_ws_url_4h()
    print(f"✅ WebSocket 4h URL: {ws_url_4h}")


    print("\n" + "=" * 50)
    print("🎉 All tests passed! Ready for live trading.")
    print(f"📈 Strategy: Machine Learning Model")
    print(f"💱 Symbol: {Config.SYMBOL}")
    print(f"💰 Initial Capital: ${Config.INITIAL_CAPITAL}")
    print(f"⚡ Risk per Trade: {Config.RISK_PER_TRADE * 100}%")
    print("=" * 50)

    return True

if __name__ == "__main__":
    asyncio.run(test_api_connection())