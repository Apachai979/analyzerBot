import time
import os
from datetime import datetime
from bybit_client import bybit_client
from coinmarketcap_client import get_coinmarketcap_data
from config import MIN_MARKET_CAP

FILTERED_SYMBOLS_FILE = "data/filtered_symbols.txt"

def filter_and_sort_symbols():
    """
    Получает все спотовые пары с Bybit, читает существующий список из файла,
    добавляет новые пары (которых нет в файле) если они проходят фильтрацию,
    сортирует по капитализации в порядке убывания и сохраняет в файл.
    """
    try:
        # Создаем директорию, если её нет
        os.makedirs("data", exist_ok=True)
        
        # Читаем существующий список символов из файла
        existing_symbols = set()
        if os.path.exists(FILTERED_SYMBOLS_FILE):
            with open(FILTERED_SYMBOLS_FILE, "r", encoding="utf-8") as f:
                existing_symbols = set(line.strip() for line in f if line.strip())
            print(f"[{datetime.now()}] Загружено {len(existing_symbols)} существующих пар из файла")
        
        # Получаем все спотовые пары с Bybit
        print(f"[{datetime.now()}] Получение списка спотовых пар...")
        info = bybit_client.session.get_instruments_info(category="spot")
        
        if info['retCode'] != 0:
            print("Ошибка получения списка пар:", info['retMsg'])
            return
        
        all_symbols = [item['symbol'] for item in info['result']['list']]
        print(f"[{datetime.now()}] Найдено {len(all_symbols)} спотовых пар на Bybit")
        
        # Находим новые пары (которых нет в существующем списке)
        new_symbols = [s for s in all_symbols if s not in existing_symbols]
        print(f"[{datetime.now()}] Обнаружено {len(new_symbols)} новых пар")
        
        if not new_symbols:
            print(f"[{datetime.now()}] Новых пар не найдено, файл не изменён")
            print(f"\n{'='*60}")
            print(f"Общее количество пар в файле: {len(existing_symbols)}")
            print(f"Новые добавленные пары: 0")
            print(f"{'='*60}")
            return
        
        # Получаем данные с CoinMarketCap только для новых пар
        print(f"[{datetime.now()}] Получение данных с CoinMarketCap для новых пар...")
        cmc_data = get_coinmarketcap_data(new_symbols)
        
        # Фильтруем новые пары
        newly_filtered = []
        for symbol in new_symbols:
            base_currency = symbol.replace("USDT", "")
            market_data = cmc_data.get(base_currency, {})
            
            market_cap = market_data.get('market_cap', 0) or 0
            volume_24h = market_data.get('volume_24h', 0) or 0
            
            if market_cap >= MIN_MARKET_CAP and volume_24h >= 1_000_000:
                newly_filtered.append({
                    'symbol': symbol,
                    'market_cap': market_cap,
                    'volume_24h': volume_24h
                })
        
        print(f"[{datetime.now()}] Из новых пар прошло фильтрацию: {len(newly_filtered)}")
        
        # Объединяем существующие пары с новыми
        # Для существующих пар получаем капитализацию для сортировки
        print(f"[{datetime.now()}] Получение данных для всех пар для сортировки...")
        all_pairs_for_sort = list(existing_symbols) + [c['symbol'] for c in newly_filtered]
        all_cmc_data = get_coinmarketcap_data(all_pairs_for_sort)
        
        all_coins = []
        for symbol in all_pairs_for_sort:
            base_currency = symbol.replace("USDT", "")
            market_data = all_cmc_data.get(base_currency, {})
            market_cap = market_data.get('market_cap', 0) or 0
            volume_24h = market_data.get('volume_24h', 0) or 0
            all_coins.append({
                'symbol': symbol,
                'market_cap': market_cap,
                'volume_24h': volume_24h
            })
        
        # Сортируем по капитализации в порядке убывания
        all_coins.sort(key=lambda x: x['market_cap'], reverse=True)
        
        # Записываем в файл
        with open(FILTERED_SYMBOLS_FILE, "w", encoding="utf-8") as f:
            for coin in all_coins:
                f.write(f"{coin['symbol']}\n")
        
        print(f"[{datetime.now()}] Данные обновлены и сохранены в {FILTERED_SYMBOLS_FILE}")
        print(f"\nТоп-10 монет по капитализации:")
        for i, coin in enumerate(all_coins[:10], 1):
            print(f"{i}. {coin['symbol']} - Market Cap: ${coin['market_cap']:,.0f}, Volume 24h: ${coin['volume_24h']:,.0f}")
        
        # Итоговая статистика
        print(f"\n{'='*60}")
        print(f"Общее количество пар в файле: {len(all_coins)}")
        print(f"Новые добавленные пары: {len(newly_filtered)}")
        if newly_filtered:
            print(f"\nСписок новых пар:")
            for coin in newly_filtered:
                print(f"  • {coin['symbol']} - Market Cap: ${coin['market_cap']:,.0f}, Volume 24h: ${coin['volume_24h']:,.0f}")
        print(f"{'='*60}")
        
    except Exception as e:
        print(f"Ошибка при фильтрации символов: {e}")

def main():
    """Основная функция для запуска фильтрации"""
    filter_and_sort_symbols()

if __name__ == "__main__":
    main()