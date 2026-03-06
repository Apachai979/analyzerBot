import time
import numpy as np
import pandas as pd


class RSIAnalyzer:
    def __init__(self, default_period=14, default_lookback=30, default_pivot_window=2):
        """
        Инициализирует анализатор RSI и дивергенций.

        Args:
            default_period (int): Период RSI по умолчанию.
            default_lookback (int): Количество последних свечей для поиска дивергенции.
            default_pivot_window (int): Размер окна для поиска локальных экстремумов.

        Example:
            analyzer = RSIAnalyzer(default_period=14, default_lookback=30, default_pivot_window=2)
        """
        self.default_period = default_period
        self.default_lookback = default_lookback
        self.default_pivot_window = default_pivot_window

        # Актуальное состояние по ключу (symbol, timeframe)
        self.latest_divergence = {}
        self.latest_rsi_info = {}

    def _format_rsi_info(self, last_rsi, period=None):
        """
        Формирует текстовый блок с информацией по RSI.

        Args:
            last_rsi (float): Последнее значение RSI.
            period (int | None): Период RSI. Если None, используется default_period.

        Returns:
            str: Форматированный текстовый блок RSI.

        Example:
            text = analyzer._format_rsi_info(63.25, period=14)
        """
        period = period or self.default_period

        if last_rsi >= 70:
            rsi_state = "ПЕРЕКУПЛЕННОСТЬ"
        elif last_rsi <= 30:
            rsi_state = "ПЕРЕПРОДАННОСТЬ"
        else:
            rsi_state = "НЕЙТРАЛЬНО"

        return (
            f"=== RSI ANALYSIS ===\n"
            f"Период: {period}\n"
            f"RSI: {last_rsi:.2f}\n"
            f"Состояние: {rsi_state}\n"
            f"---\n"
        )

    def get_info_rsi(self, symbol="UNKNOWN", timeframe="UNKNOWN"):
        """
        Возвращает последний сохраненный RSI-блок по symbol/timeframe.

        Args:
            symbol (str): Тикер инструмента, например BTCUSDT.
            timeframe (str): Таймфрейм, например 1H/4H/12H.

        Returns:
            str: Последний текстовый блок RSI для указанной пары symbol/timeframe.

        Example:
            text = analyzer.get_info_rsi(symbol="BTCUSDT", timeframe="1H")
        """
        info = self.latest_rsi_info.get((symbol, timeframe))
        if not info:
            return (
                f"=== RSI ANALYSIS ===\n"
                f"{symbol} [{timeframe}]\n"
                f"Данные RSI еще не анализировались\n"
                f"---\n"
            )

        return self._format_rsi_info(info['last_rsi'], period=info['period'])

    def calculate_rsi(self, df, period=None):
        """
        Считает RSI по методу Уайлдера и возвращает текст + серию RSI.

        Args:
            df (pd.DataFrame): Данные свечей. Должен содержать колонку close.
            period (int | None): Период RSI. Если None, используется default_period.

        Returns:
            tuple[str, pd.Series | None]:
                - log_rsi_str: форматированный текстовый блок RSI,
                - rsi: серия RSI (или None при недостатке данных).

        Example:
            log, rsi_series = analyzer.calculate_rsi(df_1h, period=14)
        """
        period = period or self.default_period
        df = df.copy()

        if len(df) < period:
            return "Недостаточно данных для расчета RSI\n", None

        delta = df['close'].diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)

        avg_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
        avg_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()

        rs = avg_gain / avg_loss.replace(0, np.nan)
        rsi = 100 - (100 / (1 + rs))

        loss_zero_gain_pos = (avg_loss == 0) & (avg_gain > 0)
        gain_zero_loss_pos = (avg_gain == 0) & (avg_loss > 0)
        both_zero = (avg_gain == 0) & (avg_loss == 0)

        rsi = rsi.mask(loss_zero_gain_pos, 100)
        rsi = rsi.mask(gain_zero_loss_pos, 0)
        rsi = rsi.mask(both_zero, 50)

        if rsi.dropna().empty:
            return "Недостаточно данных для расчета RSI\n", None

        last_rsi = rsi.dropna().iloc[-1]
        log_rsi_str = self._format_rsi_info(last_rsi, period=period)

        return log_rsi_str, rsi

    def _detect_rsi_divergence(self, df, rsi_series, lookback=None, pivot_window=None):
        """
        Ищет бычью/медвежью дивергенцию RSI по двум последним pivot-экстремумам.

        Args:
            df (pd.DataFrame): Данные свечей. Используется колонка close.
            rsi_series (pd.Series): Готовая серия RSI.
            lookback (int | None): Глубина анализа в свечах.
            pivot_window (int | None): Окно для поиска локальных минимумов/максимумов.

        Returns:
            dict: Словарь вида:
                {
                    "type": "BULLISH" | "BEARISH" | "NONE",
                    "details": str,
                    "signature": tuple | None
                }

        Example:
            result = analyzer._detect_rsi_divergence(df_1h, rsi_series, lookback=30, pivot_window=2)
        """
        lookback = lookback or self.default_lookback
        pivot_window = pivot_window or self.default_pivot_window

        if rsi_series is None or rsi_series.dropna().empty:
            return {
                "type": "NONE",
                "details": "RSI недоступен для поиска дивергенции",
                "signature": None,
            }

        work = pd.DataFrame({
            "close": df['close'],
            "rsi": rsi_series
        }).dropna().tail(lookback).reset_index(drop=True)

        if len(work) < (pivot_window * 2 + 3):
            return {
                "type": "NONE",
                "details": "Недостаточно свечей для swing-анализа RSI дивергенции",
                "signature": None,
            }

        closes = work['close'].values
        rsis = work['rsi'].values

        pivot_lows = []
        pivot_highs = []

        for i in range(pivot_window, len(work) - pivot_window):
            window_prices = closes[i - pivot_window:i + pivot_window + 1]
            center_price = closes[i]

            if center_price == np.min(window_prices):
                pivot_lows.append(i)
            if center_price == np.max(window_prices):
                pivot_highs.append(i)

        if len(pivot_lows) >= 2:
            prev_idx, last_idx = pivot_lows[-2], pivot_lows[-1]
            prev_price_low = float(closes[prev_idx])
            last_price_low = float(closes[last_idx])
            prev_rsi_low = float(rsis[prev_idx])
            last_rsi_low = float(rsis[last_idx])

            if last_price_low < prev_price_low and last_rsi_low > prev_rsi_low:
                return {
                    "type": "BULLISH",
                    "details": (
                        f"Бычья дивергенция: цена low {prev_price_low:.4f} -> {last_price_low:.4f}, "
                        f"RSI low {prev_rsi_low:.2f} -> {last_rsi_low:.2f}"
                    ),
                    "signature": ("BULLISH", round(last_price_low, 8), round(last_rsi_low, 4), int(last_idx)),
                }

        if len(pivot_highs) >= 2:
            prev_idx, last_idx = pivot_highs[-2], pivot_highs[-1]
            prev_price_high = float(closes[prev_idx])
            last_price_high = float(closes[last_idx])
            prev_rsi_high = float(rsis[prev_idx])
            last_rsi_high = float(rsis[last_idx])

            if last_price_high > prev_price_high and last_rsi_high < prev_rsi_high:
                return {
                    "type": "BEARISH",
                    "details": (
                        f"Медвежья дивергенция: цена high {prev_price_high:.4f} -> {last_price_high:.4f}, "
                        f"RSI high {prev_rsi_high:.2f} -> {last_rsi_high:.2f}"
                    ),
                    "signature": ("BEARISH", round(last_price_high, 8), round(last_rsi_high, 4), int(last_idx)),
                }

        return {
            "type": "NONE",
            "details": "RSI дивергенция не обнаружена",
            "signature": None,
        }

    def analyze_divergence_output(self, df, symbol="UNKNOWN", timeframe="UNKNOWN", period=None, lookback=None, pivot_window=None):
        """
        Выполняет полный анализ RSI + дивергенции, обновляет внутреннее состояние и
        возвращает итоговый текстовый вывод.

        Args:
            df (pd.DataFrame): Данные свечей с колонкой close.
            symbol (str): Тикер инструмента.
            timeframe (str): Таймфрейм анализа.
            period (int | None): Период RSI.
            lookback (int | None): Глубина анализа дивергенции.
            pivot_window (int | None): Окно поиска pivot-экстремумов.

        Returns:
            str: Итоговый текст RSI + блок дивергенции.

        Example:
            text = analyzer.analyze_divergence_output(df_1h, symbol="BTCUSDT", timeframe="1H")
        """
        rsi_log, rsi_series = self.calculate_rsi(df, period=period or self.default_period)
        divergence = self._detect_rsi_divergence(df, rsi_series, lookback=lookback, pivot_window=pivot_window)

        key = (symbol, timeframe)
        if rsi_series is not None and not rsi_series.dropna().empty:
            self.latest_rsi_info[key] = {
                "last_rsi": float(rsi_series.dropna().iloc[-1]),
                "period": period or self.default_period,
                "updated_at": time.time(),
            }

        prev_state = self.latest_divergence.get(key)

        # Обновляем состояние ТОЛЬКО при новой дивергенции
        if divergence['type'] in ["BULLISH", "BEARISH"]:
            if prev_state is None or prev_state.get('signature') != divergence['signature']:
                self.latest_divergence[key] = {
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "type": divergence['type'],
                    "details": divergence['details'],
                    "signature": divergence['signature'],
                    "updated_at": time.time(),
                }

        current_state = self.latest_divergence.get(key)
        rsi_info_text = self.get_info_rsi(symbol=symbol, timeframe=timeframe)

        if current_state:
            return (
                f"{rsi_info_text}"
                f"=== RSI DIVERGENCE ===\n"
                f"{symbol} [{timeframe}]\n"
                f"Тип: {current_state['type']}\n"
                f"{current_state['details']}\n"
                f"---\n"
            )

        return (
            f"{rsi_info_text}"
            f"=== RSI DIVERGENCE ===\n"
            f"{symbol} [{timeframe}]\n"
            f"Тип: NONE\n"
            f"RSI дивергенция пока не обнаружена\n"
            f"---\n"
        )

    def get_latest_divergence(self, symbol="UNKNOWN", timeframe="UNKNOWN"):
        """
        Возвращает последнее зафиксированное состояние дивергенции для symbol/timeframe.

        Args:
            symbol (str): Тикер инструмента.
            timeframe (str): Таймфрейм.

        Returns:
            dict | None: Последний словарь дивергенции или None, если ничего не найдено.

        Example:
            state = analyzer.get_latest_divergence(symbol="BTCUSDT", timeframe="1H")
            if state:
                print(state["type"])
        """
        return self.latest_divergence.get((symbol, timeframe))
