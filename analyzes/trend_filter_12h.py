from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any

import numpy as np
import pandas as pd


# =========================
# Конфиг фильтра 12h
# =========================

@dataclass(slots=True)
class TrendFilter12hConfig:
    # EMA
    ema_fast_period: int = 20
    ema_mid_period: int = 50
    ema_slow_period: int = 200

    # ATR / ADX
    atr_period: int = 14
    adx_period: int = 14

    # Минимально допустимый ADX для "сильного" тренда
    min_adx: float = 18.0

    # Насколько цена может быть "вытянута" от EMA20 в ATR
    max_overextension_atr: float = 2.5

    # За сколько баров смотреть наклон EMA200
    ema_slope_lookback: int = 5

    # Параметры свингов
    swing_left_bars: int = 2
    swing_right_bars: int = 2

    # Сколько мягких условий должно пройти
    min_soft_conditions_passed: int = 2

    # Минимально допустимое количество строк
    min_required_rows: int = 260


# =========================
# Результат фильтра
# =========================

@dataclass(slots=True)
class TrendFilter12hResult:
    passed: bool
    hard_passed: bool
    soft_score: int
    soft_score_max: int
    reason: str
    details: dict[str, Any]


# =========================
# Индикаторы
# =========================

def ema(series: pd.Series, period: int) -> pd.Series:
    """Exponential Moving Average."""
    return series.ewm(span=period, adjust=False).mean()


def rma(series: pd.Series, period: int) -> pd.Series:
    """Wilder's moving average."""
    return series.ewm(alpha=1 / period, adjust=False).mean()


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Average True Range."""
    high = df["high"]
    low = df["low"]
    close = df["close"]

    prev_close = close.shift(1)

    tr = pd.concat(
        [
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)

    return rma(tr, period)


def adx_components(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    """
    Возвращает DataFrame с:
    - plus_di
    - minus_di
    - adx
    """
    high = df["high"]
    low = df["low"]
    close = df["close"]

    up_move = high.diff()
    down_move = -low.diff()

    plus_dm = pd.Series(
        np.where((up_move > down_move) & (up_move > 0), up_move, 0.0),
        index=df.index,
        dtype=float,
    )
    minus_dm = pd.Series(
        np.where((down_move > up_move) & (down_move > 0), down_move, 0.0),
        index=df.index,
        dtype=float,
    )

    prev_close = close.shift(1)
    tr = pd.concat(
        [
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)

    atr_rma = rma(tr, period).replace(0, np.nan)
    plus_di = 100 * rma(plus_dm, period) / atr_rma
    minus_di = 100 * rma(minus_dm, period) / atr_rma

    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    adx = rma(dx, period)

    return pd.DataFrame(
        {
            "plus_di": plus_di,
            "minus_di": minus_di,
            "adx": adx,
        },
        index=df.index,
    )


# =========================
# Свинги
# =========================

def find_confirmed_swings(
    df: pd.DataFrame,
    left_bars: int = 2,
    right_bars: int = 2,
) -> tuple[list[tuple[Any, float]], list[tuple[Any, float]]]:
    """
    Ищет подтвержденные swing high / swing low.

    Бар считается swing, только если справа уже есть right_bars свечей.
    Это важно: бот не должен использовать "недоформированные" pivots.

    Возвращает:
    - highs: список (df.index, price)
    - lows: список (df.index, price)
    """
    highs: list[tuple[Any, float]] = []
    lows: list[tuple[Any, float]] = []

    h = df["high"].to_numpy(dtype=float)
    l = df["low"].to_numpy(dtype=float)
    idx = df.index
    n = len(df)

    for i in range(left_bars, n - right_bars):
        high_window = h[i - left_bars : i + right_bars + 1]
        low_window = l[i - left_bars : i + right_bars + 1]

        # Берем только уникальный максимум/минимум, чтобы снизить шум
        if h[i] == np.max(high_window) and np.sum(high_window == h[i]) == 1:
            highs.append((idx[i], h[i]))

        if l[i] == np.min(low_window) and np.sum(low_window == l[i]) == 1:
            lows.append((idx[i], l[i]))

    return highs, lows


def evaluate_market_structure(
    swing_highs: list[tuple[Any, float]],
    swing_lows: list[tuple[Any, float]],
    last_close: float,
) -> dict[str, Any]:
    """
    Более мягкая оценка структуры тренда.

    Не требуем одновременно и HH, и HL.
    Для 12h-контекста достаточно, чтобы структура в целом выглядела бычьей:
    - higher lows, или
    - higher highs, или
    - цена уже выше последнего подтвержденного swing high.
    """
    result: dict[str, Any] = {
        "enough_highs": len(swing_highs) >= 2,
        "enough_lows": len(swing_lows) >= 2,
        "last_two_swing_highs": swing_highs[-2:] if len(swing_highs) >= 2 else None,
        "last_two_swing_lows": swing_lows[-2:] if len(swing_lows) >= 2 else None,
        "higher_highs": False,
        "higher_lows": False,
        "close_above_last_swing_high": False,
        "structure_ok": False,
    }

    if len(swing_highs) >= 2:
        prev_high = swing_highs[-2][1]
        last_high = swing_highs[-1][1]
        result["higher_highs"] = last_high > prev_high

    if len(swing_lows) >= 2:
        prev_low = swing_lows[-2][1]
        last_low = swing_lows[-1][1]
        result["higher_lows"] = last_low > prev_low

    if len(swing_highs) >= 1:
        last_confirmed_high = swing_highs[-1][1]
        result["close_above_last_swing_high"] = last_close > last_confirmed_high

    # Мягкое правило структуры:
    # рынок считаем конструктивным, если есть хотя бы один уверенный бычий признак.
    result["structure_ok"] = any(
        [
            result["higher_lows"],
            result["higher_highs"],
            result["close_above_last_swing_high"],
        ]
    )

    return result


# =========================
# Валидация входных данных
# =========================

def validate_ohlcv_dataframe(df: pd.DataFrame) -> None:
    """
    Проверка базовой корректности входного DataFrame.
    """
    required_cols = {"open", "high", "low", "close", "volume"}
    missing = required_cols - set(df.columns)
    if missing:
        raise ValueError(f"В df не хватает колонок: {sorted(missing)}")

    if df.empty:
        raise ValueError("df пустой")

    if not df.index.is_monotonic_increasing:
        # Это не критично, но лучше явно отсортировать заранее
        raise ValueError("Индекс df должен быть отсортирован по времени по возрастанию")

    numeric_cols = ["open", "high", "low", "close", "volume"]
    if df[numeric_cols].isnull().any().any():
        raise ValueError("В OHLCV данных есть NaN")

    # Базовая sanity check для свечей
    invalid_rows = (
        (df["high"] < df["low"]) |
        (df["high"] < df["open"]) |
        (df["high"] < df["close"]) |
        (df["low"] > df["open"]) |
        (df["low"] > df["close"])
    )
    if invalid_rows.any():
        raise ValueError("Обнаружены некорректные OHLC строки")


# =========================
# Основной фильтр
# =========================

def trend_filter_12h(
    df: pd.DataFrame,
    config: TrendFilter12hConfig | None = None,
) -> TrendFilter12hResult:
    """
    Фильтр старшего 12h-контекста для LONG на spot.

    Логика:
    1. Проверяем обязательные условия (hard conditions)
    2. Проверяем мягкие условия (soft conditions)
    3. Если все обязательные выполнены и soft_score >= порога,
       то разрешаем дальше искать сетап на 4h / триггер на 1h

    Ожидается:
    - df содержит только закрытые 12h свечи
    - колонки: open, high, low, close, volume
    - строки идут от старых к новым
    """
    if config is None:
        config = TrendFilter12hConfig()

    validate_ohlcv_dataframe(df)

    # Минимум истории нужен, чтобы EMA200 и slope были адекватными
    required_rows = max(
        config.min_required_rows,
        config.ema_slow_period + config.ema_slope_lookback + 10,
    )
    if len(df) < required_rows:
        return TrendFilter12hResult(
            passed=False,
            hard_passed=False,
            soft_score=0,
            soft_score_max=len(SOFT_CONDITION_KEYS),
            reason="Недостаточно данных для 12h trend filter",
            details={
                "required_rows": required_rows,
                "actual_rows": len(df),
                "config": asdict(config),
            },
        )

    data = df.copy()

    # -------------------------
    # Считаем индикаторы
    # -------------------------
    data["ema_fast"] = ema(data["close"], config.ema_fast_period)
    data["ema_mid"] = ema(data["close"], config.ema_mid_period)
    data["ema_slow"] = ema(data["close"], config.ema_slow_period)
    data["atr"] = atr(data, config.atr_period)

    adx_df = adx_components(data, config.adx_period)
    data = pd.concat([data, adx_df], axis=1)

    last = data.iloc[-1]
    prev = data.iloc[-2]

    # -------------------------
    # Hard conditions
    # -------------------------
    # Это обязательные условия.
    # Если хотя бы одно не выполнено — LONG дальше не рассматриваем.
    # -------------------------

    # 1) Цена выше EMA200
    close_above_ema200 = bool(last["close"] > last["ema_slow"])

    # 2) EMA50 выше EMA200
    ema50_above_ema200 = bool(last["ema_mid"] > last["ema_slow"])

    # 3) EMA200 имеет положительный наклон
    ema_slow_past = data["ema_slow"].iloc[-1 - config.ema_slope_lookback]
    ema200_slope_up = bool(last["ema_slow"] > ema_slow_past)

    # 4) Цена не слишком вытянута от EMA20
    # Если рынок уже "улетел", вход с 4h/1h часто получается запоздалым.
    if pd.isna(last["atr"]) or last["atr"] <= 0:
        not_overextended = False
        overextension_atr = None
        overextension_limit = None
    else:
        overextension_atr = float((last["close"] - last["ema_fast"]) / last["atr"])
        overextension_limit = float(
            last["ema_fast"] + config.max_overextension_atr * last["atr"]
        )
        not_overextended = bool(overextension_atr <= config.max_overextension_atr)

    hard_conditions = {
        "close_above_ema200": close_above_ema200,
        "ema50_above_ema200": ema50_above_ema200,
        "ema200_slope_up": ema200_slope_up,
        "not_overextended": not_overextended,
    }

    hard_passed = all(hard_conditions.values())

    # -------------------------
    # Soft conditions
    # -------------------------
    # Это дополнительные признаки хорошего трендового режима.
    # Для разрешения сделки нужно пройти хотя бы часть из них.
    # -------------------------

    # 1) Bullish EMA stack: EMA20 > EMA50 > EMA200
    bullish_ema_stack = bool(
        (last["ema_fast"] > last["ema_mid"]) and
        (last["ema_mid"] > last["ema_slow"])
    )

    # 2) ADX сильный
    adx_strong = bool(pd.notna(last["adx"]) and last["adx"] >= config.min_adx)

    # 3) ADX растет + бычье доминирование DI
    adx_rising_bullish = bool(
        pd.notna(last["adx"]) and
        pd.notna(prev["adx"]) and
        pd.notna(last["plus_di"]) and
        pd.notna(last["minus_di"]) and
        (last["adx"] > prev["adx"]) and
        (last["plus_di"] > last["minus_di"])
    )

    # 4) Рынок имеет конструктивную структуру
    swing_highs, swing_lows = find_confirmed_swings(
        data,
        left_bars=config.swing_left_bars,
        right_bars=config.swing_right_bars,
    )
    structure = evaluate_market_structure(
        swing_highs=swing_highs,
        swing_lows=swing_lows,
        last_close=float(last["close"]),
    )
    market_structure_ok = bool(structure["structure_ok"])

    soft_conditions = {
        "bullish_ema_stack": bullish_ema_stack,
        "adx_strong": adx_strong,
        "adx_rising_bullish": adx_rising_bullish,
        "market_structure_ok": market_structure_ok,
    }

    soft_score = sum(int(v) for v in soft_conditions.values())
    soft_score_max = len(soft_conditions)

    # -------------------------
    # Финальное решение
    # -------------------------
    passed = hard_passed and (soft_score >= config.min_soft_conditions_passed)

    if passed:
        reason = "Trend 12h OK"
    else:
        failed_hard = [k for k, v in hard_conditions.items() if not v]
        failed_soft = [k for k, v in soft_conditions.items() if not v]

        if not hard_passed:
            reason = f"Trend 12h rejected: hard conditions failed: {failed_hard}"
        else:
            reason = (
                "Trend 12h rejected: not enough soft confirmations: "
                f"{soft_score}/{soft_score_max}; failed: {failed_soft}"
            )

    # -------------------------
    # Детали для логов / дебага
    # -------------------------
    details: dict[str, Any] = {
        "config": asdict(config),
        "last_candle": {
            "close": float(last["close"]),
            "ema_fast": float(last["ema_fast"]),
            "ema_mid": float(last["ema_mid"]),
            "ema_slow": float(last["ema_slow"]),
            "atr": float(last["atr"]) if pd.notna(last["atr"]) else None,
            "plus_di": float(last["plus_di"]) if pd.notna(last["plus_di"]) else None,
            "minus_di": float(last["minus_di"]) if pd.notna(last["minus_di"]) else None,
            "adx": float(last["adx"]) if pd.notna(last["adx"]) else None,
        },
        "hard_conditions": hard_conditions,
        "soft_conditions": soft_conditions,
        "soft_score_required": config.min_soft_conditions_passed,
        "soft_score_actual": soft_score,
        "ema200_slope": {
            "lookback_bars": config.ema_slope_lookback,
            "ema200_now": float(last["ema_slow"]),
            "ema200_past": float(ema_slow_past),
            "slope_up": ema200_slope_up,
        },
        "overextension": {
            "overextension_atr": overextension_atr,
            "max_allowed_atr": config.max_overextension_atr,
            "limit_price": overextension_limit,
            "not_overextended": not_overextended,
        },
        "structure": structure,
    }

    return TrendFilter12hResult(
        passed=passed,
        hard_passed=hard_passed,
        soft_score=soft_score,
        soft_score_max=soft_score_max,
        reason=reason,
        details=details,
    )

# Единый источник количества soft-условий
SOFT_CONDITION_KEYS: tuple[str, ...] = (
    "bullish_ema_stack",
    "adx_strong",
    "adx_rising_bullish",
    "market_structure_ok",
)