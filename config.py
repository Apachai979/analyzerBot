# ==================== КОНФИГУРАЦИЯ ====================
import os
from dotenv import load_dotenv

load_dotenv()

COINMARKETCAP_API_KEY = os.getenv('COINMARKETCAP_API_KEY')

TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

BYBIT_API_KEY = os.getenv('BYBIT_API_KEY_TRADE')
BYBIT_API_SECRET = os.getenv('BYBIT_SECRET_TRADE')
TESTNET = os.getenv('BYBIT_TESTNET', 'False').lower() == 'true'
BYBIT_API_URL = "https://api.bybit.com"
BYBIT_TESTNET_URL = "https://api-testnet.bybit.com"


# Общие настройки
INTERVAL = "60"
FAST_PERIOD = 20
SLOW_PERIOD = 50
LIMIT = 500
VOLATILITY_LOOKBACK = 200
CATEGORY = "spot" #"linear" 
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
# ==== Параметры общего universe ==== 
UNIVERSE_FILTER_MIN_MARKET_CAP = float(os.getenv('UNIVERSE_FILTER_MIN_MARKET_CAP', str(MIN_MARKET_CAP)))
UNIVERSE_FILTER_MIN_VOLUME_24H = float(os.getenv('UNIVERSE_FILTER_MIN_VOLUME_24H', '1000000'))
UNIVERSE_FILTER_EXCLUDE_STABLECOINS = os.getenv('UNIVERSE_FILTER_EXCLUDE_STABLECOINS', 'True').lower() == 'true'
# Минимальная стоимость spot-позиции в USDT, ниже которой остаток считается пылью.
SPOT_POSITION_MIN_USD_VALUE = float(os.getenv('SPOT_POSITION_MIN_USD_VALUE', '1.0'))

# ==== Параметры основного цикла и фоновых потоков ====
# Пауза между основными циклами анализа символов в main.py.
MAIN_LOOP_PAUSE_SECONDS = int(os.getenv('MAIN_LOOP_PAUSE_SECONDS', '60'))
# Как часто background calibration worker проверяет, не наступило ли окно автокалибровки.
CALIBRATION_CHECK_PAUSE_SECONDS = int(os.getenv('CALIBRATION_CHECK_PAUSE_SECONDS', '60'))
# Как часто background calibration worker пишет heartbeat в отдельный лог, даже если окно еще не наступило.
CALIBRATION_HEARTBEAT_INTERVAL_SECONDS = int(os.getenv('CALIBRATION_HEARTBEAT_INTERVAL_SECONDS', '300'))


# ==== Конфигурация стратегий ==== 
# enabled: участвует ли стратегия в цикле анализа
# watch_only: стратегия анализирует рынок и пишет сигналы, но не открывает сделки
STRATEGY_RUNTIME_CONFIGS = {
    'MULTI_TF': {
        'enabled': True,
        'watch_only': False,
        'parameters': {
            'trend_min_required_rows': 260,
            'trend_min_soft_conditions_passed': 2,
            'setup_min_required_rows': 220,
            'setup_min_soft_conditions_passed': 6,
            'entry_min_required_rows': 180,
            'entry_min_soft_conditions_passed': 5,
        },
    },
    'RANGE': {
        'enabled': True,
        'watch_only': True,
        'parameters': {
            'min_confidence': 9,
            'min_risk_reward_ratio': 7,
        },
    },
}
