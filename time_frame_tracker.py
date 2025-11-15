"""
Модуль для отслеживания частоты анализа таймфреймов и дедупликации сигналов.

Управляет тем, как часто анализируется каждый таймфрейм для каждого символа,
и предотвращает отправку дублирующихся Telegram сигналов.
"""

import time


class TimeframeAnalysisTracker:
    """Отслеживает время последнего анализа для каждого таймфрейма и символа"""
    
    def __init__(self):
        # Интервалы анализа в секундах
        self.intervals = {
            '1D': 12 * 60 * 60,   # 12 часов (2 раза в день)
            '12H': 4 * 60 * 60,   # 4 часа (3 раза за 12 часов)
            '4H': 2 * 60 * 60,    # 2 часа (2 раза за 4 часа)
            '1H': 15 * 60         # 15 минут (4 раза в час)
        }
        
        # Хранилище времени последнего анализа: {symbol: {timeframe: timestamp}}
        self.last_analysis = {}
        
        # Кэш для дедупликации Telegram сигналов
        self.sent_signals = {}
        self.signal_timeout = 3600  # 1 час - время жизни сигнала в кэше
    
    def should_analyze(self, symbol, timeframe):
        """
        Проверяет, пора ли анализировать данный таймфрейм для символа.
        
        Args:
            symbol (str): Торговый символ (например, 'BTCUSDT')
            timeframe (str): Таймфрейм ('1D', '12H', '4H', '1H')
        
        Returns:
            bool: True если пора анализировать, False если еще рано
        """
        current_time = time.time()
        
        if symbol not in self.last_analysis:
            self.last_analysis[symbol] = {}
        
        if timeframe not in self.last_analysis[symbol]:
            # Первый раз для этого символа и таймфрейма - анализируем
            self.last_analysis[symbol][timeframe] = current_time
            return True
        
        time_passed = current_time - self.last_analysis[symbol][timeframe]
        
        if time_passed >= self.intervals[timeframe]:
            # Прошло достаточно времени - обновляем timestamp и разрешаем анализ
            self.last_analysis[symbol][timeframe] = current_time
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
        Возвращает время (в секундах) до следующего разрешенного анализа.
        
        Args:
            symbol (str): Торговый символ
            timeframe (str): Таймфрейм
        
        Returns:
            float: Секунд до следующего анализа, или 0 если можно анализировать сейчас
        """
        if symbol not in self.last_analysis or timeframe not in self.last_analysis[symbol]:
            return 0
        
        current_time = time.time()
        time_passed = current_time - self.last_analysis[symbol][timeframe]
        time_remaining = self.intervals[timeframe] - time_passed
        
        return max(0, time_remaining)
    
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
            'intervals': self.intervals
        }
