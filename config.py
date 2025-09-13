# ==================== КОНФИГУРАЦИЯ ====================
import os
from dotenv import load_dotenv

load_dotenv()

COINMARKETCAP_API_KEY = os.getenv('COINMARKETCAP_API_KEY')

TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

BYBIT_API_KEY = os.getenv('BYBIT_API_KEY')
BYBIT_API_SECRET = os.getenv('BYBIT_SECRET')
TESTNET = os.getenv('BYBIT_TESTNET', 'False').lower() == 'true'
BYBIT_API_URL = "https://api.bybit.com"
BYBIT_TESTNET_URL = "https://api-testnet.bybit.com"


# Общие настройки
INTERVAL = "60"
FAST_PERIOD = 20
SLOW_PERIOD = 50
LIMIT = 500
VOLATILITY_LOOKBACK = 200
CATEGORY = "spot"
RSI_PERIOD = 14
VOLUME_MA_PERIOD = 20

CMC_API_URL = "https://pro-api.coinmarketcap.com/v2/cryptocurrency/quotes/latest"
CMC_FGI_URL = "https://pro-api.coinmarketcap.com/v3/fear-and-greed/historical"
CMC_FGI_LATEST = "https://pro-api.coinmarketcap.com/v3/fear-and-greed/latest"

# Ручные настройки (опционально)
USER_ORDERBOOK_LEVELS = None
USER_WHALE_SIZE = None
USER_VOLATILITY_MULTIPLIER = None

# Пресеты для активов
ASSET_PRESETS = {
    'BTCUSDT': {'whale_size': 250000, 'orderbook_levels': 15, 'volatility_multiplier': 2.0},
    'ETHUSDT': {'whale_size': 100000, 'orderbook_levels': 20, 'volatility_multiplier': 1.8},
    'TONUSDT': {'whale_size': 25000, 'orderbook_levels': 30, 'volatility_multiplier': 1.5},
    'SOLUSDT': {'whale_size': 50000, 'orderbook_levels': 25, 'volatility_multiplier': 1.7},
    'ADAUSDT': {'whale_size': 30000, 'orderbook_levels': 30, 'volatility_multiplier': 1.6},
    'DEFAULT': {'whale_size': 50000, 'orderbook_levels': 25, 'volatility_multiplier': 1.5}
}

# ==== Пороги для мониторинга трендов на споте ====
GAIN_12H = 20      # Рост за 12 часов, % (например, +20%)
DROP_12H = -20     # Падение за 12 часов, % (например, -20%)
GAIN_4H = 10       # Рост за 4 часа, % (например, +10%)
DROP_4H = -10      # Падение за 4 часа, % (например, -10%)
GAIN_2H = 7        # Рост за 2 часа, % (например, +7%)
DROP_2H = -7       # Падение за 2 часа, % (например, -7%)
MIN_MARKET_CAP = 4_000_000  # Минимальная капитализация для отбора пары, в долларах
