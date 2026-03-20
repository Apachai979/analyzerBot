from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any

import pandas as pd

from analyzes.rsi_analyzer import RSIAnalyzer
from analyzes.setup_filter_4h import SetupFilter4hResult, rsi
from analyzes.trend_filter_12h_v2 import (
    adx_components,
    atr,
    ema,
    evaluate_market_structure,
    find_confirmed_swings,
    validate_ohlcv_dataframe,
)


SOFT_CONDITION_KEYS: tuple[str, ...] = (
    "reclaimed_ema20",
    "bullish_momentum",
    "rsi_constructive",
    "rsi_bullish_divergence",
    "volume_supportive",
    "breakout_or_bullish_structure",
    "bullish_candle_confirmation",
    "room_to_target_ok",
)


@dataclass(slots=True)
class EntryTrigger1hConfig:
    ema_fast_period: int = 9
    ema_mid_period: int = 20
    ema_slow_period: int = 50
    atr_period: int = 14
    adx_period: int = 14
    rsi_period: int = 14
    volume_ma_period: int = 20

    swing_left_bars: int = 2
    swing_right_bars: int = 2
    local_level_lookback: int = 12

    max_extension_from_ema20_atr: float = 1.6
    stop_buffer_atr: float = 0.35
    min_reward_risk: float = 2.0
    min_adx: float = 14.0
    min_volume_ratio: float = 1.0
    max_rsi_for_entry: float = 66.0
    min_rsi_for_entry: float = 45.0

    rsi_divergence_lookback: int = 30
    rsi_divergence_pivot_window: int = 2

    min_soft_conditions_passed: int = 5
    min_required_rows: int = 180


@dataclass(slots=True)
class EntryTrigger1hResult:
    passed: bool
    hard_passed: bool
    soft_score: int
    soft_score_max: int
    reason: str
    trigger_state: str
    action: str
    entry_price: float | None
    stop_loss: float | None
    take_profit: float | None
    risk_percent: float | None
    reward_risk: float | None
    details: dict[str, Any]


def bullish_candle_pattern(last: pd.Series, prev: pd.Series) -> tuple[str | None, int]:
    """Определяет простой bullish candle confirmation для long trigger."""
    current_open = float(last["open"])
    current_close = float(last["close"])
    current_high = float(last["high"])
    current_low = float(last["low"])
    prev_open = float(prev["open"])
    prev_close = float(prev["close"])

    candle_range = current_high - current_low
    body_size = abs(current_close - current_open)
    if candle_range <= 0:
        return None, 0

    upper_shadow = current_high - max(current_open, current_close)
    lower_shadow = min(current_open, current_close) - current_low
    body_ratio = body_size / candle_range
    lower_shadow_ratio = lower_shadow / candle_range
    upper_shadow_ratio = upper_shadow / candle_range

    is_bullish = current_close > current_open
    prev_bearish = prev_close < prev_open

    if is_bullish and prev_bearish and current_close > prev_open and current_open < prev_close:
        return "bullish_engulfing", 3
    if is_bullish and lower_shadow_ratio > 0.5 and body_ratio < 0.35 and upper_shadow_ratio < 0.2:
        return "hammer", 2
    if is_bullish and body_ratio > 0.65 and current_close >= current_high - candle_range * 0.15:
        return "strong_bull_close", 2
    return None, 0


def resolve_trigger_state(
    setup_passed: bool,
    hard_conditions: dict[str, bool],
    soft_conditions: dict[str, bool],
) -> str:
    """Возвращает диагностическое состояние 1H trigger."""
    if not setup_passed:
        return "higher_timeframe_blocked"
    if not hard_conditions["not_overextended"]:
        return "chasing_move"
    if not hard_conditions["reclaim_structure_ok"]:
        return "no_reclaim"
    if not hard_conditions["risk_model_valid"]:
        return "risk_invalid"
    if soft_conditions["breakout_or_bullish_structure"] and soft_conditions["volume_supportive"]:
        return "trigger_ready"
    return "trigger_building"


def build_rsi_divergence_confirmation(data: pd.DataFrame, config: EntryTrigger1hConfig) -> dict[str, Any]:
    """Считает только RSI divergence как дополнительное soft-confirmation для 1H trigger."""
    analyzer = RSIAnalyzer(
        default_period=config.rsi_period,
        default_lookback=config.rsi_divergence_lookback,
        default_pivot_window=config.rsi_divergence_pivot_window,
    )
    _, rsi_series = analyzer.calculate_rsi(data[["close"]], period=config.rsi_period)
    divergence = analyzer._detect_rsi_divergence(
        data[["close"]],
        rsi_series,
        lookback=config.rsi_divergence_lookback,
        pivot_window=config.rsi_divergence_pivot_window,
    )

    return {
        "last_rsi": float(rsi_series.dropna().iloc[-1]) if rsi_series is not None and not rsi_series.dropna().empty else None,
        "divergence": divergence,
        "rsi_bullish_divergence": bool(divergence.get("type") == "BULLISH"),
    }


def entry_trigger_1h(
    df: pd.DataFrame,
    setup_result: SetupFilter4hResult,
    config: EntryTrigger1hConfig | None = None,
) -> EntryTrigger1hResult:
    """Ищет точный long trigger на 1H после подтвержденного 4H setup."""
    if config is None:
        config = EntryTrigger1hConfig()

    validate_ohlcv_dataframe(df)

    required_rows = max(config.min_required_rows, config.ema_slow_period + config.local_level_lookback + 10)
    if len(df) < required_rows:
        return EntryTrigger1hResult(
            passed=False,
            hard_passed=False,
            soft_score=0,
            soft_score_max=len(SOFT_CONDITION_KEYS),
            reason="Недостаточно данных для 1h entry trigger",
            trigger_state="invalid",
            action="SKIP",
            entry_price=None,
            stop_loss=None,
            take_profit=None,
            risk_percent=None,
            reward_risk=None,
            details={
                "required_rows": required_rows,
                "actual_rows": len(df),
                "config": asdict(config),
            },
        )

    if not setup_result.passed:
        return EntryTrigger1hResult(
            passed=False,
            hard_passed=False,
            soft_score=0,
            soft_score_max=len(SOFT_CONDITION_KEYS),
            reason=setup_result.reason,
            trigger_state="higher_timeframe_blocked",
            action="SKIP",
            entry_price=None,
            stop_loss=None,
            take_profit=None,
            risk_percent=None,
            reward_risk=None,
            details={
                "config": asdict(config),
                "setup_state": setup_result.setup_state,
                "setup_reason": setup_result.reason,
            },
        )

    data = df.copy()
    data["ema_fast"] = ema(data["close"], config.ema_fast_period)
    data["ema_mid"] = ema(data["close"], config.ema_mid_period)
    data["ema_slow"] = ema(data["close"], config.ema_slow_period)
    data["atr"] = atr(data, config.atr_period)
    data["rsi"] = rsi(data["close"], config.rsi_period)
    data["volume_ma"] = data["volume"].rolling(config.volume_ma_period).mean()

    adx_df = adx_components(data, config.adx_period)
    data = pd.concat([data, adx_df], axis=1)

    last = data.iloc[-1]
    prev = data.iloc[-2]
    last_pos = len(data) - 1

    swing_highs, swing_lows = find_confirmed_swings(
        data,
        left_bars=config.swing_left_bars,
        right_bars=config.swing_right_bars,
    )
    structure = evaluate_market_structure(
        swing_highs=swing_highs,
        swing_lows=swing_lows,
        last_close=float(last["close"]),
        last_pos=last_pos,
    )

    atr_value = float(last["atr"]) if pd.notna(last["atr"]) else None
    entry_price = float(last["close"])
    current_extension_atr = None
    if atr_value and atr_value > 0:
        current_extension_atr = float((last["close"] - last["ema_mid"]) / atr_value)

    recent = data.iloc[-config.local_level_lookback :]
    recent_high = float(recent["high"].max())
    recent_low = float(recent["low"].min())
    recent_high_before_last = float(recent["high"].iloc[:-1].max()) if len(recent) > 1 else recent_high

    reclaimed_ema20 = bool(last["close"] > last["ema_mid"])
    price_above_ema50 = bool(last["close"] > last["ema_slow"])
    ema_stack_ok = bool(last["ema_fast"] > last["ema_mid"] > last["ema_slow"])
    breakout_of_recent_high = bool(last["close"] > recent_high_before_last)
    breakout_or_bullish_structure = bool(breakout_of_recent_high or structure["higher_lows"])

    pattern_name, pattern_strength = bullish_candle_pattern(last, prev)
    bullish_candle_confirmation = pattern_name is not None

    volume_ratio = None
    if pd.notna(last["volume_ma"]) and last["volume_ma"] > 0:
        volume_ratio = float(last["volume"] / last["volume_ma"])
    volume_supportive = bool(volume_ratio is not None and volume_ratio >= config.min_volume_ratio)

    bullish_momentum = bool(
        pd.notna(last["adx"]) and last["adx"] >= config.min_adx and
        pd.notna(last["plus_di"]) and pd.notna(last["minus_di"]) and
        last["plus_di"] > last["minus_di"]
    )
    rsi_constructive = bool(
        pd.notna(last["rsi"]) and config.min_rsi_for_entry <= last["rsi"] <= config.max_rsi_for_entry
    )
    rsi_confirmation = build_rsi_divergence_confirmation(data, config)

    last_confirmed_low = swing_lows[-1] if swing_lows else None
    stop_anchor = recent_low
    if last_confirmed_low is not None:
        stop_anchor = min(stop_anchor, last_confirmed_low.price)

    stop_loss = None
    take_profit = None
    reward_risk = None
    risk_percent = None
    risk_model_valid = False
    room_to_target_ok = False

    if atr_value and atr_value > 0:
        stop_loss = float(stop_anchor - config.stop_buffer_atr * atr_value)
        risk = entry_price - stop_loss
        if risk > 0:
            take_profit = float(entry_price + risk * config.min_reward_risk)
            reward = take_profit - entry_price
            reward_risk = float(reward / risk) if risk > 0 else None
            risk_percent = float(risk / entry_price * 100)
            room_to_target_ok = recent_high <= take_profit
            risk_model_valid = bool(reward_risk is not None and reward_risk >= config.min_reward_risk)

    reclaim_structure_ok = bool(reclaimed_ema20 and price_above_ema50)
    not_overextended = bool(
        current_extension_atr is not None and current_extension_atr <= config.max_extension_from_ema20_atr
    )

    hard_conditions = {
        "setup_passed": bool(setup_result.passed),
        "reclaim_structure_ok": reclaim_structure_ok,
        "ema_stack_ok": ema_stack_ok,
        "not_overextended": not_overextended,
        "risk_model_valid": risk_model_valid,
    }
    hard_passed = all(hard_conditions.values())

    soft_conditions = {
        "reclaimed_ema20": reclaimed_ema20,
        "bullish_momentum": bullish_momentum,
        "rsi_constructive": rsi_constructive,
        "rsi_bullish_divergence": rsi_confirmation["rsi_bullish_divergence"],
        "volume_supportive": volume_supportive,
        "breakout_or_bullish_structure": breakout_or_bullish_structure,
        "bullish_candle_confirmation": bullish_candle_confirmation,
        "room_to_target_ok": room_to_target_ok,
    }
    soft_score = sum(int(v) for v in soft_conditions.values())
    soft_score_max = len(soft_conditions)

    passed = hard_passed and soft_score >= config.min_soft_conditions_passed
    trigger_state = resolve_trigger_state(
        setup_passed=setup_result.passed,
        hard_conditions=hard_conditions,
        soft_conditions=soft_conditions,
    )

    if passed:
        reason = "1h trigger OK"
        action = "ENTER"
    else:
        failed_hard = [k for k, v in hard_conditions.items() if not v]
        failed_soft = [k for k, v in soft_conditions.items() if not v]
        if not hard_passed:
            reason = f"1h trigger rejected: hard conditions failed: {failed_hard}"
            action = "SKIP"
        else:
            reason = (
                "1h trigger rejected: not enough soft confirmations: "
                f"{soft_score}/{soft_score_max}; failed: {failed_soft}"
            )
            action = "WAIT_BETTER"

    details: dict[str, Any] = {
        "config": asdict(config),
        "setup_context": {
            "setup_state": setup_result.setup_state,
            "setup_reason": setup_result.reason,
        },
        "last_candle": {
            "open": float(last["open"]),
            "high": float(last["high"]),
            "low": float(last["low"]),
            "close": float(last["close"]),
            "ema_fast": float(last["ema_fast"]),
            "ema_mid": float(last["ema_mid"]),
            "ema_slow": float(last["ema_slow"]),
            "atr": float(last["atr"]) if pd.notna(last["atr"]) else None,
            "rsi": float(last["rsi"]) if pd.notna(last["rsi"]) else None,
            "plus_di": float(last["plus_di"]) if pd.notna(last["plus_di"]) else None,
            "minus_di": float(last["minus_di"]) if pd.notna(last["minus_di"]) else None,
            "adx": float(last["adx"]) if pd.notna(last["adx"]) else None,
            "volume": float(last["volume"]),
            "volume_ma": float(last["volume_ma"]) if pd.notna(last["volume_ma"]) else None,
            "volume_ratio": volume_ratio,
            "current_extension_atr": current_extension_atr,
        },
        "hard_conditions": hard_conditions,
        "soft_conditions": soft_conditions,
        "soft_condition_keys": SOFT_CONDITION_KEYS,
        "soft_score_required": config.min_soft_conditions_passed,
        "soft_score_actual": soft_score,
        "pattern": {
            "name": pattern_name,
            "strength": pattern_strength,
        },
        "rsi_confirmation": rsi_confirmation,
        "local_levels": {
            "recent_high": recent_high,
            "recent_high_before_last": recent_high_before_last,
            "recent_low": recent_low,
            "breakout_of_recent_high": breakout_of_recent_high,
        },
        "risk_model": {
            "entry_price": entry_price,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "reward_risk": reward_risk,
            "risk_percent": risk_percent,
            "risk_model_valid": risk_model_valid,
        },
        "structure": structure,
        "trigger_state": trigger_state,
    }

    return EntryTrigger1hResult(
        passed=passed,
        hard_passed=hard_passed,
        soft_score=soft_score,
        soft_score_max=soft_score_max,
        reason=reason,
        trigger_state=trigger_state,
        action=action,
        entry_price=entry_price if passed else None,
        stop_loss=stop_loss if passed else None,
        take_profit=take_profit if passed else None,
        risk_percent=risk_percent if passed else None,
        reward_risk=reward_risk if passed else None,
        details=details,
    )