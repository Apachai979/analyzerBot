import time
import os
from datetime import datetime
from bybit_client import bybit_client
from coinmarketcap_client import get_coinmarketcap_data
from telegram_utils import send_telegram_message
from config import (
    GAIN_12H, DROP_12H, GAIN_4H, DROP_4H, GAIN_2H, DROP_2H, MIN_MARKET_CAP
)

DYNAMIC_SYMBOLS_FILE = "data/dynamic_symbols.txt"
LOWCAP_SYMBOLS_FILE = "data/lowcap_symbols.txt"
KNOWN_SYMBOLS_FILE = "data/known_spot_symbols.txt"

def load_dynamic_symbols():
    try:
        with open(DYNAMIC_SYMBOLS_FILE, "r", encoding="utf-8") as f:
            return [line.strip() for line in f if line.strip()]
    except FileNotFoundError:
        return []

def save_dynamic_symbol(symbol):
    with open(DYNAMIC_SYMBOLS_FILE, "a", encoding="utf-8") as f:
        f.write(symbol + "\n")

def load_lowcap_symbols():
    try:
        with open(LOWCAP_SYMBOLS_FILE, "r", encoding="utf-8") as f:
            return set(line.strip() for line in f if line.strip())
    except FileNotFoundError:
        return set()

def save_lowcap_symbol(symbol):
    with open(LOWCAP_SYMBOLS_FILE, "a", encoding="utf-8") as f:
        f.write(symbol + "\n")

def load_known_symbols():
    if not os.path.exists(KNOWN_SYMBOLS_FILE):
        return set()
    with open(KNOWN_SYMBOLS_FILE, "r", encoding="utf-8") as f:
        return set(line.strip() for line in f if line.strip())

def save_known_symbols(symbols):
    with open(KNOWN_SYMBOLS_FILE, "w", encoding="utf-8") as f:
        for symbol in sorted(symbols):
            f.write(symbol + "\n")

def get_spot_symbols():
    try:
        info = bybit_client.session.get_instruments_info(category="spot")
        if info['retCode'] != 0:
            print("Ошибка получения списка пар:", info['retMsg'])
            return []
        return [item['symbol'] for item in info['result']['list']]
    except Exception as e:
        print("Ошибка получения списка пар:", e)
        return []

def check_spot_trends():
    dynamic_symbols = load_dynamic_symbols()
    dynamic_symbols_set = set(dynamic_symbols)
    lowcap_symbols_set = load_lowcap_symbols()
    symbols = get_spot_symbols()
    print(f"[{datetime.now()}] Проверка {len(symbols)} спотовых пар...")
    for symbol in symbols:
        try:
            if symbol in dynamic_symbols_set or symbol in lowcap_symbols_set:
                continue

            df = bybit_client.get_klines(symbol, interval="15", limit=48)  # 12 часов
            time.sleep(0.2)
            if df is None or len(df) < 32:
                continue

            price_now = float(df['close'].iloc[-1])
            price_2h_ago = float(df['close'].iloc[-8])
            price_4h_ago = float(df['close'].iloc[-16])
            price_12h_ago = float(df['close'].iloc[0])

            growth_2h = (price_now - price_2h_ago) / price_2h_ago * 100
            growth_4h = (price_now - price_4h_ago) / price_4h_ago * 100
            growth_12h = (price_now - price_12h_ago) / price_12h_ago * 100

            trigger = None
            if growth_12h > GAIN_12H:
                trigger = f"🚀 Рост за 12ч: <b>{growth_12h:.2f}%</b>"
            elif growth_12h < DROP_12H:
                trigger = f"⚠️ Падение за 12ч: <b>{growth_12h:.2f}%</b>"
            elif growth_4h > GAIN_4H:
                trigger = f"🚀 Рост за 4ч: <b>{growth_4h:.2f}%</b>"
            elif growth_4h < DROP_4H:
                trigger = f"⚠️ Падение за 4ч: <b>{growth_4h:.2f}%</b>"
            elif growth_2h > GAIN_2H:
                trigger = f"🚀 Рост за 2ч: <b>{growth_2h:.2f}%</b>"
            elif growth_2h < DROP_2H:
                trigger = f"⚠️ Падение за 2ч: <b>{growth_2h:.2f}%</b>"

            if trigger:
                market_data = get_coinmarketcap_data(symbol)
                if not market_data:
                    print(f"Нет данных CMC для {symbol}, пропуск.")
                    continue
                market_cap = market_data.get('market_cap', 0)
                if market_cap < MIN_MARKET_CAP:
                    print(f"{symbol}: капитализация {market_cap:.0f} < {MIN_MARKET_CAP:,}, пропуск.")
                    save_lowcap_symbol(symbol)
                    lowcap_symbols_set.add(symbol)
                    continue

                msg = (
                    f"{trigger}\n"
                    f"<b>{symbol}</b>\n"
                    f"Текущий курс: <b>{price_now:.6f}</b>\n"
                    f"Курс 2ч назад: <b>{price_2h_ago:.6f}</b>\n"
                    f"Курс 4ч назад: <b>{price_4h_ago:.6f}</b>\n"
                    f"Курс 12ч назад: <b>{price_12h_ago:.6f}</b>"
                )
                send_telegram_message(msg)
                save_dynamic_symbol(symbol)
                dynamic_symbols_set.add(symbol)
                print(f"Добавлена новая пара для анализа и сохранена: {symbol}")
        except Exception as e:
            print(f"Ошибка анализа {symbol}: {e}")

def check_new_spot_pairs():
    known_symbols = load_known_symbols()
    try:
        info = bybit_client.session.get_instruments_info(category="spot")
        if info['retCode'] != 0:
            print("Ошибка получения списка пар:", info['retMsg'])
            return
        current_symbols = set(item['symbol'] for item in info['result']['list'])
    except Exception as e:
        print("Ошибка получения списка пар:", e)
        return

    new_symbols = current_symbols - known_symbols
    if new_symbols:
        for symbol in new_symbols:
            msg = f"🆕 Новая спотовая пара на Bybit: <b>{symbol}</b>"
            send_telegram_message(msg)
            print(f"Найдена новая пара: {symbol}")
    else:
        print("Новых пар не найдено.")

    # Файл будет обновляться всегда, даже если новых пар нет
    save_known_symbols(current_symbols)

# Для периодического вызова:
def spot_trend_watcher_loop():
    while True:
        check_spot_trends()
        time.sleep(600)  # 10 минут

def new_pairs_watcher_loop():
    while True:
        check_new_spot_pairs()
        time.sleep(600)  # Проверять каждые 10 минут