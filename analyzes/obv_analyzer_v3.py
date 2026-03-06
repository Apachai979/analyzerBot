from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd


@dataclass
class OBVPolicy:
    ma_period: int = 20
    fast_ema_period: int = 10
    slow_ema_period: int = 30
    trend_lookback: int = 5
    divergence_lookback: int = 30
    pivot_window: int = 2
    min_confidence_for_alert: int = 65
    cooldown_seconds: int = 900
    alert_on_change_only: bool = True


class JSONStateStore:
    def __init__(self, file_path: str = "data/obv_state_v3.json"):
        self.file_path = file_path
        os.makedirs(os.path.dirname(file_path), exist_ok=True)

    def _load(self) -> Dict[str, Any]:
        if not os.path.exists(self.file_path):
            return {}
        try:
            with open(self.file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def _save(self, payload: Dict[str, Any]) -> None:
        with open(self.file_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

    def get(self, key: str) -> Optional[Dict[str, Any]]:
        return self._load().get(key)

    def set(self, key: str, value: Dict[str, Any]) -> None:
        payload = self._load()
        payload[key] = value
        self._save(payload)


class OBVAnalyzerV3:
    def __init__(self, policy: Optional[OBVPolicy] = None, store: Optional[JSONStateStore] = None):
        self.policy = policy or OBVPolicy()
        self.store = store or JSONStateStore()

    @staticmethod
    def _key(symbol: str, timeframe: str) -> str:
        return f"{symbol}::{timeframe}"

    def _validate_df(self, df: pd.DataFrame) -> Optional[str]:
        if df is None or df.empty:
            return "Пустой DataFrame"
        required = {"close", "volume"}
        missing = required.difference(df.columns)
        if missing:
            return f"Нет обязательных колонок: {', '.join(sorted(missing))}"
        return None

    @staticmethod
    def _detect_divergence(price: pd.Series, obv: pd.Series, lookback: int, pivot_window: int) -> Dict[str, Any]:
        work = pd.DataFrame({"close": price, "obv": obv}).dropna().tail(lookback).reset_index(drop=True)
        if len(work) < (pivot_window * 2 + 3):
            return {"type": "NONE", "details": "Недостаточно данных для дивергенции"}

        closes = work["close"].values
        obv_values = work["obv"].values

        pivot_lows: List[int] = []
        pivot_highs: List[int] = []

        for idx in range(pivot_window, len(work) - pivot_window):
            window_prices = closes[idx - pivot_window : idx + pivot_window + 1]
            center_price = closes[idx]
            if center_price == np.min(window_prices):
                pivot_lows.append(idx)
            if center_price == np.max(window_prices):
                pivot_highs.append(idx)

        if len(pivot_lows) >= 2:
            prev_idx, last_idx = pivot_lows[-2], pivot_lows[-1]
            prev_price_low = float(closes[prev_idx])
            last_price_low = float(closes[last_idx])
            prev_obv_low = float(obv_values[prev_idx])
            last_obv_low = float(obv_values[last_idx])
            if last_price_low < prev_price_low and last_obv_low > prev_obv_low:
                return {
                    "type": "BULLISH",
                    "details": (
                        f"Бычья дивергенция: цена low {prev_price_low:.4f} -> {last_price_low:.4f}, "
                        f"OBV low {prev_obv_low:.2f} -> {last_obv_low:.2f}"
                    ),
                }

        if len(pivot_highs) >= 2:
            prev_idx, last_idx = pivot_highs[-2], pivot_highs[-1]
            prev_price_high = float(closes[prev_idx])
            last_price_high = float(closes[last_idx])
            prev_obv_high = float(obv_values[prev_idx])
            last_obv_high = float(obv_values[last_idx])
            if last_price_high > prev_price_high and last_obv_high < prev_obv_high:
                return {
                    "type": "BEARISH",
                    "details": (
                        f"Медвежья дивергенция: цена high {prev_price_high:.4f} -> {last_price_high:.4f}, "
                        f"OBV high {prev_obv_high:.2f} -> {last_obv_high:.2f}"
                    ),
                }

        return {"type": "NONE", "details": "OBV дивергенция не обнаружена"}

    def compute_obv_features(self, df: pd.DataFrame) -> Dict[str, Any]:
        error = self._validate_df(df)
        if error:
            return {"ok": False, "error": error}

        work = df[["close", "volume"]].copy()
        work["price_diff"] = work["close"].diff().fillna(0)
        signed_volume = np.where(
            work["price_diff"] > 0,
            work["volume"],
            np.where(work["price_diff"] < 0, -work["volume"], 0),
        )
        obv = pd.Series(signed_volume, index=work.index).cumsum()

        if obv.dropna().empty:
            return {"ok": False, "error": "Недостаточно данных для OBV"}

        obv_ma = obv.rolling(self.policy.ma_period).mean()
        obv_ema_fast = obv.ewm(span=self.policy.fast_ema_period, adjust=False).mean()
        obv_ema_slow = obv.ewm(span=self.policy.slow_ema_period, adjust=False).mean()

        last_obv = float(obv.iloc[-1])
        prev_obv = float(obv.iloc[-2]) if len(obv) > 1 else last_obv
        trend_idx = self.policy.trend_lookback + 1
        obv_ref = float(obv.iloc[-trend_idx]) if len(obv) >= trend_idx else float(obv.iloc[0])
        obv_delta = last_obv - obv_ref
        obv_slope = obv_delta / max(1, self.policy.trend_lookback)

        avg_volume = float(work["volume"].tail(self.policy.ma_period).mean()) if len(work) >= 2 else float(work["volume"].iloc[-1])
        normalized_strength = obv_delta / max(avg_volume, 1e-9)

        divergence = self._detect_divergence(
            price=work["close"],
            obv=obv,
            lookback=self.policy.divergence_lookback,
            pivot_window=self.policy.pivot_window,
        )

        return {
            "ok": True,
            "last_obv": last_obv,
            "prev_obv": prev_obv,
            "last_obv_ma": float(obv_ma.dropna().iloc[-1]) if not obv_ma.dropna().empty else last_obv,
            "last_obv_ema_fast": float(obv_ema_fast.iloc[-1]),
            "last_obv_ema_slow": float(obv_ema_slow.iloc[-1]),
            "obv_delta": obv_delta,
            "obv_slope": obv_slope,
            "normalized_strength": float(normalized_strength),
            "divergence": divergence,
            "n_bars": int(len(work)),
        }

    def classify_obv_state(self, features: Dict[str, Any], previous_state: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if not features.get("ok"):
            return {
                "state": "UNKNOWN",
                "raw_state": "UNKNOWN",
                "confidence": 0,
                "reasons": [features.get("error", "Ошибка расчета")],
                "should_alert": False,
            }

        reasons: List[str] = []
        raw_state = "NEUTRAL"

        fast = features["last_obv_ema_fast"]
        slow = features["last_obv_ema_slow"]
        slope = features["obv_slope"]
        div_type = features["divergence"]["type"]

        if fast > slow and slope > 0:
            raw_state = "BULLISH"
            reasons.append("OBV EMA fast > slow и наклон положительный")
        elif fast < slow and slope < 0:
            raw_state = "BEARISH"
            reasons.append("OBV EMA fast < slow и наклон отрицательный")
        else:
            reasons.append("EMA/наклон OBV дают смешанный сигнал")

        confidence = 50

        strength = abs(features["normalized_strength"])
        if strength > 10:
            confidence += 15
            reasons.append("Сильное нормализованное движение OBV")
        elif strength > 5:
            confidence += 8
            reasons.append("Умеренное нормализованное движение OBV")
        else:
            confidence -= 5
            reasons.append("Слабое нормализованное движение OBV")

        if div_type == "BULLISH" and raw_state == "BULLISH":
            confidence += 12
            reasons.append("Бычья дивергенция подтверждает рост")
        elif div_type == "BEARISH" and raw_state == "BEARISH":
            confidence += 12
            reasons.append("Медвежья дивергенция подтверждает падение")
        elif div_type in ("BULLISH", "BEARISH"):
            confidence -= 7
            reasons.append("Дивергенция против базового OBV-сигнала")

        confidence = int(max(0, min(100, confidence)))

        state = raw_state
        if previous_state and previous_state.get("state") != raw_state and self.policy.alert_on_change_only:
            reasons.append("Смена состояния относительно прошлого значения")

        now_ts = time.time()
        should_alert = confidence >= self.policy.min_confidence_for_alert

        if previous_state:
            last_alert_ts = float(previous_state.get("last_alert_ts", 0) or 0)
            if now_ts - last_alert_ts < self.policy.cooldown_seconds:
                should_alert = False
                reasons.append("В cooldown-окне, алерт подавлен")
            if self.policy.alert_on_change_only and previous_state.get("state") == state:
                should_alert = False
                reasons.append("Состояние не изменилось, алерт подавлен")

        return {
            "state": state,
            "raw_state": raw_state,
            "confidence": confidence,
            "reasons": reasons,
            "should_alert": should_alert,
        }

    def analyze(self, df: pd.DataFrame, symbol: str = "UNKNOWN", timeframe: str = "UNKNOWN", persist: bool = True) -> Dict[str, Any]:
        key = self._key(symbol, timeframe)
        previous = self.store.get(key)

        features = self.compute_obv_features(df)
        decision = self.classify_obv_state(features, previous_state=previous)

        result: Dict[str, Any] = {
            "symbol": symbol,
            "timeframe": timeframe,
            "ts": time.time(),
            "policy": asdict(self.policy),
            "features": features,
            "decision": decision,
        }

        if previous and previous.get("decision", {}).get("should_alert"):
            result["last_alert_ts"] = previous.get("ts", 0)
        else:
            result["last_alert_ts"] = previous.get("last_alert_ts", 0) if previous else 0

        if result["decision"]["should_alert"]:
            result["last_alert_ts"] = result["ts"]

        if persist:
            self.store.set(key, result)

        return result

    def format_report(self, result: Dict[str, Any]) -> str:
        symbol = result.get("symbol", "UNKNOWN")
        timeframe = result.get("timeframe", "UNKNOWN")
        decision = result.get("decision", {})
        features = result.get("features", {})

        if not features.get("ok"):
            return (
                f"=== OBV ANALYZER V3 ===\n"
                f"{symbol} [{timeframe}]\n"
                f"Статус: ERROR\n"
                f"Причина: {features.get('error', 'Неизвестная ошибка')}\n"
                f"---\n"
            )

        divergence = features.get("divergence", {})
        reasons = decision.get("reasons", [])

        return (
            f"=== OBV ANALYZER V3 ===\n"
            f"{symbol} [{timeframe}]\n"
            f"State: {decision.get('state')} (raw: {decision.get('raw_state')})\n"
            f"Confidence: {decision.get('confidence')}%\n"
            f"Alert: {'YES' if decision.get('should_alert') else 'NO'}\n"
            f"OBV: {features.get('last_obv', 0):.2f}\n"
            f"EMA({self.policy.fast_ema_period}/{self.policy.slow_ema_period}): "
            f"{features.get('last_obv_ema_fast', 0):.2f}/{features.get('last_obv_ema_slow', 0):.2f}\n"
            f"Slope: {features.get('obv_slope', 0):.4f}\n"
            f"Normalized strength: {features.get('normalized_strength', 0):.2f}\n"
            f"Divergence: {divergence.get('type', 'NONE')}\n"
            f"Divergence details: {divergence.get('details', 'n/a')}\n"
            f"Reasons:\n- " + "\n- ".join(reasons) + "\n"
            f"---\n"
        )

    def get_latest(self, symbol: str = "UNKNOWN", timeframe: str = "UNKNOWN") -> Optional[Dict[str, Any]]:
        return self.store.get(self._key(symbol, timeframe))

    def get_latest_report(self, symbol: str = "UNKNOWN", timeframe: str = "UNKNOWN") -> str:
        latest = self.get_latest(symbol=symbol, timeframe=timeframe)
        if not latest:
            return (
                f"=== OBV ANALYZER V3 ===\n"
                f"{symbol} [{timeframe}]\n"
                f"Данные еще не анализировались\n"
                f"---\n"
            )
        return self.format_report(latest)

    def analyze_obv_output(self, df, symbol="UNKNOWN", timeframe="UNKNOWN", ma_period=None, trend_lookback=None):
        """
        Совместимый адаптер с v2 API.
        ma_period и trend_lookback оставлены для обратной совместимости.
        """
        if ma_period is not None:
            self.policy.ma_period = ma_period
        if trend_lookback is not None:
            self.policy.trend_lookback = trend_lookback

        result = self.analyze(df=df, symbol=symbol, timeframe=timeframe, persist=True)
        return self.format_report(result)

    def get_latest_obv_state(self, symbol="UNKNOWN", timeframe="UNKNOWN", as_dict=False):
        """
        Совместимый адаптер с v2 API.
        """
        latest = self.get_latest(symbol=symbol, timeframe=timeframe)
        if as_dict:
            if not latest:
                return None
            return {
                "symbol": latest.get("symbol"),
                "timeframe": latest.get("timeframe"),
                "obv_state": latest.get("decision", {}).get("state"),
                "raw_state": latest.get("decision", {}).get("raw_state"),
                "confidence": latest.get("decision", {}).get("confidence"),
                "details": "; ".join(latest.get("decision", {}).get("reasons", [])),
                "updated_at": latest.get("ts"),
            }

        return self.get_latest_report(symbol=symbol, timeframe=timeframe)
