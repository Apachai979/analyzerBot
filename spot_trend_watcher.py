import time
import os
from datetime import datetime
from bybit_client import bybit_client
from coinmarketcap_client import get_coinmarketcap_data
from config import MIN_MARKET_CAP

FILTERED_SYMBOLS_FILE = "data/filtered_symbols.txt"

def filter_and_sort_symbols():
    """
    Получает все спотовые пары с Bybit, фильтрует по капитализации и объему,
    сортирует по капитализации в порядке убывания и сохраняет в файл.
    """
    try:
        # Получаем все спотовые пары с Bybit
        print(f"[{datetime.now()}] Получение списка спотовых пар...")
        info = bybit_client.session.get_instruments_info(category="spot")
        
        if info['retCode'] != 0:
            print("Ошибка получения списка пар:", info['retMsg'])
            return
        
        symbols = [item['symbol'] for item in info['result']['list']]
        print(f"[{datetime.now()}] Найдено {len(symbols)} спотовых пар")
        
        # Получаем данные с CoinMarketCap для всех пар
        print(f"[{datetime.now()}] Получение данных с CoinMarketCap...")
        cmc_data = get_coinmarketcap_data(symbols)
        
        # Фильтруем и собираем данные
        filtered_coins = []
        
        for symbol in symbols:
            # Извлекаем базовую валюту (убираем USDT)
            base_currency = symbol.replace("USDT", "")
            market_data = cmc_data.get(base_currency, {})
            
            market_cap = market_data.get('market_cap', 0) or 0
            volume_24h = market_data.get('volume_24h', 0) or 0
            
            # Применяем условие фильтрации (инвертированное - берем те, что НЕ проходят условие)
            # Если market_cap < MIN_MARKET_CAP или volume_24h < 1_000_000, то пропускаем
            if market_cap >= MIN_MARKET_CAP and volume_24h >= 1_000_000:
                filtered_coins.append({
                    'symbol': symbol,
                    'market_cap': market_cap,
                    'volume_24h': volume_24h
                })
        
        print(f"[{datetime.now()}] После фильтрации осталось {len(filtered_coins)} пар")
        
        # Сортируем по капитализации в порядке убывания
        filtered_coins.sort(key=lambda x: x['market_cap'], reverse=True)
        
        # Создаем директорию, если её нет
        os.makedirs("data", exist_ok=True)
        
        # Записываем в файл
        with open(FILTERED_SYMBOLS_FILE, "w", encoding="utf-8") as f:
            for coin in filtered_coins:
                f.write(f"{coin['symbol']}\n")
        
        print(f"[{datetime.now()}] Данные сохранены в {FILTERED_SYMBOLS_FILE}")
        print(f"Топ-10 монет по капитализации:")
        for i, coin in enumerate(filtered_coins[:10], 1):
            print(f"{i}. {coin['symbol']} - Market Cap: ${coin['market_cap']:,.0f}, Volume 24h: ${coin['volume_24h']:,.0f}")
        
    except Exception as e:
        print(f"Ошибка при фильтрации символов: {e}")

def main():
    """Основная функция для запуска фильтрации"""
    filter_and_sort_symbols()

if __name__ == "__main__":
    main()