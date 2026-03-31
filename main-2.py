"""
╔══════════════════════════════════════════════════════════════════╗
║          BINANCE PROFESSIONAL TRADING BOT v5.0 ULTIMATE          ║
║                                                                  ║
║  Stratégie  : RSI + MACD + Bollinger + EMA 50/200 (tendance)    ║
║  Sécurité   : Anti-PnD | Cooldown | Max 1 trade/paire           ║
║  Fiabilité  : Reconnexion auto | Alerte balance | CSV backup     ║
║  Timing     : Fenêtres optimales | Pause weekend                 ║
╚══════════════════════════════════════════════════════════════════╝
"""

import os
import csv
import time
import logging
import requests
import threading
from datetime import datetime, timezone, timedelta
from binance.client import Client
from binance.exceptions import BinanceAPIException
import pandas as pd
import numpy as np
from http.server import HTTPServer, BaseHTTPRequestHandler

# ══════════════════════════════════════════════
#  CONFIGURATION
# ══════════════════════════════════════════════
API_KEY        = os.environ.get("BINANCE_API_KEY", "")
API_SECRET     = os.environ.get("BINANCE_SECRET_KEY", "")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT  = os.environ.get("TELEGRAM_CHAT_ID", "")

# ── Top 10 paires ──
PAIRS = [
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT",
    "XRPUSDT", "ADAUSDT", "DOGEUSDT", "AVAXUSDT",
    "DOTUSDT", "MATICUSDT"
]

# ── Fenêtres de trading optimales (UTC) ──
TRADING_WINDOWS = [
    (0,  3,  "Asie",       2),
    (8,  12, "Europe",     2),
    (13, 17, "Europe+US",  3),   # Meilleure période
    (17, 20, "US",         2),
]
WEEKEND_TRADING = False

# ── Gestion du risque ──
RISK_PER_TRADE     = 0.03    # 3% du capital
STOP_LOSS_PCT      = 0.015   # -1.5%
TAKE_PROFIT_PCT    = 0.04    # +4%
TRAILING_STOP_PCT  = 0.012   # -1.2% depuis le plus haut
MAX_OPEN_TRADES    = 2       # Max 2 trades simultanés
TRADE_COOLDOWN_MIN = 30      # 30 min entre 2 trades sur la même paire
MIN_BALANCE_ALERT  = 20.0    # Alerte si USDT < $20
TRADE_INTERVAL     = 60      # Vérification toutes les 60s

# ── Anti pump-and-dump ──
PUMP_THRESHOLD     = 0.05
DUMP_THRESHOLD     = -0.05
VOLUME_SPIKE_MULT  = 3.0

# ── Indicateurs ──
RSI_PERIOD         = 14
RSI_OVERSOLD       = 35
RSI_OVERBOUGHT     = 65
MACD_FAST          = 12
MACD_SLOW          = 26
MACD_SIGNAL        = 9
BB_PERIOD          = 20
BB_STD             = 2.0
EMA_FAST           = 50     # EMA court terme
EMA_SLOW           = 200    # EMA long terme
CANDLE_INTERVAL    = Client.KLINE_INTERVAL_15MINUTE
CANDLE_LIMIT       = 220    # >= EMA_SLOW pour calcul précis

# ── Fichier CSV de sauvegarde ──
CSV_FILE           = "trades_history.csv"

# ══════════════════════════════════════════════
#  LOGGING
# ══════════════════════════════════════════════
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
log = logging.getLogger(__name__)

# ══════════════════════════════════════════════
#  SERVEUR HTTP (requis pour Render)
# ══════════════════════════════════════════════
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        msg = f"Bot Binance v5.0 ULTIMATE | {datetime.now(timezone.utc).strftime('%H:%M UTC')}"
        self.wfile.write(msg.encode())
    def log_message(self, *args):
        pass

def start_health_server():
    port = int(os.environ.get("PORT", 8000))
    HTTPServer(("0.0.0.0", port), HealthHandler).serve_forever()

# ══════════════════════════════════════════════
#  TELEGRAM
# ══════════════════════════════════════════════
def send_telegram(message: str):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT:
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, json={
            "chat_id": TELEGRAM_CHAT,
            "text": message,
            "parse_mode": "HTML"
        }, timeout=10)
    except Exception as e:
        log.warning(f"Telegram erreur: {e}")

# ══════════════════════════════════════════════
#  RECONNEXION AUTOMATIQUE BINANCE
# ══════════════════════════════════════════════
def create_client(retries: int = 10, delay: int = 30) -> Client:
    """
    Crée le client Binance avec reconnexion automatique.
    Réessaie jusqu'à `retries` fois avec `delay` secondes d'attente.
    """
    for attempt in range(1, retries + 1):
        try:
            client = Client(API_KEY, API_SECRET)
            client.ping()
            log.info(f"Connexion Binance OK (tentative {attempt})")
            return client
        except Exception as e:
            log.error(f"Connexion échouée ({attempt}/{retries}): {e}")
            if attempt < retries:
                log.info(f"Nouvelle tentative dans {delay}s...")
                time.sleep(delay)

    log.critical("Impossible de se connecter à Binance après plusieurs tentatives.")
    send_telegram("🚨 <b>ERREUR CRITIQUE</b> : impossible de connecter à Binance !")
    raise ConnectionError("Binance inaccessible")

def safe_api_call(func, *args, client_ref: list = None, **kwargs):
    """
    Appelle une fonction Binance en gérant les erreurs réseau.
    En cas d'échec, tente une reconnexion automatique.
    """
    for attempt in range(3):
        try:
            return func(*args, **kwargs)
        except (BinanceAPIException, requests.exceptions.RequestException) as e:
            log.warning(f"Erreur API (tentative {attempt+1}/3): {e}")
            if attempt == 2 and client_ref is not None:
                log.info("Reconnexion Binance en cours...")
                send_telegram("🔄 <b>Reconnexion Binance...</b>")
                try:
                    client_ref[0] = create_client()
                    log.info("Reconnexion réussie ✓")
                    send_telegram("✅ <b>Reconnexion réussie !</b>")
                except Exception as re:
                    log.error(f"Reconnexion échouée: {re}")
            time.sleep(5 * (attempt + 1))
    return None

# ══════════════════════════════════════════════
#  SAUVEGARDE CSV
# ══════════════════════════════════════════════
def save_trade_csv(trade_type: str, symbol: str, qty: float,
                   price: float, pnl: float = 0.0, reason: str = ""):
    file_exists = os.path.isfile(CSV_FILE)
    try:
        with open(CSV_FILE, "a", newline="") as f:
            writer = csv.writer(f)
            if not file_exists:
                writer.writerow(["date", "heure", "type", "paire", "quantite",
                                 "prix", "pnl_%", "raison"])
            now = datetime.now()
            writer.writerow([
                now.strftime("%d/%m/%Y"),
                now.strftime("%H:%M:%S"),
                trade_type, symbol,
                f"{qty:.6f}", f"{price:.4f}",
                f"{pnl:+.2f}", reason
            ])
    except Exception as e:
        log.warning(f"Erreur CSV: {e}")

# ══════════════════════════════════════════════
#  FENÊTRES DE TRADING
# ══════════════════════════════════════════════
def is_good_trading_time() -> tuple[bool, str]:
    hour    = datetime.now(timezone.utc).hour
    weekday = datetime.now(timezone.utc).weekday()

    if weekday >= 5 and not WEEKEND_TRADING:
        return False, f"{'Samedi' if weekday==5 else 'Dimanche'} — volume réduit, pause"

    for start, end, name, score in TRADING_WINDOWS:
        if start <= hour < end:
            return True, f"Session {name} ({'⭐'*score})"

    return False, f"Creux ({hour}h UTC) — faible liquidité"

# ══════════════════════════════════════════════
#  COOLDOWN PAR PAIRE
# ══════════════════════════════════════════════
def is_on_cooldown(last_trades: dict, symbol: str) -> bool:
    if symbol not in last_trades:
        return False
    elapsed = (datetime.now() - last_trades[symbol]).total_seconds() / 60
    return elapsed < TRADE_COOLDOWN_MIN

# ══════════════════════════════════════════════
#  ANTI PUMP-AND-DUMP
# ══════════════════════════════════════════════
def is_pump_or_dump(client: Client, symbol: str) -> bool:
    try:
        klines  = client.get_klines(symbol=symbol, interval=Client.KLINE_INTERVAL_1HOUR, limit=24)
        closes  = [float(k[4]) for k in klines]
        volumes = [float(k[5]) for k in klines]

        change       = (closes[-1] - closes[-2]) / closes[-2]
        avg_vol      = np.mean(volumes[:-1])
        vol_ratio    = volumes[-1] / avg_vol if avg_vol > 0 else 1

        if change >= PUMP_THRESHOLD:
            log.warning(f"{symbol} PUMP: +{change*100:.1f}%")
            return True
        if change <= DUMP_THRESHOLD:
            log.warning(f"{symbol} DUMP: {change*100:.1f}%")
            return True
        if vol_ratio >= VOLUME_SPIKE_MULT:
            log.warning(f"{symbol} Volume suspect: {vol_ratio:.1f}x")
            return True
        return False
    except Exception as e:
        log.error(f"Erreur anti-PnD {symbol}: {e}")
        return True

# ══════════════════════════════════════════════
#  INDICATEURS TECHNIQUES
# ══════════════════════════════════════════════
def compute_rsi(series: pd.Series) -> pd.Series:
    delta = series.diff()
    gain  = delta.clip(lower=0).ewm(com=RSI_PERIOD - 1, adjust=True).mean()
    loss  = (-delta.clip(upper=0)).ewm(com=RSI_PERIOD - 1, adjust=True).mean()
    return 100 - (100 / (1 + gain / loss))

def compute_macd(series: pd.Series):
    fast   = series.ewm(span=MACD_FAST, adjust=False).mean()
    slow   = series.ewm(span=MACD_SLOW, adjust=False).mean()
    macd   = fast - slow
    signal = macd.ewm(span=MACD_SIGNAL, adjust=False).mean()
    return macd - signal  # histogramme uniquement

def compute_bollinger(series: pd.Series):
    sma = series.rolling(BB_PERIOD).mean()
    std = series.rolling(BB_PERIOD).std()
    return sma + BB_STD * std, sma - BB_STD * std

def get_signal(client: Client, symbol: str) -> str:
    """
    Signal BUY  : prix > EMA200 (tendance haussière) + RSI survendu
                  + MACD croise à la hausse + prix sous BB low
    Signal SELL : prix < EMA200 (tendance baissière) + RSI suracheté
                  + MACD croise à la baisse + prix sur BB upper
    """
    try:
        klines = client.get_klines(
            symbol=symbol,
            interval=CANDLE_INTERVAL,
            limit=CANDLE_LIMIT
        )
        df = pd.DataFrame(klines, columns=[
            "time","open","high","low","close","volume",
            "close_time","qav","trades","tbav","tbqv","ignore"
        ])
        df["close"] = df["close"].astype(float)

        # Indicateurs
        rsi          = compute_rsi(df["close"])
        hist         = compute_macd(df["close"])
        bb_up, bb_lo = compute_bollinger(df["close"])
        ema_fast     = df["close"].ewm(span=EMA_FAST, adjust=False).mean()
        ema_slow     = df["close"].ewm(span=EMA_SLOW, adjust=False).mean()

        c     = df["close"].iloc[-1]    # prix actuel
        rsi_v = rsi.iloc[-1]
        h_now = hist.iloc[-1]
        h_pre = hist.iloc[-2]
        ef    = ema_fast.iloc[-1]       # EMA 50
        es    = ema_slow.iloc[-1]       # EMA 200

        trend_up   = c > es and ef > es   # tendance haussière confirmée
        trend_down = c < es and ef < es   # tendance baissière confirmée

        # Signal BUY : dans le sens de la tendance haussière
        if (trend_up and
            rsi_v < RSI_OVERSOLD and
            h_now > h_pre and
            c <= bb_lo.iloc[-1] * 1.005):
            return "BUY"

        # Signal SELL : dans le sens de la tendance baissière
        if (trend_down and
            rsi_v > RSI_OVERBOUGHT and
            h_now < h_pre and
            c >= bb_up.iloc[-1] * 0.995):
            return "SELL"

        return "HOLD"

    except Exception as e:
        log.error(f"Erreur signal {symbol}: {e}")
        return "HOLD"

# ══════════════════════════════════════════════
#  GESTION DES ORDRES
# ══════════════════════════════════════════════
def get_balance(client: Client, asset: str = "USDT") -> float:
    try:
        return float(client.get_asset_balance(asset=asset)["free"])
    except:
        return 0.0

def get_price(client: Client, symbol: str) -> float:
    try:
        return float(client.get_symbol_ticker(symbol=symbol)["price"])
    except:
        return 0.0

def get_lot_size(client: Client, symbol: str):
    try:
        info = client.get_symbol_info(symbol)
        for f in info["filters"]:
            if f["filterType"] == "LOT_SIZE":
                return float(f["minQty"]), float(f["stepSize"])
    except:
        pass
    return 0.0, 0.001

def round_step(qty: float, step: float) -> float:
    precision = len(str(step).rstrip("0").split(".")[-1]) if "." in str(step) else 0
    return round(qty - (qty % step), precision)

def place_buy(client: Client, symbol: str, usdt_balance: float, session: str) -> dict:
    try:
        price         = get_price(client, symbol)
        if price == 0:
            return {}
        min_qty, step = get_lot_size(client, symbol)
        qty           = round_step((usdt_balance * RISK_PER_TRADE) / price, step)

        if qty < min_qty:
            log.warning(f"{symbol}: quantité trop petite ({qty} < {min_qty})")
            return {}

        client.order_market_buy(symbol=symbol, quantity=qty)
        log.info(f"✅ ACHAT {symbol} | Qty: {qty} | Prix: {price:.4f}")
        save_trade_csv("BUY", symbol, qty, price)

        send_telegram(
            f"🟢 <b>ACHAT</b> — {symbol}\n"
            f"━━━━━━━━━━━━━━\n"
            f"💰 Quantité  : {qty}\n"
            f"📈 Prix      : {price:.4f} USDT\n"
            f"🛑 Stop-Loss : {price*(1-STOP_LOSS_PCT):.4f}\n"
            f"🎯 TP        : {price*(1+TAKE_PROFIT_PCT):.4f}\n"
            f"🔄 Trailing  : -{TRAILING_STOP_PCT*100}%\n"
            f"⏰ Session   : {session}\n"
            f"🕐 {datetime.now().strftime('%H:%M:%S')} UTC"
        )
        return {"symbol": symbol, "qty": qty, "buy_price": price, "highest": price}

    except BinanceAPIException as e:
        log.error(f"Erreur achat {symbol}: {e}")
        return {}

def place_sell(client: Client, trade: dict, reason: str, daily_stats: dict):
    try:
        symbol  = trade["symbol"]
        price   = get_price(client, symbol)
        _, step = get_lot_size(client, symbol)
        qty     = round_step(trade["qty"], step)

        client.order_market_sell(symbol=symbol, quantity=qty)

        pnl   = (price - trade["buy_price"]) / trade["buy_price"] * 100
        emoji = "🟢" if pnl > 0 else "🔴"

        daily_stats["total_trades"] += 1
        daily_stats["total_pnl"]    += pnl
        daily_stats["wins" if pnl > 0 else "losses"] += 1

        save_trade_csv("SELL", symbol, qty, price, pnl, reason)
        log.info(f"{emoji} VENTE {symbol} | PnL: {pnl:+.2f}% | {reason}")

        send_telegram(
            f"{emoji} <b>VENTE</b> — {symbol}\n"
            f"━━━━━━━━━━━━━━\n"
            f"📉 Prix vente : {price:.4f} USDT\n"
            f"📊 PnL        : {pnl:+.2f}%\n"
            f"📌 Raison     : {reason}\n"
            f"🕐 {datetime.now().strftime('%H:%M:%S')} UTC"
        )

    except BinanceAPIException as e:
        log.error(f"Erreur vente {trade['symbol']}: {e}")

# ══════════════════════════════════════════════
#  RAPPORT JOURNALIER
# ══════════════════════════════════════════════
def send_daily_report(client: Client, daily_stats: dict):
    balance  = get_balance(client)
    total    = daily_stats["total_trades"]
    wins     = daily_stats["wins"]
    losses   = daily_stats["losses"]
    pnl      = daily_stats["total_pnl"]
    win_rate = (wins / total * 100) if total > 0 else 0
    emoji    = "🟢" if pnl >= 0 else "🔴"

    send_telegram(
        f"📊 <b>RAPPORT JOURNALIER</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💼 Balance    : {balance:.2f} USDT\n"
        f"📈 Trades     : {total}\n"
        f"✅ Gagnants   : {wins}\n"
        f"❌ Perdants   : {losses}\n"
        f"🎯 Win Rate   : {win_rate:.1f}%\n"
        f"{emoji} PnL total  : {pnl:+.2f}%\n"
        f"📅 {datetime.now().strftime('%d/%m/%Y')}"
    )
    for k in daily_stats:
        daily_stats[k] = 0

# ══════════════════════════════════════════════
#  BOUCLE PRINCIPALE
# ══════════════════════════════════════════════
def run_bot():
    log.info("Démarrage Bot Binance v5.0 ULTIMATE...")

    # Connexion initiale avec retry automatique
    client_ref = [create_client()]
    client     = client_ref[0]

    balance = get_balance(client)

    send_telegram(
        "🤖 <b>Bot Binance v5.0 ULTIMATE</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        f"💼 Balance : {balance:.2f} USDT\n"
        f"📊 Paires  : {len(PAIRS)} cryptos\n\n"
        "⏰ <b>Fenêtres trading (UTC) :</b>\n"
        "  🌏 00h-03h Asie ⭐⭐\n"
        "  🌍 08h-12h Europe ⭐⭐\n"
        "  🔥 13h-17h EU+US ⭐⭐⭐\n"
        "  🌎 17h-20h US ⭐⭐\n\n"
        "🛡️ Anti PnD : actif\n"
        "🔄 Trailing Stop : actif\n"
        "📈 Filtre EMA 50/200 : actif\n"
        "⏱️ Cooldown 30min/paire : actif\n"
        "🔁 Reconnexion auto : actif\n"
        "📁 Historique CSV : actif"
    )

    open_trades   = {}   # symbol -> trade info
    daily_stats   = {"total_trades": 0, "wins": 0, "losses": 0, "total_pnl": 0.0}
    last_trades   = {}   # symbol -> datetime du dernier trade (cooldown)
    last_report   = datetime.now(timezone.utc).date()
    pause_alerted = False
    balance_alerted = False

    while True:
        try:
            # Mettre à jour la référence client (peut avoir changé après reconnexion)
            client = client_ref[0]
            now    = datetime.now(timezone.utc)

            # ── Rapport journalier à minuit ──
            if now.date() != last_report:
                send_daily_report(client, daily_stats)
                last_report = now.date()

            # ── Alerte balance faible ──
            balance = get_balance(client)
            if balance < MIN_BALANCE_ALERT and not balance_alerted:
                send_telegram(
                    f"⚠️ <b>BALANCE FAIBLE</b>\n"
                    f"💼 Solde actuel : {balance:.2f} USDT\n"
                    f"📌 Seuil alerte : {MIN_BALANCE_ALERT} USDT\n"
                    "Le bot continue mais surveille !"
                )
                balance_alerted = True
            elif balance >= MIN_BALANCE_ALERT:
                balance_alerted = False

            # ── Vérifier la fenêtre de trading ──
            can_trade, session = is_good_trading_time()

            if not can_trade:
                if not pause_alerted:
                    log.info(f"Pause: {session}")
                    send_telegram(f"⏸️ <b>Pause trading</b>\n📌 {session}")
                    pause_alerted = True

                # Surveiller quand même les trades ouverts pendant la pause
                for symbol in list(open_trades.keys()):
                    trade    = open_trades[symbol]
                    price    = get_price(client, symbol)
                    if price == 0:
                        continue
                    change   = (price - trade["buy_price"]) / trade["buy_price"]
                    trailing = (price - trade["highest"])   / trade["highest"]
                    if price > trade["highest"]:
                        open_trades[symbol]["highest"] = price
                    if change <= -STOP_LOSS_PCT:
                        place_sell(client, trade, "STOP-LOSS", daily_stats)
                        last_trades[symbol] = datetime.now()
                        del open_trades[symbol]
                    elif trailing <= -TRAILING_STOP_PCT and change > 0:
                        place_sell(client, trade, "TRAILING-STOP", daily_stats)
                        last_trades[symbol] = datetime.now()
                        del open_trades[symbol]
                    elif change >= TAKE_PROFIT_PCT:
                        place_sell(client, trade, "TAKE-PROFIT", daily_stats)
                        last_trades[symbol] = datetime.now()
                        del open_trades[symbol]

                time.sleep(300)
                continue

            # Fenêtre active
            if pause_alerted:
                send_telegram(f"▶️ <b>Trading reprend !</b>\n📌 {session}")
                pause_alerted = False

            log.info(f"[{session}] Balance: {balance:.2f} | Trades: {len(open_trades)}/{MAX_OPEN_TRADES}")

            for symbol in PAIRS:
                price = get_price(client, symbol)
                if price == 0:
                    continue

                # ── Gérer trades ouverts ──
                if symbol in open_trades:
                    trade    = open_trades[symbol]
                    change   = (price - trade["buy_price"]) / trade["buy_price"]
                    trailing = (price - trade["highest"])   / trade["highest"]

                    if price > trade["highest"]:
                        open_trades[symbol]["highest"] = price

                    if change <= -STOP_LOSS_PCT:
                        place_sell(client, trade, "STOP-LOSS", daily_stats)
                        last_trades[symbol] = datetime.now()
                        del open_trades[symbol]
                    elif trailing <= -TRAILING_STOP_PCT and change > 0:
                        place_sell(client, trade, "TRAILING-STOP", daily_stats)
                        last_trades[symbol] = datetime.now()
                        del open_trades[symbol]
                    elif change >= TAKE_PROFIT_PCT:
                        place_sell(client, trade, "TAKE-PROFIT", daily_stats)
                        last_trades[symbol] = datetime.now()
                        del open_trades[symbol]
                    elif get_signal(client, symbol) == "SELL":
                        place_sell(client, trade, "SIGNAL", daily_stats)
                        last_trades[symbol] = datetime.now()
                        del open_trades[symbol]
                    continue

                # ── Chercher nouveaux signaux ──
                if len(open_trades) >= MAX_OPEN_TRADES:
                    continue
                if balance < 10:
                    continue
                if is_on_cooldown(last_trades, symbol):
                    continue
                if is_pump_or_dump(client, symbol):
                    continue

                signal = get_signal(client, symbol)
                log.info(f"{symbol} | {price:.4f} | {signal}")

                if signal == "BUY":
                    trade = place_buy(client, symbol, balance, session)
                    if trade:
                        open_trades[symbol]  = trade
                        last_trades[symbol]  = datetime.now()
                        balance              = get_balance(client)

        except Exception as e:
            log.error(f"Erreur boucle principale: {e}")
            send_telegram(f"⚠️ <b>Erreur bot:</b> {e}")
            # Tentative de reconnexion si erreur réseau
            if "connection" in str(e).lower() or "timeout" in str(e).lower():
                try:
                    client_ref[0] = create_client()
                except:
                    pass

        time.sleep(TRADE_INTERVAL)

# ══════════════════════════════════════════════
#  DÉMARRAGE
# ══════════════════════════════════════════════
if __name__ == "__main__":
    threading.Thread(target=start_health_server, daemon=True).start()
    run_bot()
