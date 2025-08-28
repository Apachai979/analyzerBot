from pybit.unified_trading import HTTP
import pandas as pd
import requests
from datetime import datetime
from config import *

def get_klines_data(symbol):
    """Получаем исторические данные для конкретной монеты"""
    try:
        session = HTTP(testnet=False)
        response = session.get_kline(
            category=CATEGORY,
            symbol=symbol,
            interval=INTERVAL,
            limit=LIMIT
        )
        
        if response['retCode'] != 0:
            print(f"Ошибка API при получении свечей {symbol}: {response['retMsg']}")
            return None
        
        klines = response['result']['list']
        df = pd.DataFrame(klines, columns=[
            'timestamp', 'open', 'high', 'low', 'close', 'volume', 'turnover'
        ])
        
        numeric_columns = ['open', 'high', 'low', 'close', 'volume', 'turnover']
        for col in numeric_columns:
            df[col] = pd.to_numeric(df[col])
        
        df['timestamp'] = pd.to_numeric(df['timestamp'])
        df = df.sort_values('timestamp').reset_index(drop=True)
        
        return df
        
    except Exception as e:
        print(f"Ошибка при получении данных {symbol}: {e}")
        return None

def get_current_price(symbol):
    """Получаем текущую цену для конкретной монеты"""
    try:
        session = HTTP(testnet=False)
        response = session.get_tickers(
            category=CATEGORY,
            symbol=symbol
        )
        
        if response['retCode'] != 0:
            print(f"Ошибка API при получении цены {symbol}: {response['retMsg']}")
            return None
        
        last_price = response['result']['list'][0]['lastPrice']
        return float(last_price)
        
    except Exception as e:
        print(f"Ошибка при получении цены {symbol}: {e}")
        return None

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
            # ...existing code...
            historical_records.append({
                'timestamp': item['timestamp'],
                'value': float(item['value']),
                'value_classification': item['value_classification']
            })
# ...existing code...
        
        latest_value = latest_data['data']['value']
        latest_classification = latest_data['data']['value_classification']
        
        return {
            'current_value': latest_value,
            'current_classification': latest_classification,
            'historical': historical_records,
            'average_30d': sum(item['value'] for item in historical_records) / len(historical_records)
        }
        
    except Exception as e:
        print(f"❌ Ошибка получения Fear and Greed Index: {e}")
        return None

def get_orderbook_data(symbol, config):
    """Получает и анализирует стакан цен для конкретной монеты"""
    try:
        session = HTTP(testnet=False)
        response = session.get_orderbook(
            category=CATEGORY,
            symbol=symbol,
            limit=config.orderbook_levels * 3
        )
        
        if response['retCode'] != 0:
            print(f"Ошибка API при получении стакана {symbol}: {response['retMsg']}")
            return None, None, None, None, None, None
        
        bids = response['result']['b']
        asks = response['result']['a']
        
        bid_volume = sum(float(bid[1]) for bid in bids[:config.orderbook_levels])
        ask_volume = sum(float(ask[1]) for ask in asks[:config.orderbook_levels])
        
        whale_bids = [order for order in bids if float(order[1]) >= config.whale_size]
        whale_asks = [order for order in asks if float(order[1]) >= config.whale_size]
        
        return bids, asks, bid_volume, ask_volume, whale_bids, whale_asks
        
    except Exception as e:
        print(f"Ошибка при получении стакана {symbol}: {e}")
        return None, None, None, None, None, None