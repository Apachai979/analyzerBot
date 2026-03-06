import time
import numpy as np
import pandas as pd


class OBVAnalyzer:
    def __init__(
        self,
        default_ma_period=20,
        default_trend_lookback=5,
        fast_ema_period=10,
        slow_ema_period=30,
        debounce_bars=2,
        divergence_lookback=30,
        pivot_window=2,
    ):
        """
        Инициализирует анализатор OBV.

        Args:
            default_ma_period (int): Период MA для OBV.
            default_trend_lookback (int): Глубина (в свечах) для оценки тренда OBV.
            fast_ema_period (int): Быстрая EMA по OBV.
            slow_ema_period (int): Медленная EMA по OBV.
            debounce_bars (int): Количество баров для подтверждения смены состояния.
            divergence_lookback (int): Глубина поиска OBV-дивергенций.
            pivot_window (int): Окно поиска локальных экстремумов.
        """
        self.default_ma_period = default_ma_period
        self.default_trend_lookback = default_trend_lookback
        self.fast_ema_period = fast_ema_period
        self.slow_ema_period = slow_ema_period
        self.debounce_bars = debounce_bars
        self.divergence_lookback = divergence_lookback
        self.pivot_window = pivot_window

        # Последнее состояние по ключу (symbol, timeframe)
        self.latest_obv_state = {}
        self._transition_state = {}

    def calculate_obv(self, df):
        """
        Рассчитывает классический OBV.

        Args:
            df (pd.DataFrame): Данные свечей с колонками 'close' и 'volume'.

        Returns:
            tuple[str, pd.Series | None]:
                - log: текстовый блок,
                - obv_series: серия OBV или None, если данных недостаточно.
        """
        if df is None or df.empty or 'close' not in df.columns or 'volume' not in df.columns:
            return "Недостаточно данных для расчета OBV\n", None

        work = df[['close', 'volume']].copy()
        work['price_diff'] = work['close'].diff().fillna(0)

        signed_volume = np.where(
            work['price_diff'] > 0,
            work['volume'],
            np.where(work['price_diff'] < 0, -work['volume'], 0)
        )

        obv_series = pd.Series(signed_volume, index=work.index).cumsum()

        if obv_series.dropna().empty:
            return "Недостаточно данных для расчета OBV\n", None

        last_obv = float(obv_series.iloc[-1])
        prev_obv = float(obv_series.iloc[-2]) if len(obv_series) > 1 else last_obv

        if last_obv > prev_obv:
            short_state = "РАСТЕТ"
        elif last_obv < prev_obv:
            short_state = "ПАДАЕТ"
        else:
            short_state = "БЕЗ ИЗМЕНЕНИЙ"

        log = (
            f"=== OBV ANALYSIS ===\n"
            f"OBV: {last_obv:.2f}\n"
            f"Изменение: {short_state}\n"
            f"---\n"
        )

        return log, obv_series

    def _detect_obv_divergence(self, df, obv_series, lookback=None, pivot_window=None):
        """Ищет дивергенцию между ценой и OBV."""
        lookback = lookback or self.divergence_lookback
        pivot_window = pivot_window or self.pivot_window

        if obv_series is None or obv_series.dropna().empty:
            return {"type": "NONE", "details": "OBV недоступен", "signature": None}

        if df is None or df.empty or 'close' not in df.columns:
            return {"type": "NONE", "details": "Цена недоступна", "signature": None}

        work = pd.DataFrame({
            'close': df['close'],
            'obv': obv_series,
        }).dropna().tail(lookback).reset_index(drop=True)

        if len(work) < (pivot_window * 2 + 3):
            return {"type": "NONE", "details": "Недостаточно данных для дивергенции", "signature": None}

        closes = work['close'].values
        obv = work['obv'].values
        pivot_lows = []
        pivot_highs = []

        for i in range(pivot_window, len(work) - pivot_window):
            price_window = closes[i - pivot_window:i + pivot_window + 1]
            center_price = closes[i]

            if center_price == np.min(price_window):
                pivot_lows.append(i)
            if center_price == np.max(price_window):
                pivot_highs.append(i)

        if len(pivot_lows) >= 2:
            prev_idx, last_idx = pivot_lows[-2], pivot_lows[-1]
            prev_price_low = float(closes[prev_idx])
            last_price_low = float(closes[last_idx])
            prev_obv_low = float(obv[prev_idx])
            last_obv_low = float(obv[last_idx])

            if last_price_low < prev_price_low and last_obv_low > prev_obv_low:
                return {
                    "type": "BULLISH",
                    "details": (
                        f"Бычья дивергенция: цена low {prev_price_low:.4f} -> {last_price_low:.4f}, "
                        f"OBV low {prev_obv_low:.2f} -> {last_obv_low:.2f}"
                    ),
                    "signature": ("BULLISH", round(last_price_low, 8), round(last_obv_low, 2), int(last_idx)),
                }

        if len(pivot_highs) >= 2:
            prev_idx, last_idx = pivot_highs[-2], pivot_highs[-1]
            prev_price_high = float(closes[prev_idx])
            last_price_high = float(closes[last_idx])
            prev_obv_high = float(obv[prev_idx])
            last_obv_high = float(obv[last_idx])

            if last_price_high > prev_price_high and last_obv_high < prev_obv_high:
                return {
                    "type": "BEARISH",
                    "details": (
                        f"Медвежья дивергенция: цена high {prev_price_high:.4f} -> {last_price_high:.4f}, "
                        f"OBV high {prev_obv_high:.2f} -> {last_obv_high:.2f}"
                    ),
                    "signature": ("BEARISH", round(last_price_high, 8), round(last_obv_high, 2), int(last_idx)),
                }

        return {
            "type": "NONE",
            "details": "OBV дивергенция не обнаружена",
            "signature": None,
        }

    def _debounce_state(self, key, raw_state):
        """Подтверждает смену состояния только после debounce_bars одинаковых сигналов."""
        tracker = self._transition_state.get(key)

        if tracker is None:
            self._transition_state[key] = {
                'confirmed': raw_state,
                'candidate': raw_state,
                'count': 1,
            }
            return raw_state, raw_state, 1

        confirmed = tracker['confirmed']
        candidate = tracker['candidate']
        count = tracker['count']

        if raw_state == confirmed:
            tracker['candidate'] = raw_state
            tracker['count'] = 1
            return confirmed, raw_state, 1

        if raw_state == candidate:
            count += 1
        else:
            candidate = raw_state
            count = 1

        if count >= self.debounce_bars:
            confirmed = raw_state
            candidate = raw_state
            count = 1

        tracker['confirmed'] = confirmed
        tracker['candidate'] = candidate
        tracker['count'] = count

        return confirmed, candidate, count

    def _confidence_score(self, raw_state, confirmed_state, obv_slope, obv_fast, obv_slow, divergence_type):
        """Формирует confidence 0..100 по силе и согласованности сигналов."""
        score = 50

        if raw_state == confirmed_state:
            score += 10

        if raw_state == "BULLISH":
            score += 10
        elif raw_state == "BEARISH":
            score += 10

        if obv_slope > 0 and obv_fast > obv_slow:
            score += 15
        elif obv_slope < 0 and obv_fast < obv_slow:
            score += 15
        else:
            score -= 10

        if divergence_type == "BULLISH" and confirmed_state == "BULLISH":
            score += 10
        elif divergence_type == "BEARISH" and confirmed_state == "BEARISH":
            score += 10
        elif divergence_type in ["BULLISH", "BEARISH"]:
            score -= 5

        return int(max(0, min(100, score)))

    def _format_obv_state(self, state):
        """Формирует текстовый вывод состояния OBV."""
        return (
            f"=== OBV STATE V2 ===\n"
            f"{state['symbol']} [{state['timeframe']}]\n"
            f"Raw: {state['raw_state']} | Confirmed: {state['obv_state']}\n"
            f"Confidence: {state['confidence']}%\n"
            f"Тренд: {state['trend_state']}\n"
            f"OBV: {state['last_obv']:.2f}\n"
            f"OBV MA({state['ma_period']}): {state['last_obv_ma']:.2f}\n"
            f"OBV EMA({state['fast_ema_period']}/{state['slow_ema_period']}): {state['last_obv_ema_fast']:.2f}/{state['last_obv_ema_slow']:.2f}\n"
            f"Дивергенция: {state['divergence_type']}\n"
            f"Детали дивергенции: {state['divergence_details']}\n"
            f"Комментарий: {state['details']}\n"
            f"---\n"
        )

    def analyze_obv_output(self, df, symbol="UNKNOWN", timeframe="UNKNOWN", ma_period=None, trend_lookback=None):
        """
        Считает OBV, оценивает состояние и сохраняет последнее состояние в кэш.

        Args:
            df (pd.DataFrame): Данные свечей ('close', 'volume').
            symbol (str): Тикер инструмента.
            timeframe (str): Таймфрейм.
            ma_period (int | None): Период MA для OBV.
            trend_lookback (int | None): Глубина оценки тренда.

        Returns:
            str: Готовый текстовый вывод по состоянию OBV.
        """
        ma_period = ma_period or self.default_ma_period
        trend_lookback = trend_lookback or self.default_trend_lookback

        log, obv_series = self.calculate_obv(df)
        if obv_series is None or obv_series.dropna().empty:
            return log

        obv_ma = obv_series.rolling(ma_period).mean()
        obv_ema_fast = obv_series.ewm(span=self.fast_ema_period, adjust=False).mean()
        obv_ema_slow = obv_series.ewm(span=self.slow_ema_period, adjust=False).mean()

        last_obv = float(obv_series.iloc[-1])
        last_obv_ma = float(obv_ma.dropna().iloc[-1]) if not obv_ma.dropna().empty else last_obv
        last_obv_ema_fast = float(obv_ema_fast.iloc[-1])
        last_obv_ema_slow = float(obv_ema_slow.iloc[-1])

        if len(obv_series) > trend_lookback:
            obv_prev = float(obv_series.iloc[-(trend_lookback + 1)])
        else:
            obv_prev = float(obv_series.iloc[0])

        obv_delta = last_obv - obv_prev
        obv_slope = obv_delta / max(1, trend_lookback)

        if obv_delta > 0:
            trend_state = "ВОСХОДЯЩИЙ"
        elif obv_delta < 0:
            trend_state = "НИСХОДЯЩИЙ"
        else:
            trend_state = "БОКОВОЙ"

        if last_obv_ema_fast > last_obv_ema_slow and obv_slope > 0:
            raw_state = "BULLISH"
        elif last_obv_ema_fast < last_obv_ema_slow and obv_slope < 0:
            raw_state = "BEARISH"
        else:
            raw_state = "NEUTRAL"

        key = (symbol, timeframe)
        obv_state, candidate_state, candidate_count = self._debounce_state(key, raw_state)

        divergence = self._detect_obv_divergence(df, obv_series)
        divergence_type = divergence.get('type', 'NONE')
        divergence_details = divergence.get('details', 'n/a')

        confidence = self._confidence_score(
            raw_state=raw_state,
            confirmed_state=obv_state,
            obv_slope=obv_slope,
            obv_fast=last_obv_ema_fast,
            obv_slow=last_obv_ema_slow,
            divergence_type=divergence_type,
        )

        if obv_state == "BULLISH":
            details = "OBV подтверждает накопление объема (восходящий режим)."
        elif obv_state == "BEARISH":
            details = "OBV подтверждает распределение объема (нисходящий режим)."
        else:
            details = "OBV в смешанном режиме, явного преимущества нет."

        state = {
            "symbol": symbol,
            "timeframe": timeframe,
            "obv_state": obv_state,
            "raw_state": raw_state,
            "candidate_state": candidate_state,
            "candidate_count": candidate_count,
            "confidence": confidence,
            "trend_state": trend_state,
            "last_obv": last_obv,
            "last_obv_ma": last_obv_ma,
            "ma_period": ma_period,
            "last_obv_ema_fast": last_obv_ema_fast,
            "last_obv_ema_slow": last_obv_ema_slow,
            "fast_ema_period": self.fast_ema_period,
            "slow_ema_period": self.slow_ema_period,
            "obv_slope": obv_slope,
            "divergence_type": divergence_type,
            "divergence_details": divergence_details,
            "details": details,
            "updated_at": time.time(),
        }

        self.latest_obv_state[key] = state

        return log + self._format_obv_state(state)

    def get_latest_obv_state(self, symbol="UNKNOWN", timeframe="UNKNOWN", as_dict=False):
        """
        Возвращает последнее зафиксированное состояние OBV.

        Args:
            symbol (str): Тикер инструмента.
            timeframe (str): Таймфрейм.
            as_dict (bool): Вернуть dict вместо текста.

        Returns:
            dict | str: Последнее состояние OBV.
        """
        state = self.latest_obv_state.get((symbol, timeframe))

        if as_dict:
            return state

        if not state:
            return (
                f"=== OBV STATE ===\n"
                f"{symbol} [{timeframe}]\n"
                f"Данные OBV еще не анализировались\n"
                f"---\n"
            )

        return self._format_obv_state(state)
