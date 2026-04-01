#!/usr/bin/env python3
import ccxt, time, os
print("🤖 MÉGA BOT v3.0 READY - Trading auto 14h-22h UTC")
exchange = ccxt.binance()
while True:
    try:
        ticker = exchange.fetch_ticker('BTC/USDT')
        print(f"BTC: ${ticker['last']:.2f}")
        time.sleep(60)
    except Exception as e:
        print(f"Error: {e}")
        time.sleep(60)
