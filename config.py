# ==================== КОНФИГУРАЦИЯ ====================
import os
from dotenv import load_dotenv

load_dotenv()

COINMARKETCAP_API_KEY = os.getenv('COINMARKETCAP_API_KEY')


BYBIT_API_KEY = os.getenv('BYBIT_API_KEY')
BYBIT_API_SECRET = os.getenv('BYBIT_API_SECRET')
TESTNET = os.getenv('BYBIT_TESTNET', 'False').lower() == 'true'
BYBIT_API_URL = "https://api.bybit.com"
BYBIT_TESTNET_URL = "https://api-testnet.bybit.com"

SYMBOLS = [
    "SOLUSDT",
    "PYTHUSDT",
    "ARKMUSDT", 
    "ARBUSDT",
]

TVL_CHAINS_TO_MONITOR = [
    'Ethereum', 'Solana', 'BSC', 'Arbitrum', 
    'Polygon', 'Avalanche', 'Optimism', 'Base'
]

# Маппинг блокчейнов к токенам
CHAIN_TO_TOKEN_MAP = {
    'Ethereum': 'ETH',
    'Solana': 'SOL',
    'BSC': 'BNB',
    'Arbitrum': 'ARB',
    'Polygon': 'MATIC',
    'Avalanche': 'AVAX',
    'Optimism': 'OP',
    'Base': 'BASE'
}

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

# Получить тикер токена по символу
def get_token_from_symbol(symbol):
    for chain, token in CHAIN_TO_TOKEN_MAP.items():
        if symbol.startswith(token):
            return chain
    return None