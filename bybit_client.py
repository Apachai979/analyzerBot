from pybit.unified_trading import HTTP
from datetime import datetime
import time
from collections import deque
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
        
        # Rate limiting: Bybit allows ~120 requests/minute
        # We'll use conservative 100 requests/minute = 1.67 req/sec
        self.rate_limit = 100  # requests per minute
        self.rate_window = 60  # seconds
        self.min_request_interval = 0.6  # seconds between requests (100 req/min = 1 req per 0.6s)
        self.request_times = deque(maxlen=self.rate_limit)
        self.last_request_time = 0
        
        self._initialize_session()
    
    def _initialize_session(self):
        """Инициализирует сессию с Bybit"""
        try:
            self.session = HTTP(
                api_key=self.api_key,
                api_secret=self.api_secret,
                testnet=TESTNET,
                recv_window=5000  # 5 seconds window (default recommended by Bybit)
            )
        except Exception as e:
            print(f"❌ Ошибка инициализации сессии Bybit: {e}")
            self.session = None
    
    def _wait_for_rate_limit(self):
        """
        Защита от превышения rate limit Bybit.
        Bybit: ~120 req/min. Используем консервативный лимит 100 req/min.
        """
        current_time = time.time()
        
        # Минимальный интервал между запросами (0.6 сек)
        time_since_last = current_time - self.last_request_time
        if time_since_last < self.min_request_interval:
            sleep_time = self.min_request_interval - time_since_last
            time.sleep(sleep_time)
            current_time = time.time()
        
        # Проверка скользящего окна (100 запросов за 60 секунд)
        self.request_times.append(current_time)
        if len(self.request_times) >= self.rate_limit:
            oldest_time = self.request_times[0]
            time_diff = current_time - oldest_time
            if time_diff < self.rate_window:
                sleep_time = self.rate_window - time_diff + 0.1  # +0.1 для безопасности
                print(f"⏳ Rate limit: ожидание {sleep_time:.1f}s...")
                time.sleep(sleep_time)
        
        self.last_request_time = time.time()

    from datetime import datetime

    def get_klines_until_date(self, symbol, interval=INTERVAL, limit=LIMIT, until_date="2025-09-09"):
        """
        Получает исторические свечи до указанной даты (не включая её).
        until_date — строка в формате 'YYYY-MM-DD'
        """
        try:
            if not self.session:
                self._initialize_session()
                if not self.session:
                    return None

            # Rate limiting
            self._wait_for_rate_limit()

            # Получаем все доступные свечи (ограничено лимитом API)
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

            # Фильтруем по дате
            until_ts = int(datetime.strptime(until_date, "%Y-%m-%d").timestamp() * 1000)
            df = df[df['timestamp'] < until_ts].reset_index(drop=True)

            return df

        except Exception as e:
            print(f"❌ Ошибка при получении данных {symbol}: {e}")
            return None

    # Для использования как метод класса:
    # df = bybit_client.get_klines_until_date("BTCUSDT", interval="1h", limit=1000, until_date="2025-

    def get_klines(self, symbol, interval=INTERVAL, limit=LIMIT):
        """Получаем исторические данные для конкретной монеты"""
        try:
            if not self.session:
                self._initialize_session()
                if not self.session:
                    return None
            
            # Rate limiting
            self._wait_for_rate_limit()
            
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

    def get_coin_info(self, symbol):
        """
        Получает название токена, тикер и список сетей (chain) для указанного символа.
        Возвращает: name, coin, chains (список строк)
        """
        try:
            if not self.session:
                self._initialize_session()
                if not self.session:
                    return None, None, None

            # Rate limiting
            self._wait_for_rate_limit()

            response = self.session.get_coin_info(coin=symbol)
            if response['retCode'] != 0 or 'result' not in response or 'rows' not in response['result']:
                print(f"❌ Ошибка API при получении информации о токене {symbol}: {response.get('retMsg', 'Нет сообщения')}")
                return None, None, None

            row = response['result']['rows'][0]
            name = row.get('name')
            coin = row.get('coin')
            chains = [chain.get('chain') for chain in row.get('chains', []) if 'chain' in chain]

            return name, coin, chains

        except Exception as e:
            print(f"❌ Ошибка при получении информации о токене {symbol}: {e}")
            return None, None, None
        
    def get_orderbook(self, symbol, levels, whale_size=None):
        """Получает стакан цен для конкретной монеты и анализирует крупные ордера"""
        try:
            if not self.session:
                self._initialize_session()
                if not self.session:
                    return None, None, None, None, None, None
            
            # Rate limiting
            self._wait_for_rate_limit()
            
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
            
            # Rate limiting
            self._wait_for_rate_limit()
            
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
            
            # Rate limiting
            self._wait_for_rate_limit()
            
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
            
            # Rate limiting
            self._wait_for_rate_limit()
            
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

    def get_server_time(self):
        """
        Получает серверное время Bybit в удобном формате (UTC).
        
        Returns:
            dict: {
                'timeSecond': str - время в секундах (Unix timestamp),
                'timeNano': str - время в наносекундах,
                'time': int - время в миллисекундах,
                'datetime_utc': str - дата и время UTC в формате 'dd.mm.yyyy hh:mm:ss UTC',
                'datetime_local': str - дата и время локальное в формате 'dd.mm.yyyy hh:mm:ss'
            } или None при ошибке
        """
        try:
            if not self.session:
                self._initialize_session()
                if not self.session:
                    return None
            
            # Rate limiting
            self._wait_for_rate_limit()
            
            response = self.session.get_server_time()
            
            if response['retCode'] == 0:
                # Конвертируем Unix timestamp
                time_second = int(response['result']['timeSecond'])
                
                # UTC время
                from datetime import timezone
                dt_utc = datetime.fromtimestamp(time_second, tz=timezone.utc)
                formatted_utc = dt_utc.strftime('%d.%m.%Y %H:%M:%S UTC')
                
                # Локальное время
                dt_local = datetime.fromtimestamp(time_second)
                formatted_local = dt_local.strftime('%d.%m.%Y %H:%M:%S')
                
                return {
                    'timeSecond': response['result']['timeSecond'],
                    'timeNano': response['result']['timeNano'],
                    'time': response['time'],
                    'datetime_utc': formatted_utc,
                    'datetime_local': formatted_local
                }
            else:
                print(f"❌ Ошибка получения серверного времени: {response['retMsg']}")
                return None
                
        except Exception as e:
            print(f"❌ Ошибка получения серверного времени: {e}")
            return None

# Глобальный экземпляр клиента
bybit_client = BybitClient()

def get_bybit_client():
    """Возвращает глобальный экземпляр Bybit клиента"""
    return bybit_client