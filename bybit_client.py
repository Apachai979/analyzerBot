from pybit.unified_trading import HTTP
from datetime import datetime
from config import (
    BYBIT_API_KEY, BYBIT_API_SECRET, TESTNET, BYBIT_API_URL, BYBIT_TESTNET_URL,
    CATEGORY, INTERVAL, LIMIT
)
from coinmarketcap_client import get_coinmarketcap_data, get_fear_greed_index

class BybitClient:
    def __init__(self):
        self.api_key = BYBIT_API_KEY
        self.api_secret = BYBIT_API_SECRET
        self.base_url = BYBIT_TESTNET_URL if TESTNET else BYBIT_API_URL
        self.session = None
        self._initialize_session()
    
    def _initialize_session(self):
        """Инициализирует сессию с Bybit"""
        try:
            self.session = HTTP(
                api_key=self.api_key,
                api_secret=self.api_secret,
                testnet=TESTNET
            )
        except Exception as e:
            print(f"❌ Ошибка инициализации сессии Bybit: {e}")
            self.session = None

    def get_klines(self, symbol, interval=INTERVAL, limit=LIMIT):
        """Получаем исторические данные для конкретной монеты"""
        try:
            if not self.session:
                self._initialize_session()
                if not self.session:
                    return None
            
            response = self.session.get_kline(
                category=CATEGORY,
                symbol=symbol,
                interval=interval,
                limit=limit
            )
            
            if response['retCode'] != 0:
                print(f"❌ Ошибка API при получении свечей {symbol}: {response['retMsg']}")
                return None
            
            klines = response['result']['list']
            import pandas as pd
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
            print(f"❌ Ошибка при получении данных {symbol}: {e}")
            return None

    def get_orderbook(self, symbol, levels, whale_size=None):
        """Получает стакан цен для конкретной монеты и анализирует крупные ордера"""
        try:
            if not self.session:
                self._initialize_session()
                if not self.session:
                    return None, None, None, None, None, None
            
            response = self.session.get_orderbook(
                category=CATEGORY,
                symbol=symbol,
                limit=levels * 3  # Берем в 3 раза больше для анализа
            )
            
            if response['retCode'] != 0:
                print(f"❌ Ошибка API при получении стакана {symbol}: {response['retMsg']}")
                return None, None, None, None, None, None
            
            bids = response['result']['b']
            asks = response['result']['a']
            
            bid_volume = sum(float(bid[1]) for bid in bids[:levels]) if bids else 0
            ask_volume = sum(float(ask[1]) for ask in asks[:levels]) if asks else 0

            whale_bids = []
            whale_asks = []
            if whale_size is not None:
                whale_bids = [order for order in bids if float(order[1]) >= whale_size]
                whale_asks = [order for order in asks if float(order[1]) >= whale_size]
            
            return bids, asks, bid_volume, ask_volume, whale_bids, whale_asks
            
        except Exception as e:
            print(f"❌ Ошибка при получении стакана {symbol}: {e}")
            return None, None, None, None, None, None

    def get_current_price(self, symbol):
        """Получаем текущую цену для конкретной монеты"""
        try:
            if not self.session:
                self._initialize_session()
                if not self.session:
                    return None
            
            response = self.session.get_tickers(
                category=CATEGORY,
                symbol=symbol
            )
            
            if response['retCode'] != 0:
                print(f"❌ Ошибка API при получении цены {symbol}: {response['retMsg']}")
                return None
            
            last_price = response['result']['list'][0]['lastPrice']
            return float(last_price)
            
        except Exception as e:
            print(f"❌ Ошибка при получении цены {symbol}: {e}")
            return None

    def get_multiple_prices(self, symbols):
        """Получает цены для нескольких монет одновременно"""
        try:
            if not self.session:
                self._initialize_session()
                if not self.session:
                    return {}
            
            response = self.session.get_tickers(
                category=CATEGORY,
                symbol=','.join(symbols)
            )
            
            if response['retCode'] != 0:
                print(f"❌ Ошибка API при получении цен: {response['retMsg']}")
                return {}
            
            prices = {}
            for item in response['result']['list']:
                symbol = item['symbol']
                prices[symbol] = float(item['lastPrice'])
            
            return prices
            
        except Exception as e:
            print(f"❌ Ошибка при получении цен: {e}")
            return {}

    def test_connection(self):
        """Проверяет соединение с Bybit API"""
        try:
            if not self.session:
                self._initialize_session()
            
            response = self.session.get_tickers(
                category=CATEGORY,
                symbol="BTCUSDT"
            )
            
            if response['retCode'] == 0:
                print("✅ Соединение с Bybit API установлено успешно")
                return True
            else:
                print(f"❌ Ошибка соединения с Bybit API: {response['retMsg']}")
                return False
                
        except Exception as e:
            print(f"❌ Ошибка соединения с Bybit API: {e}")
            return False

# Глобальный экземпляр клиента
bybit_client = BybitClient()

def get_bybit_client():
    """Возвращает глобальный экземпляр Bybit клиента"""
    return bybit_client