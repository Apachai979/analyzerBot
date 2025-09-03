from config import ASSET_PRESETS, USER_ORDERBOOK_LEVELS, USER_WHALE_SIZE, USER_VOLATILITY_MULTIPLIER

class AssetConfig:
    """Класс для хранения конфигурации отдельного актива"""
    
    def __init__(self, symbol, user_orderbook_levels=None, user_whale_size=None, user_vol_multiplier=None):
        self.symbol = symbol
        self.orderbook_levels = user_orderbook_levels
        self.whale_size = user_whale_size
        self.volatility_multiplier = user_vol_multiplier
        self.is_configured = False
    
    def auto_configure(self, df):
        """Автоматически настраивает параметры based на данных актива"""
        preset = ASSET_PRESETS.get(self.symbol, ASSET_PRESETS['DEFAULT']).copy()
        print(f"[auto_configure] {self.symbol}: len(df)={len(df) if df is not None else 0}")
        if df is not None and len(df) > 20:  # уменьшили порог
            daily_volatility = df['close'].pct_change().std() * 100
            avg_volume = df['volume'].tail(20).mean()
            print(f"[auto_configure] {self.symbol}: vol={daily_volatility:.2f}, avg_vol={avg_volume:.2f}")
            
            if daily_volatility > 5:
                preset['orderbook_levels'] = min(40, preset['orderbook_levels'] + 5)
                preset['volatility_multiplier'] *= 1.2
            
            if avg_volume < 1000000:
                preset['whale_size'] = max(10000, preset['whale_size'] * 0.7)
                preset['orderbook_levels'] += 10
        
        self.orderbook_levels = self.orderbook_levels or preset['orderbook_levels']
        self.whale_size = self.whale_size or preset['whale_size']
        self.volatility_multiplier = self.volatility_multiplier or preset['volatility_multiplier']
        
        self.is_configured = True
        return self

class ConfigManager:
    """Управляет конфигурациями всех активов"""
    
    def __init__(self):
        self.configs = {}
    
    def get_config(self, symbol, df):
        """Возвращает конфигурацию для символа, автоматически настраивая если нужно"""
        if symbol not in self.configs:
            config = AssetConfig(
                symbol,
                USER_ORDERBOOK_LEVELS,
                USER_WHALE_SIZE, 
                USER_VOLATILITY_MULTIPLIER
            )
            self.configs[symbol] = config.auto_configure(df)
        
        return self.configs[symbol]