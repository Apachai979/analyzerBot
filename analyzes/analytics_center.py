import numpy as np
from analyzes.time_frame_analysis import (analyze_1d_ma_macd_volume, analyze_12h_ema_macd_rsi_atr, analyze_4h_bb_stoch_ma_volume, analyze_1h_ema_macd_atr_rsi)
from analyzes.multi_timeframe_ma_analysis import (
    analyze_ma_signals,
    calculate_macd,
    analyze_volume,
    calculate_bollinger_bands,
    log_to_file,
    calculate_bollinger_bands_1D
)

def get_support_levels(df, window=20, count=3):
    """
    Находит ключевые уровни поддержки как локальные минимумы за window периодов.
    Возвращает список support_levels (цен).
    """
    lows = df['low'].rolling(window, center=True).min()
    local_mins = df[(df['low'] == lows)]['low']
    # Берем последние count уровней
    return list(local_mins.tail(count))

def handle_12h_correction_buy_signal(df, symbol="UNKNOWN"):
    """
    ШАГ 1: Ожидаем коррекцию к ключевым уровням поддержки.
    ШАГ 2: Ищем признаки замедления падения (снижение волатильности, свечные паттерны, низкий объем).
    ШАГ 3: Ждем первого подтверждения разворота (RSI/Stoch, MACD, зеленая свеча с объемом).
    ШАГ 4: Принимаем решение — кластер из 2-3 сигналов.
    """
    support_levels = get_support_levels(df)

    analysis = analyze_12h_ema_macd_rsi_atr(df, symbol=symbol)
    last_close = df['close'].iloc[-1]
    last_low = df['low'].iloc[-1]
    last_volume = df['volume'].iloc[-1]
    avg_volume = df['volume'].rolling(20).mean().iloc[-1]

    # ШАГ 1: Цена у поддержки?
    near_support = any(abs(last_close - lvl) / lvl < 0.01 for lvl in support_levels)

    # ШАГ 2: Снижение волатильности, свечные паттерны, низкий объем
    low_volatility = analysis['volatility'] == 'LOW'
    small_candle = abs(df['close'].iloc[-1] - df['open'].iloc[-1]) < analysis['atr'] * 0.5 if analysis.get('atr') is not None else False
    low_volume = last_volume < avg_volume * 0.8

    # Примитивная проверка паттернов (молот, пин-бар, поглощение)
    last_candle = df.iloc[-1]
    hammer = (last_candle['close'] > last_candle['open']) and ((last_candle['low'] < last_candle['open'] - (last_candle['high'] - last_candle['low']) * 0.5))
    engulfing = (df['close'].iloc[-1] > df['open'].iloc[-1]) and (df['close'].iloc[-2] < df['open'].iloc[-2]) and (df['close'].iloc[-1] > df['open'].iloc[-2])

    # ШАГ 3: Подтверждение разворота
    rsi_confirm = analysis['rsi'] is not None and analysis['rsi'] > 30
    macd_confirm = analysis['macd_signal'] == "BUY"
    green_candle = (last_close > df['open'].iloc[-1]) and (last_volume > avg_volume * 1.2)

    # Считаем количество сигналов
    signals = [
        near_support,
        low_volatility or small_candle,
        hammer or engulfing,
        low_volume,
        rsi_confirm,
        macd_confirm,
        green_candle
    ]
    signal_count = sum(signals)

    # Решение
    decision = "WAIT"
    if signal_count >= 3:
        decision = "BUY ZONE"

    # Формируем резюме
    summary = (
        f"=== 12H Correction Buy Handler ===\n"
        f"Цена у поддержки: {near_support}\n"
        f"Снижение волатильности: {low_volatility}\n"
        f"Маленькая свеча: {small_candle}\n"
        f"Паттерн (молот/поглощение): {hammer or engulfing}\n"
        f"Низкий объем: {low_volume}\n"
        f"RSI вышел из перепроданности: {rsi_confirm}\n"
        f"MACD бычий: {macd_confirm}\n"
        f"Зеленая свеча с объемом: {green_candle}\n"
        f"Кластер сигналов: {signal_count}\n"
        f"Решение: {decision}\n"
        f"---\n"
    )

    log_to_file("correction_buy_12h_log.txt", summary)
    print(summary)

    return {
        "near_support": near_support,
        "low_volatility": low_volatility,
        "small_candle": small_candle,
        "pattern": hammer or engulfing,
        "low_volume": low_volume,
        "rsi_confirm": rsi_confirm,
        "macd_confirm": macd_confirm,
        "green_candle": green_candle,
        "signal_count": signal_count,
        "decision": decision,
        "summary": summary
    }
    
def analyze_1d_macd_signal(macd, macd_signal, macd_hist):
    """
    Анализирует MACD, MACD Signal и MACD Hist на 1D согласно торговой таблице.
    Возвращает словарь с сигналом, рекомендациями и действием.
    """
    # Бычий сигнал: MACD > Signal > 0
    if macd > macd_signal and macd_signal > 0:
        return {
            "signal": "✅ БЫЧИЙ",
            "can_buy": True,
            "can_sell": False,
            "action": "Ищем вход на покупку на коррекциях младших ТФ.",
            "description": "MACD и Signal над нулем, MACD выше Signal — бычий тренд."
        }
    # Нейтрально-бычий: MACD > 0, но падает, почти пересек Signal
    elif macd > 0 and macd_hist < 0 and abs(macd - macd_signal) < 0.05:
        return {
            "signal": "❌ НЕЙТРАЛЬНО-БЫЧИЙ",
            "can_buy": False,
            "can_sell": True,
            "action": "Закрываем покупки, фиксируем прибыль. Новых лонгов не открываем. Ждем.",
            "description": "MACD над нулем, но падает и близко к пересечению Signal."
        }
    # Медвежье пересечение: Signal > MACD, оба > 0
    elif macd_signal > macd and macd > 0 and macd_signal > 0:
        return {
            "signal": "🚫 МЕДВЕЖИЙ ПЕРЕСЕЧЕНИЕ",
            "can_buy": False,
            "can_sell": True,
            "action": "Запрет на покупки. Готовимся к продажам. Это сигнал на разворот тренда.",
            "description": "Signal выше MACD, оба над нулем — разворот к медвежьему тренду."
        }
    # Полностью медвежий: Signal > MACD, оба < 0
    elif macd_signal > macd and macd < 0 and macd_signal < 0:
        return {
            "signal": "🚫 ПОЛНОСТЬЮ МЕДВЕЖИЙ",
            "can_buy": False,
            "can_sell": True,
            "action": "Только продажи. Любые отскоки цены — это возможность шортить. Покупки запрещены.",
            "description": "Signal выше MACD, оба под нулем — сильный медвежий тренд."
        }
    # Если не попадает ни под одно условие — нейтрально
    else:
        return {
            "signal": "NEUTRAL",
            "can_buy": False,
            "can_sell": False,
            "action": "Нет четкого сигнала. Ждем подтверждения.",
            "description": "MACD/Signal не дают однозначного сигнала."
        }