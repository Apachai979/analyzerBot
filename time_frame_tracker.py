"""
Модуль для отслеживания частоты анализа таймфреймов и дедупликации сигналов.

Управляет тем, как часто анализируется каждый таймфрейм для каждого символа,
и предотвращает отправку дублирующихся Telegram сигналов.
"""

import time


class TimeframeAnalysisTracker:
    """Отслеживает время последнего анализа для каждого таймфрейма и символа"""
    
    def __init__(self):
        # Длительность свечи в секундах для candle-close driven анализа.
        self.timeframe_seconds = {
            '1D': 24 * 60 * 60,
            '12H': 12 * 60 * 60,
            '4H': 4 * 60 * 60,
            '1H': 60 * 60,
            'RANGE': 60 * 60,
        }
        
        # Хранилище последней уже обработанной закрытой свечи: {symbol: {timeframe: candle_open_ts}}
        self.last_analysis = {}
        
        # Кэш для дедупликации Telegram сигналов
        self.sent_signals = {}
        self.signal_timeout = 3600  # 1 час - время жизни сигнала в кэше
    
    def should_analyze(self, symbol, timeframe):
        """
        Проверяет, появилась ли новая закрытая свеча для данного таймфрейма.
        
        Args:
            symbol (str): Торговый символ (например, 'BTCUSDT')
            timeframe (str): Таймфрейм ('1D', '12H', '4H', '1H')
        
        Returns:
            bool: True если появилась новая закрытая свеча, False если анализировать еще нечего
        """
        candle_seconds = self.timeframe_seconds.get(timeframe)
        if candle_seconds is None:
            raise ValueError(f"Unsupported timeframe: {timeframe}")

        current_time = int(time.time())
        current_bucket_open = (current_time // candle_seconds) * candle_seconds
        last_closed_candle_open = current_bucket_open - candle_seconds
        
        if symbol not in self.last_analysis:
            self.last_analysis[symbol] = {}
        
        if timeframe not in self.last_analysis[symbol]:
            # Первый запуск: анализируем последнюю уже закрытую свечу.
            self.last_analysis[symbol][timeframe] = last_closed_candle_open
            return True

        if self.last_analysis[symbol][timeframe] != last_closed_candle_open:
            self.last_analysis[symbol][timeframe] = last_closed_candle_open
            return True
        
        return False
    
    def should_send_signal(self, symbol, action, timeframe):
        """
        Проверяет, нужно ли отправлять Telegram сигнал (дедупликация).
        
        Предотвращает отправку одинаковых сигналов в течение signal_timeout (1 час).
        
        Args:
            symbol (str): Торговый символ (например, 'BTCUSDT')
            action (str): Действие/сигнал ('GO', 'ATTENTION', 'ENTER', 'WAIT_BETTER', 'SKIP')
            timeframe (str): Таймфрейм ('4H', '1H')
        
        Returns:
            bool: True если нужно отправить сигнал, False если уже отправляли недавно
        """
        key = f"{symbol}_{timeframe}_{action}"
        current_time = time.time()
        
        # Очистка старых сигналов из кэша
        self.sent_signals = {
            k: v for k, v in self.sent_signals.items() 
            if current_time - v < self.signal_timeout
        }
        
        # Проверка, был ли отправлен такой сигнал недавно
        if key in self.sent_signals:
            time_diff = current_time - self.sent_signals[key]
            if time_diff < self.signal_timeout:
                return False  # Уже отправляли недавно, не спамим
        
        # Сохраняем новый сигнал в кэш
        self.sent_signals[key] = current_time
        return True
    
    def get_time_until_next_analysis(self, symbol, timeframe):
        """
        Возвращает время (в секундах) до закрытия следующей свечи таймфрейма.
        
        Args:
            symbol (str): Торговый символ
            timeframe (str): Таймфрейм
        
        Returns:
            float: Секунд до появления следующей закрытой свечи
        """
        candle_seconds = self.timeframe_seconds.get(timeframe)
        if candle_seconds is None:
            raise ValueError(f"Unsupported timeframe: {timeframe}")

        current_time = time.time()
        next_bucket_open = (int(current_time) // candle_seconds + 1) * candle_seconds
        return max(0.0, next_bucket_open - current_time)
    
    def reset_symbol(self, symbol):
        """
        Сбрасывает историю анализа для конкретного символа.
        Полезно если нужно принудительно переанализировать символ.
        
        Args:
            symbol (str): Торговый символ
        """
        if symbol in self.last_analysis:
            del self.last_analysis[symbol]
    
    def get_stats(self):
        """
        Возвращает статистику по отслеживаемым символам и таймфреймам.
        
        Returns:
            dict: Статистика (количество символов, отправленных сигналов и т.д.)
        """
        return {
            'tracked_symbols': len(self.last_analysis),
            'cached_signals': len(self.sent_signals),
            'mode': 'closed-candle',
            'timeframe_seconds': self.timeframe_seconds,
        }
