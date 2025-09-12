import requests
from config import COINMARKETCAP_API_KEY, CMC_API_URL, CMC_FGI_URL, CMC_FGI_LATEST

CMC_API_URL = "https://pro-api.coinmarketcap.com/v2/cryptocurrency/quotes/latest"
CMC_FGI_URL = "https://pro-api.coinmarketcap.com/v3/fear-and-greed/historical"
CMC_FGI_LATEST = "https://pro-api.coinmarketcap.com/v3/fear-and-greed/latest"

import requests
from config import COINMARKETCAP_API_KEY, CMC_API_URL

def get_coinmarketcap_data(symbols):
    """
    Получает рыночные данные с CoinMarketCap API для списка монет.
    Возвращает словарь с расширенными данными для каждой монеты.
    """
    try:
        # Преобразуем тикеры к формату CoinMarketCap (убираем 'USDT')
        cmc_symbols = [symbol.replace("USDT", "") for symbol in symbols]
        headers = {
            'Accepts': 'application/json',
            'X-CMC_PRO_API_KEY': COINMARKETCAP_API_KEY,
        }
        params = {
            'symbol': ",".join(cmc_symbols),
            'convert': 'USD'
        }
        response = requests.get(CMC_API_URL, headers=headers, params=params)
        response.raise_for_status()
        data = response.json()

        results = {}
        for cmc_symbol in cmc_symbols:
            try:
                coin_data = data['data'][cmc_symbol]
                coin = next((c for c in coin_data if c.get('is_active', 0) == 1), coin_data[0])
                quote = coin['quote']['USD']
                results[cmc_symbol] = {
                    'id': coin.get('id'),
                    'name': coin.get('name'),
                    'symbol': cmc_symbol,
                    'slug': coin.get('slug'),
                    'num_market_pairs': coin.get('num_market_pairs'),
                    'date_added': coin.get('date_added'),
                    'tags': coin.get('tags'),
                    'max_supply': coin.get('max_supply'),
                    'circulating_supply': coin.get('circulating_supply'),
                    'total_supply': coin.get('total_supply'),
                    'platform': coin.get('platform'),
                    'is_active': coin.get('is_active'),
                    'infinite_supply': coin.get('infinite_supply'),
                    'cmc_rank': coin.get('cmc_rank'),
                    'is_fiat': coin.get('is_fiat'),
                    'self_reported_circulating_supply': coin.get('self_reported_circulating_supply'),
                    'self_reported_market_cap': coin.get('self_reported_market_cap'),
                    'tvl_ratio': coin.get('tvl_ratio'),
                    'last_updated': coin.get('last_updated'),
                    'price': quote.get('price'),
                    'volume_24h': quote.get('volume_24h'),
                    'volume_change_24h': quote.get('volume_change_24h'),
                    'percent_change_1h': quote.get('percent_change_1h'),
                    'percent_change_24h': quote.get('percent_change_24h'),
                    'percent_change_7d': quote.get('percent_change_7d'),
                    'percent_change_30d': quote.get('percent_change_30d'),
                    'percent_change_60d': quote.get('percent_change_60d'),
                    'percent_change_90d': quote.get('percent_change_90d'),
                    'market_cap': quote.get('market_cap'),
                    'market_cap_dominance': quote.get('market_cap_dominance'),
                    'fully_diluted_market_cap': quote.get('fully_diluted_market_cap'),
                    'tvl': quote.get('tvl'),
                    'quote_last_updated': quote.get('last_updated'),
                    'volume_mcap_ratio': quote.get('volume_24h') / quote.get('market_cap') if quote.get('market_cap') else 0,
                    'platform_id': coin['platform']['id'] if coin.get('platform') else None,
                    'platform_name': coin['platform']['name'] if coin.get('platform') else None,
                    'platform_symbol': coin['platform']['symbol'] if coin.get('platform') else None,
                    'platform_slug': coin['platform']['slug'] if coin.get('platform') else None,
                    'platform_token_address': coin['platform']['token_address'] if coin.get('platform') and 'token_address' in coin['platform'] else None,
                }
            except Exception as e:
                results[cmc_symbol] = {'error': f'Ошибка обработки данных: {e}'}
        return results

    except Exception as e:
        print(f"❌ Ошибка получения данных CoinMarketCap: {e}")
        return None

# Пример использования:
# symbols = ['BTCUSDT', 'ETHUSDT', 'TAUSDT']
# market_data = get_coinmarketcap_data(symbols)
# print(market_data)

def get_fear_greed_index(days=30):
    """Получает исторические данные Fear and Greed Index"""
    try:
        headers = {
            'Accepts': 'application/json',
            'X-CMC_PRO_API_KEY': COINMARKETCAP_API_KEY,
        }
        historical_response = requests.get(CMC_FGI_URL, headers=headers)
        historical_response.raise_for_status()
        historical_data = historical_response.json()
        latest_response = requests.get(CMC_FGI_LATEST, headers=headers)
        latest_response.raise_for_status()
        latest_data = latest_response.json()
        historical_records = []
        for item in historical_data['data'][:days]:
            historical_records.append({
                'timestamp': item['timestamp'],
                'value': float(item['value']),
                'value_classification': item['value_classification']
            })
        latest_value = float(latest_data['data']['value'])
        latest_classification = latest_data['data']['value_classification']
        return {
            'current_value': latest_value,
            'current_classification': latest_classification,
            'historical': historical_records,
            'average_30d': sum(item['value'] for item in historical_records) / len(historical_records) if historical_records else 0
        }
    except Exception as e:
        print(f"❌ Ошибка получения Fear and Greed Index: {e}")
        return None
    
def analyze_fgi_trend(fgi_data):
    """
    Анализирует тренд Fear and Greed Index, сравнивает текущее значение с средним,
    возвращает выводы, текущее значение и classification.
    """
    if not fgi_data or not fgi_data.get('historical'):
        return {
            "trend": "Нет данных",
            "current_vs_avg": "Нет данных",
            "current_value": None,
            "classification": None
        }

    historical = fgi_data['historical']
    values = [item['value'] for item in historical]
    current_value = fgi_data['current_value']
    classification = fgi_data['current_classification']
    average_30d = fgi_data['average_30d']

    # Тренд: сравниваем первые и последние значения
    if len(values) >= 2:
        if values[-1] > values[0]:
            trend = "Жадность растет"
        elif values[-1] < values[0]:
            trend = "Страх растет"
        else:
            trend = "Тренд не изменился"
    else:
        trend = "Недостаточно данных для тренда"

    # Сравнение текущего значения с средним
    if current_value > average_30d:
        current_vs_avg = "Текущее значение выше среднего"
    elif current_value < average_30d:
        current_vs_avg = "Текущее значение ниже среднего"
    else:
        current_vs_avg = "Текущее значение равно среднему"

    return {
        "trend": trend,
        "current_vs_avg": current_vs_avg,
        "current_value": current_value,
        "classification": classification
    }
    
def analyze_cmc_response(cmc_response, symbol):
    """
    Анализирует данные CoinMarketCap и выводит рекомендации для трейдера.
    """
    if not cmc_response or 'data' not in cmc_response or symbol not in cmc_response['data']:
        print("Нет данных для анализа.")
        return

    # Берём первую активную монету с нужным тикером
    coins = [coin for coin in cmc_response['data'][symbol] if coin.get('is_active', 0) == 1]
    if not coins:
        print("Нет активных монет для анализа.")
        return

    coin = coins[0]
    quote = coin['quote']['USD']

    price = quote.get('price')
    market_cap = quote.get('market_cap')
    volume_24h = quote.get('volume_24h')
    volume_change_24h = quote.get('volume_change_24h')
    percent_change_24h = quote.get('percent_change_24h')
    percent_change_7d = quote.get('percent_change_7d')
    percent_change_30d = quote.get('percent_change_30d')

    # Анализ волатильности и тренда
    insights = []
    if volume_24h and market_cap and market_cap > 0:
        volume_mcap_ratio = volume_24h / market_cap
        if volume_mcap_ratio > 2:
            insights.append("Монета волатильна и интересна для краткосрочных сделок.")
        elif volume_mcap_ratio > 0.5:
            insights.append("Высокий объем может означать продолжение волатильности.")

    if percent_change_30d and percent_change_30d > 50:
        if percent_change_24h and percent_change_24h < 0:
            insights.append("Сейчас идет коррекция после сильного роста.")
        else:
            insights.append("Монета находится в фазе роста.")

    if percent_change_24h and abs(percent_change_24h) > 10:
        insights.append("Требуется осторожность: возможны резкие движения как вверх, так и вниз.")

    # Выводим результат
    print(f"\nАнализ монеты {coin['name']} ({symbol}):")
    print(f"Цена: ${price:.4f}" if price else "Цена: нет данных")
    print(f"Рыночная капитализация: ${market_cap:,.0f}" if market_cap else "Рыночная капитализация: нет данных")
    print(f"Объем торгов за 24ч: ${volume_24h:,.0f}" if volume_24h else "Объем торгов за 24ч: нет данных")
    print(f"Изменение цены за 24ч: {percent_change_24h:+.2f}%" if percent_change_24h is not None else "Изменение цены за 24ч: нет данных")
    print(f"Изменение цены за 7 дней: {percent_change_7d:+.2f}%" if percent_change_7d is not None else "Изменение цены за 7 дней: нет данных")
    print(f"Изменение цены за 30 дней: {percent_change_30d:+.2f}%" if percent_change_30d is not None else "Изменение цены за 30 дней: нет данных")
    print("\nВыводы для трейдера:")
    for insight in insights:
        print(f"- {insight}")
    if not insights:
        print("- Нет ярко выраженных сигналов.")

# Пример использования:
# analyze_cmc_response(cmc_response, 'TA')