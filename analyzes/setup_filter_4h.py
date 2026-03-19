from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any

import numpy as np
import pandas as pd

from analyzes.obv_analyzer_v3 import OBVAnalyzerV3, OBVPolicy
from analyzes.trend_filter_12h_v2 import (
    adx_components,
    atr,
    ema,
    evaluate_market_structure,
    find_confirmed_swings,
    rma,
    validate_ohlcv_dataframe,
)


SOFT_CONDITION_KEYS: tuple[str, ...] = (
    "touched_working_zone",
    "reclaimed_ema20",
    "rsi_reset_healthy",
    "adx_acceptable",
    "di_bullish",
    "bullish_local_structure",
    "near_ema20_after_reclaim",
    "obv_bullish_state",
    "obv_strength_supportive",
    "obv_bullish_divergence",
)


@dataclass(slots=True)
class SetupFilter4hConfig:
    # EMA
    ema_fast_period: int = 20
    ema_mid_period: int = 50
    ema_slow_period: int = 200

    # ATR / ADX / RSI
    atr_period: int = 14
    adx_period: int = 14
    rsi_period: int = 14
    volume_ma_period: int = 20

    # Hard-правила
    min_adx: float = 16.0
    max_reextension_atr: float = 1.8
    max_pullback_below_ema200_atr: float = 0.5
    pullback_lookback_bars: int = 12
    pullback_touch_tolerance_atr: float = 0.35
    min_pullback_depth_atr: float = 0.8

    # Soft-правила
    preferred_reclaim_extension_atr: float = 0.8
    min_rsi_reset: float = 38.0
    max_rsi_reset: float = 58.0
    min_reclaim_volume_ratio: float = 1.0

    # OBV soft-confirmation
    obv_ma_period: int = 20
    obv_fast_ema_period: int = 10
    obv_slow_ema_period: int = 30
    obv_trend_lookback: int = 5
    obv_divergence_lookback: int = 30
    obv_pivot_window: int = 2
    obv_min_confidence: int = 60
    obv_min_normalized_strength: float = 3.0

    # Свинги
    swing_left_bars: int = 2
    swing_right_bars: int = 2

    # Общие настройки
    min_soft_conditions_passed: int = 5
    min_required_rows: int = 220


@dataclass(slots=True)
class SetupFilter4hResult:
    passed: bool
    hard_passed: bool
    soft_score: int
    soft_score_max: int
    reason: str
    setup_state: str
    details: dict[str, Any]


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """Вычисляет RSI по Уайлдеру."""
    delta = series.diff()
    gains = delta.clip(lower=0)
    losses = -delta.clip(upper=0)

    avg_gain = rma(gains, period)
    avg_loss = rma(losses, period)

    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi_series = 100 - (100 / (1 + rs))

    no_loss_mask = (avg_loss == 0) & (avg_gain > 0)
    flat_mask = (avg_loss == 0) & (avg_gain == 0)
    rsi_series = rsi_series.mask(no_loss_mask, 100.0)
    rsi_series = rsi_series.mask(flat_mask, 50.0)
    return rsi_series


def evaluate_pullback(
    data: pd.DataFrame,
    config: SetupFilter4hConfig,
    last: pd.Series,
) -> dict[str, Any]:
    """Оценивает, был ли на 4H здоровый откат в рабочую зону continuation-сетапа."""
    recent = data.iloc[-config.pullback_lookback_bars :].copy()
    recent_low = float(recent["low"].min())
    recent_high = float(recent["high"].max())
    recent_low_idx = recent["low"].idxmin()
    recent_high_idx = recent["high"].idxmax()

    if pd.isna(last["atr"]) or last["atr"] <= 0:
        return {
            "recent_low": recent_low,
            "recent_high": recent_high,
            "recent_low_index": recent_low_idx,
            "recent_high_index": recent_high_idx,
            "pullback_depth_atr": None,
            "current_extension_atr": None,
            "touched_ema20_zone": False,
            "touched_ema50_zone": False,
            "pullback_happened": False,
            "near_ema20_after_reclaim": False,
            "pullback_not_too_deep": False,
        }

    atr_value = float(last["atr"])
    ema_fast_value = float(last["ema_fast"])
    ema_mid_value = float(last["ema_mid"])
    ema_slow_value = float(last["ema_slow"])
    close_value = float(last["close"])

    pullback_depth_atr = float((recent_high - recent_low) / atr_value)
    current_extension_atr = float((close_value - ema_fast_value) / atr_value)

    touch_buffer = config.pullback_touch_tolerance_atr * atr_value
    touched_ema20_zone = recent_low <= ema_fast_value + touch_buffer
    touched_ema50_zone = recent_low <= ema_mid_value + touch_buffer

    pullback_happened = bool(
        touched_ema20_zone or
        touched_ema50_zone or
        pullback_depth_atr >= config.min_pullback_depth_atr
    )

    pullback_not_too_deep = bool(
        recent_low >= ema_slow_value - config.max_pullback_below_ema200_atr * atr_value
    )
    near_ema20_after_reclaim = bool(current_extension_atr <= config.preferred_reclaim_extension_atr)

    return {
        "recent_low": recent_low,
        "recent_high": recent_high,
        "recent_low_index": recent_low_idx,
        "recent_high_index": recent_high_idx,
        "pullback_depth_atr": pullback_depth_atr,
        "current_extension_atr": current_extension_atr,
        "touched_ema20_zone": touched_ema20_zone,
        "touched_ema50_zone": touched_ema50_zone,
        "pullback_happened": pullback_happened,
        "near_ema20_after_reclaim": near_ema20_after_reclaim,
        "pullback_not_too_deep": pullback_not_too_deep,
    }


def resolve_setup_state(
    trend_bias_passed: bool,
    hard_conditions: dict[str, bool],
    soft_conditions: dict[str, bool],
) -> str:
    """Возвращает диагностическое состояние 4H сетапа."""
    if not trend_bias_passed:
        return "higher_timeframe_blocked"
    if not hard_conditions["pullback_happened"]:
        return "no_pullback"
    if not hard_conditions["pullback_not_too_deep"] or not hard_conditions["structure_not_broken"]:
        return "trend_breakdown"
    if not hard_conditions["not_reoverextended"]:
        return "too_extended"
    if hard_conditions["pullback_happened"] and not soft_conditions["reclaimed_ema20"]:
        return "healthy_pullback"
    if soft_conditions["reclaimed_ema20"] and not soft_conditions["near_ema20_after_reclaim"]:
        return "reclaim_in_progress"
    if all(hard_conditions.values()) and all(soft_conditions.values()):
        return "setup_ok"
    if all(hard_conditions.values()):
        return "setup_building"
    return "invalid"


def build_obv_confirmation(df: pd.DataFrame, config: SetupFilter4hConfig) -> dict[str, Any]:
    """Считает OBV-признаки как дополнительное подтверждение 4H continuation setup."""
    analyzer = OBVAnalyzerV3(
        policy=OBVPolicy(
            ma_period=config.obv_ma_period,
            fast_ema_period=config.obv_fast_ema_period,
            slow_ema_period=config.obv_slow_ema_period,
            trend_lookback=config.obv_trend_lookback,
            divergence_lookback=config.obv_divergence_lookback,
            pivot_window=config.obv_pivot_window,
            min_confidence_for_alert=config.obv_min_confidence,
            cooldown_seconds=0,
            alert_on_change_only=False,
        )
    )

    features = analyzer.compute_obv_features(df[["close", "volume"]])
    decision = analyzer.classify_obv_state(features, previous_state=None)

    if not features.get("ok"):
        return {
            "features": features,
            "decision": decision,
            "obv_bullish_state": False,
            "obv_strength_supportive": False,
            "obv_bullish_divergence": False,
        }

    normalized_strength = float(features.get("normalized_strength", 0.0))
    divergence_type = features.get("divergence", {}).get("type")

    return {
        "features": features,
        "decision": decision,
        "obv_bullish_state": bool(
            decision.get("state") == "BULLISH" and
            decision.get("confidence", 0) >= config.obv_min_confidence
        ),
        "obv_strength_supportive": bool(
            features.get("obv_slope", 0) > 0 and
            normalized_strength >= config.obv_min_normalized_strength
        ),
        "obv_bullish_divergence": bool(divergence_type == "BULLISH"),
    }


def setup_filter_4h(
    df: pd.DataFrame,
    trend_bias_passed: bool,
    config: SetupFilter4hConfig | None = None,
    trend_bias_reason: str | None = None,
) -> SetupFilter4hResult:
    """Оценивает, есть ли на 4H качественный long setup внутри разрешенного 12H тренда."""
    if config is None:
        config = SetupFilter4hConfig()

    validate_ohlcv_dataframe(df)

    required_rows = max(
        config.min_required_rows,
        config.ema_slow_period + config.pullback_lookback_bars + 10,
    )
    if len(df) < required_rows:
        return SetupFilter4hResult(
            passed=False,
            hard_passed=False,
            soft_score=0,
            soft_score_max=len(SOFT_CONDITION_KEYS),
            reason="Недостаточно данных для 4h setup filter",
            setup_state="invalid",
            details={
                "required_rows": required_rows,
                "actual_rows": len(df),
                "config": asdict(config),
            },
        )

    if not trend_bias_passed:
        return SetupFilter4hResult(
            passed=False,
            hard_passed=False,
            soft_score=0,
            soft_score_max=len(SOFT_CONDITION_KEYS),
            reason=trend_bias_reason or "12h trend bias does not allow long setup search",
            setup_state="higher_timeframe_blocked",
            details={
                "config": asdict(config),
                "trend_bias_passed": trend_bias_passed,
                "trend_bias_reason": trend_bias_reason,
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

    pullback = evaluate_pullback(data, config, last)

    last_confirmed_low = swing_lows[-1] if swing_lows else None
    structure_not_broken = True
    if last_confirmed_low is not None:
        structure_not_broken = pullback["recent_low"] >= last_confirmed_low.price

    close_above_ema200 = bool(last["close"] > last["ema_slow"])
    ema50_above_ema200 = bool(last["ema_mid"] > last["ema_slow"])

    not_reoverextended = False
    if pullback["current_extension_atr"] is not None:
        not_reoverextended = bool(
            pullback["current_extension_atr"] <= config.max_reextension_atr
        )

    hard_conditions = {
        "trend_bias_passed": bool(trend_bias_passed),
        "close_above_ema200": close_above_ema200,
        "ema50_above_ema200": ema50_above_ema200,
        "pullback_happened": bool(pullback["pullback_happened"]),
        "pullback_not_too_deep": bool(pullback["pullback_not_too_deep"]),
        "structure_not_broken": bool(structure_not_broken),
        "not_reoverextended": not_reoverextended,
    }
    hard_passed = all(hard_conditions.values())

    recent_rsi = data["rsi"].iloc[-config.pullback_lookback_bars :]
    recent_rsi_min = float(recent_rsi.min()) if recent_rsi.notna().any() else None

    reclaimed_ema20 = bool(last["close"] > last["ema_fast"])
    touched_working_zone = bool(
        pullback["touched_ema20_zone"] or pullback["touched_ema50_zone"]
    )
    rsi_reset_healthy = bool(
        recent_rsi_min is not None and config.min_rsi_reset <= recent_rsi_min <= config.max_rsi_reset
    )
    adx_acceptable = bool(pd.notna(last["adx"]) and last["adx"] >= config.min_adx)
    di_bullish = bool(
        pd.notna(last["plus_di"]) and
        pd.notna(last["minus_di"]) and
        last["plus_di"] > last["minus_di"]
    )
    bullish_local_structure = bool(
        structure["higher_lows"] or structure["close_above_last_swing_high"]
    )
    near_ema20_after_reclaim = bool(pullback["near_ema20_after_reclaim"])

    current_volume_ratio = None
    if pd.notna(last["volume_ma"]) and last["volume_ma"] > 0:
        current_volume_ratio = float(last["volume"] / last["volume_ma"])
    volume_supportive = bool(
        current_volume_ratio is not None and
        current_volume_ratio >= config.min_reclaim_volume_ratio and
        last["close"] >= prev["close"]
    )
    obv_confirmation = build_obv_confirmation(data, config)

    soft_conditions = {
        "touched_working_zone": touched_working_zone,
        "reclaimed_ema20": reclaimed_ema20,
        "rsi_reset_healthy": rsi_reset_healthy,
        "adx_acceptable": adx_acceptable,
        "di_bullish": di_bullish,
        "bullish_local_structure": bullish_local_structure,
        "near_ema20_after_reclaim": near_ema20_after_reclaim,
        "obv_bullish_state": obv_confirmation["obv_bullish_state"],
        "obv_strength_supportive": obv_confirmation["obv_strength_supportive"],
        "obv_bullish_divergence": obv_confirmation["obv_bullish_divergence"],
    }
    soft_score = sum(int(value) for value in soft_conditions.values())
    soft_score_max = len(soft_conditions)

    passed = hard_passed and soft_score >= config.min_soft_conditions_passed
    setup_state = resolve_setup_state(
        trend_bias_passed=trend_bias_passed,
        hard_conditions=hard_conditions,
        soft_conditions=soft_conditions,
    )

    if passed:
        reason = "4h setup OK"
    else:
        failed_hard = [key for key, value in hard_conditions.items() if not value]
        failed_soft = [key for key, value in soft_conditions.items() if not value]
        if not hard_passed:
            reason = f"4h setup rejected: hard conditions failed: {failed_hard}"
        else:
            reason = (
                "4h setup rejected: not enough soft confirmations: "
                f"{soft_score}/{soft_score_max}; failed: {failed_soft}"
            )

    details: dict[str, Any] = {
        "config": asdict(config),
        "trend_context": {
            "trend_bias_passed": trend_bias_passed,
            "trend_bias_reason": trend_bias_reason,
        },
        "last_candle": {
            "close": float(last["close"]),
            "open": float(last["open"]),
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
            "volume_ratio": current_volume_ratio,
            "volume_supportive": volume_supportive,
        },
        "hard_conditions": hard_conditions,
        "soft_conditions": soft_conditions,
        "soft_condition_keys": SOFT_CONDITION_KEYS,
        "soft_score_required": config.min_soft_conditions_passed,
        "soft_score_actual": soft_score,
        "pullback": pullback,
        "recent_rsi_min": recent_rsi_min,
        "obv": obv_confirmation,
        "structure": {
            **structure,
            "structure_not_broken": structure_not_broken,
            "last_confirmed_low": (
                {
                    "pos": last_confirmed_low.pos,
                    "index": last_confirmed_low.index,
                    "price": last_confirmed_low.price,
                }
                if last_confirmed_low is not None
                else None
            ),
        },
        "setup_state": setup_state,
    }

    return SetupFilter4hResult(
        passed=passed,
        hard_passed=hard_passed,
        soft_score=soft_score,
        soft_score_max=soft_score_max,
        reason=reason,
        setup_state=setup_state,
        details=details,
    )