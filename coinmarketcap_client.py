import requests
from config import COINMARKETCAP_API_KEY, CMC_API_URL, CMC_FGI_URL, CMC_FGI_LATEST

def get_coinmarketcap_data(symbol):
    """Получает рыночные данные с CoinMarketCap API"""
    try:
        symbol_mapping = {
            "BTCUSDT": "BTC",
            "ETHUSDT": "ETH", 
            "TONUSDT": "TON",
            "SOLUSDT": "SOL",
            "ADAUSDT": "ADA"
        }
        cmc_symbol = symbol_mapping.get(symbol, symbol.replace("USDT", ""))
        headers = {
            'Accepts': 'application/json',
            'X-CMC_PRO_API_KEY': COINMARKETCAP_API_KEY,
        }
        params = {
            'symbol': cmc_symbol,
            'convert': 'USD'
        }
        response = requests.get(CMC_API_URL, headers=headers, params=params)
        response.raise_for_status()
        data = response.json()
        quote_data = data['data'][cmc_symbol][0]['quote']['USD']
        return {
            'price': quote_data['price'],
            'volume_24h': quote_data['volume_24h'],
            'market_cap': quote_data['market_cap'],
            'volume_change_24h': quote_data.get('volume_change_24h', 0),
            'market_cap_change_24h': quote_data.get('market_cap_change_24h', 0),
            'volume_mcap_ratio': quote_data['volume_24h'] / quote_data['market_cap'] if quote_data['market_cap'] > 0 else 0
        }
    except Exception as e:
        print(f"❌ Ошибка получения данных CoinMarketCap для {symbol}: {e}")
        return None

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