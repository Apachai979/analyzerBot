from datetime import datetime
from analyzes.multi_timeframe_ma_analysis import (
    analyze_ma_signals,
    calculate_macd,
    analyze_volume,
    calculate_bollinger_bands,
    log_to_file,
    calculate_bollinger_bands_1D
)
from analyzes.atr_rsi_stochastic import calculate_rsi, calculate_atr, calculate_stochastic

def adjust_periods_for_history(df, fast_period, slow_period, lookback_periods, min_required=6):
    """
    Если данных мало, уменьшает периоды индикаторов до максимально возможных.
    Если данных достаточно — возвращает исходные периоды.
    """
    if df is None or df.empty:
        return None
    available = len(df)
    if available < min_required:
        return None
    min_period = max(fast_period, slow_period, lookback_periods)
    if available >= min_period + 2:
        # Данных достаточно для стандартных периодов
        return fast_period, slow_period, lookback_periods
    # Если данных мало — уменьшаем периоды
    fast_period = max(2, int(available * 0.3))
    slow_period = max(3, int(available * 0.95))
    lookback_periods = max(2, available // 2)
    return fast_period, slow_period, lookback_periods

def analyze_1d_ma_macd_volume(df, symbol="UNKNOWN"):
    """
    Анализирует дневные сигналы SMA/EMA (50, 200), MACD, Volume и Bollinger Bands (SMA).
    Возвращает словарь с результатами и кратким текстовым резюме.
    """
    
    fast_period = 50
    slow_period = 200
    lookback_periods = 100

    adjusted = adjust_periods_for_history(df, fast_period, slow_period, lookback_periods)
    if adjusted is None:
        print(f"{datetime.now()} | {symbol} | Слишком мало данных для анализа 1D\n")
        return None
    fast_period, slow_period, lookback_periods = adjusted
    if slow_period < 30:
        print(f"{datetime.now()} | {symbol} | Слишком мало данных для анализа 1D\n")
        return None
    # SMA/EMA анализ
    sma_result = analyze_ma_signals(df.copy(), fast_period, slow_period, lookback_periods, symbol=f"{symbol} [1D]", ma_type="SMA")
    ema_result = analyze_ma_signals(df.copy(), fast_period, slow_period, lookback_periods, symbol=f"{symbol} [1D]", ma_type="EMA")

    # MACD анализ
    macd_df = calculate_macd(df.copy(), fast_period=12, slow_period=26, signal_period=9, symbol=f"{symbol} [1D]") 
    macd_action = macd_df.attrs.get('action') if hasattr(macd_df, 'attrs') else None
    
    # Volume анализ
    volume_res = analyze_volume(df.copy(), volume_ma_period=20, symbol=f"{symbol} [1D]")

    # Bollinger Bands анализ на SMA
    bb_sma_df = calculate_bollinger_bands_1D(df.copy(), period=20, num_std=2, ma_type="EMA", symbol=f"{symbol} [1D]", trend_direction=f"{sma_result['signal']}")
    bb_sma_signal = bb_sma_df['bb_signal'].iloc[-1] if not bb_sma_df.empty else None

    # Формируем краткое текстовое резюме
    summary = (
        f"=== 1D MA/MACD/Volume/BB Analysis ===\n"
        f"SMA(50/200) {sma_result.get('signal','n/a') if sma_result else 'n/a'}, {sma_result.get('bar','n/a') if sma_result else 'n/a'}, {sma_result.get('price_position','n/a') if sma_result else 'n/a'}, {sma_result.get('is_confidently_above_ema200','n/a') if sma_result else 'n/a'}, {sma_result.get('trading_verdict','n/a') if sma_result else 'n/a'}\n"
        f"EMA(50/200) {ema_result.get('signal','n/a') if ema_result else 'n/a'}, {ema_result.get('bar','n/a') if ema_result else 'n/a'}, {ema_result.get('price_position','n/a') if ema_result else 'n/a'}, {ema_result.get('is_confidently_above_ema200','n/a') if ema_result else 'n/a'}, {ema_result.get('trading_verdict','n/a') if ema_result else 'n/a'}\n"
        f"MACD сигнал: {macd_df.attrs.get('summary_signal')}, details: {macd_df.attrs.get('summary_details')}, action: {macd_df.attrs.get('action')}\n"
        f"Bollinger Bands SMA сигнал: {bb_sma_signal}\n"
        f"Объем: {volume_res.get('current_volume', 'n/a')} vs средний {volume_res.get('avg_volume', 'n/a')}\n"
        f"Сигнал по объему: {volume_res.get('signal', 'n/a')}, action: {volume_res.get('action', 'n/a')}\n"
        f"---\n"
    )

    # Логирование
    log_to_file("ma_macd_volume_1d_log.txt", summary)

    return {
        "sma_result": sma_result,
        "ema_result": ema_result,
        "macd_action": macd_action,  # Добавляем action от MACD
        "volume_result": volume_res,
        "bb_sma_signal": bb_sma_signal,
        "summary": summary
    }

def analyze_12h_correction_strategy(df, trend_1d, symbol="UNKNOWN"):
    """
    Детальная стратегия анализа 12h с системой "светофора".
    
    Args:
        df: DataFrame с данными 12h
        trend_1d: Тренд с 1D ("BULLISH" или "BEARISH")
        symbol: Название инструмента
    
    Returns:
        dict: Результаты анализа с итоговым действием (STOP/ATTENTION/GO)
    """
    from analyzes.multi_timeframe_ma_analysis import calculate_ema
    
    if len(df) < 50:
        return None
    
    # Определяем ожидаемое поведение на 12h
    expected_12h_direction = "DOWN" if trend_1d == "BULLISH" else "UP"
    
    # === АНАЛИЗ ПРЕДЫДУЩИХ СВЕЧЕЙ (ПОДТВЕРЖДЕНИЕ ДВИЖЕНИЯ) ===
    # Проверяем последние 3-4 свечи для подтверждения тренда коррекции/отскока
    
    current_price = df['close'].iloc[-1]
    prev_price_1 = df['close'].iloc[-2]
    prev_price_2 = df['close'].iloc[-3]
    prev_price_3 = df['close'].iloc[-4] if len(df) >= 4 else None
    
    # Подтверждение направления движения
    trend_confirmation = False
    trend_strength = 0  # 0-3 баллов за подтверждение тренда
    correction_type = ""  # "GRADUAL" (постепенная) или "SHARP" (резкая)
    
    if trend_1d == "BULLISH":
        # Ожидаем коррекцию ВНИЗ на 12H (цены должны были снижаться)
        
        # Вариант 1: Постепенная коррекция (несколько падающих свечей)
        candles_down = 0
        if prev_price_1 < prev_price_2:
            candles_down += 1
        if prev_price_2 and prev_price_3 and prev_price_2 < prev_price_3:
            candles_down += 1
            
        # Вариант 2: Резкая коррекция (одна мощная медвежья свеча)
        # Проверяем саму свечу (open → close), а не просто разницу цен закрытия
        prev_open = df['open'].iloc[-2]
        prev_close = df['close'].iloc[-2]
        prev_high = df['high'].iloc[-2]
        prev_low = df['low'].iloc[-2]
        
        # Размер тела свечи (не путать с диапазоном high-low)
        prev_candle_body = abs(prev_close - prev_open) / prev_open * 100
        is_bearish_prev = prev_close < prev_open  # Медвежья свеча (красная)
        
        # Резкая коррекция = мощная медвежья свеча >3% + цена действительно упала
        is_sharp_correction = (prev_candle_body > 3.0 and 
                              is_bearish_prev and 
                              prev_price_1 < prev_price_2)
        
        # Принимаем ЛЮБОЙ из вариантов
        if candles_down >= 1:
            trend_confirmation = True
            trend_strength = candles_down
            correction_type = "GRADUAL"
        elif is_sharp_correction:
            # Одна мощная медвежья свеча вниз - тоже валидная коррекция
            trend_confirmation = True
            trend_strength = 1
            correction_type = "SHARP"
        
    else:  # trend_1d == "BEARISH"
        # Ожидаем отскок ВВЕРХ на 12H (цены должны были расти)
        
        # Вариант 1: Постепенный отскок (несколько растущих свечей)
        candles_up = 0
        if prev_price_1 > prev_price_2:
            candles_up += 1
        if prev_price_2 and prev_price_3 and prev_price_2 > prev_price_3:
            candles_up += 1
            
        # Вариант 2: Резкий отскок (одна мощная бычья свеча)
        # Проверяем саму свечу (open → close), а не просто разницу цен закрытия
        prev_open = df['open'].iloc[-2]
        prev_close = df['close'].iloc[-2]
        prev_high = df['high'].iloc[-2]
        prev_low = df['low'].iloc[-2]
        
        # Размер тела свечи
        prev_candle_body = abs(prev_close - prev_open) / prev_open * 100
        is_bullish_prev = prev_close > prev_open  # Бычья свеча (зеленая)
        
        # Резкий отскок = мощная бычья свеча >3% + цена действительно выросла
        is_sharp_bounce = (prev_candle_body > 3.0 and 
                          is_bullish_prev and 
                          prev_price_1 > prev_price_2)
        
        # Принимаем ЛЮБОЙ из вариантов
        if candles_up >= 1:
            trend_confirmation = True
            trend_strength = candles_up
            correction_type = "GRADUAL"
        elif is_sharp_bounce:
            # Одна мощная бычья свеча вверх - тоже валидный отскок
            trend_confirmation = True
            trend_strength = 1
            correction_type = "SHARP"
    
    # Если нет подтверждения движения - не анализируем дальше
    if not trend_confirmation:
        prev_price_3_text = f"{prev_price_3:.4f}" if prev_price_3 else "n/a"
        summary = (
            f"=== 12H СТРАТЕГИЯ КОРРЕКЦИИ ===\n"
            f"Тренд 1D: {trend_1d}\n"
            f"Ожидаем на 12H: {expected_12h_direction}\n"
            f"\n⚠️ ОТКЛОНЕНО: Нет подтверждения движения в ожидаемом направлении\n"
            f"Последние 3 свечи не показывают четкой коррекции/отскока.\n"
            f"Цены: {prev_price_3_text} → {prev_price_2:.4f} → {prev_price_1:.4f} → {current_price:.4f}\n"
            f"Нет ни постепенного движения, ни резкой коррекционной свечи (>3%)\n"
            f"\n🔴 ДЕЙСТВИЕ: НЕ ВХОДИТЬ - Дождитесь подтверждения тренда\n"
            f"---\n"
        )
        log_to_file("12h_correction_strategy_log.txt", summary)
        return {
            "action": "STOP",
            "signal_strength": 0,
            "signals": ["⚠️ Нет подтверждения движения коррекции/отскока"],
            "trend_confirmation": False,
            "summary": summary
        }
    
    # === ИНДИКАТОРЫ ===
    
    # 1. EMA (20, 50) - анализ отскока
    ema20 = calculate_ema(df, 20)
    ema50 = calculate_ema(df, 50)
    
    ema20_current = ema20.iloc[-1]
    ema50_current = ema50.iloc[-1]
    
    # Расстояние до EMA
    distance_to_ema20 = abs(current_price - ema20_current) / ema20_current * 100
    distance_to_ema50 = abs(current_price - ema50_current) / ema50_current * 100
    
    # 2. MACD - поиск дивергенции и разворота
    macd_df = calculate_macd(df.copy(), fast_period=12, slow_period=26, signal_period=9, symbol=f"{symbol} [12H]")
    macd_hist = macd_df['macd_hist']
    
    current_hist = macd_hist.iloc[-1]
    prev_hist = macd_hist.iloc[-2]
    prev_hist_2 = macd_hist.iloc[-3] if len(macd_hist) > 2 else None
    hist_diff = current_hist - prev_hist
    
    macd_action = macd_df.attrs.get('action') if hasattr(macd_df, 'attrs') else None
    
    # 3. RSI (14) - зоны перепроданности/перекупленности
    rsi_log, rsi_series = calculate_rsi(df, period=14)
    current_rsi = rsi_series.iloc[-1] if not rsi_series.empty else None
    prev_rsi = rsi_series.iloc[-2] if len(rsi_series) > 1 else None
    prev_rsi_2 = rsi_series.iloc[-3] if len(rsi_series) > 2 else None
    
    # 4. Stochastic (14,3,3) - пересечения
    stoch_log, stoch_df = calculate_stochastic(df.copy(), k_period=14, d_period=3)
    stoch_k = stoch_df['stoch_k'].iloc[-1] if not stoch_df.empty else None
    stoch_d = stoch_df['stoch_d'].iloc[-1] if not stoch_df.empty else None
    prev_stoch_k = stoch_df['stoch_k'].iloc[-2] if len(stoch_df) > 1 else None
    prev_stoch_d = stoch_df['stoch_d'].iloc[-2] if len(stoch_df) > 1 else None
    
    # 5. Bollinger Bands
    bb_df = calculate_bollinger_bands(df.copy(), period=20, num_std=2, ma_type="EMA", symbol=f"{symbol} [12H]")
    bb_upper = bb_df['bb_upper'].iloc[-1]
    bb_lower = bb_df['bb_lower'].iloc[-1]
    bb_middle = bb_df['bb_middle'].iloc[-1]
    
    # 6. Volume анализ - сравнение коррекционных свечей vs разворотной
    volume_res = analyze_volume(df.copy(), volume_ma_period=20, symbol=f"{symbol} [12H]")
    volume_ratio = volume_res.get('volume_ratio', 1.0)
    
    # Анализ объема на коррекционных свечах vs текущей (разворотной)
    current_volume = df['volume'].iloc[-1]
    prev_volume_1 = df['volume'].iloc[-2]
    prev_volume_2 = df['volume'].iloc[-3]
    avg_volume = volume_res.get('avg_volume', current_volume)
    
    # Сравниваем объем разворотной свечи с объемом коррекционных свечей
    reversal_vs_prev1 = (current_volume / prev_volume_1) if prev_volume_1 > 0 else 1.0
    reversal_vs_prev2 = (current_volume / prev_volume_2) if prev_volume_2 > 0 else 1.0
    reversal_vs_avg = (current_volume / avg_volume) if avg_volume > 0 else 1.0
    
    # Средний объем коррекционных свечей
    correction_avg_volume = (prev_volume_1 + prev_volume_2) / 2
    reversal_vs_correction = (current_volume / correction_avg_volume) if correction_avg_volume > 0 else 1.0
    
    # 6.5. ATR - фильтр волатильности (проверка адекватности условий для торговли)
    atr_log, atr_res = calculate_atr(df, period=14)
    
    if atr_res is not None and not atr_res.empty:
        current_atr = atr_res['ATR'].iloc[-1]
        current_atr_pct = atr_res['ATR_PCT'].iloc[-1]
        volatility_state = atr_res['volatility'].iloc[-1]
    else:
        current_atr = None
        current_atr_pct = None
        volatility_state = "NORMAL"
    
    # Проверяем волатильность:
    # - Слишком низкая (<1%): боковик, сложно торговать
    # - Нормальная (1-5%): хорошие условия
    # - Высокая (5-10%): повышенный риск, но приемлемо
    # - Экстремальная (>10%): очень опасно
    volatility_acceptable = True
    volatility_warning = None
    
    if current_atr_pct is not None:
        if current_atr_pct < 1.0:
            volatility_acceptable = False
            volatility_warning = f"⚠️ НИЗКАЯ волатильность ({current_atr_pct:.2f}%) - боковое движение, сложно торговать"
        elif current_atr_pct > 10.0:
            volatility_acceptable = False
            volatility_warning = f"⚠️ ЭКСТРЕМАЛЬНАЯ волатильность ({current_atr_pct:.2f}%) - очень высокий риск!"
        elif current_atr_pct > 5.0:
            volatility_warning = f"⚠️ ВЫСОКАЯ волатильность ({current_atr_pct:.2f}%) - повышенный риск"
    
    # 7. Анализ текущей свечи
    current_open = df['open'].iloc[-1]
    current_close = df['close'].iloc[-1]
    current_high = df['high'].iloc[-1]
    current_low = df['low'].iloc[-1]
    is_bullish_candle = current_close > current_open
    candle_size = abs(current_close - current_open) / current_open * 100
    
    # Анализ качества закрытия текущей свечи (сила разворота)
    # Для бычьей свечи: близость закрытия к максимуму (close ближе к high = сильнее)
    # Для медвежьей свечи: близость закрытия к минимуму (close ближе к low = сильнее)
    candle_range = current_high - current_low
    if candle_range > 0:
        if is_bullish_candle:
            # Бычья свеча: насколько close близко к high
            close_quality = (current_close - current_low) / candle_range * 100
        else:
            # Медвежья свеча: насколько close близко к low
            close_quality = (current_high - current_close) / candle_range * 100
    else:
        close_quality = 50.0  # Доджи или плоская свеча
    
    # Оценка качества закрытия:
    # 80%+ = отличное (почти без тени)
    # 60-80% = хорошее (небольшая тень)
    # 40-60% = среднее (значительная тень)
    # <40% = плохое (длинная тень, слабое закрытие)
    
    # Анализ предыдущих свечей для подтверждения разворота
    prev_open_1 = df['open'].iloc[-2]
    prev_close_1 = df['close'].iloc[-2]
    prev_candle_bullish = prev_close_1 > prev_open_1
    
    prev_open_2 = df['open'].iloc[-3]
    prev_close_2 = df['close'].iloc[-3]
    
    # === ПОДСЧЕТ СИГНАЛОВ ===
    signals = []
    signal_strength = 0
    
    # Добавляем бонус за подтверждение тренда (до 2 баллов)
    if correction_type == "SHARP":
        # Резкая коррекция - даем бонус за силу движения
        signals.append(f"✅✅ Подтверждение: РЕЗКАЯ коррекция {expected_12h_direction} (мощная свеча >3%)")
        signal_strength += 2
    elif trend_strength >= 2:
        signals.append(f"✅✅ Подтверждение: {trend_strength} свечи показывают четкое движение {expected_12h_direction}")
        signal_strength += 2
    elif trend_strength == 1:
        signals.append(f"✅ Подтверждение: движение {expected_12h_direction} подтверждено")
        signal_strength += 1
    
    # Бонус за КАЧЕСТВО закрытия разворотной свечи
    if close_quality >= 80:
        signals.append(f"✅✅ КАЧЕСТВО СВЕЧИ: Отличное закрытие ({close_quality:.1f}% - почти без тени)!")
        signal_strength += 2
    elif close_quality >= 60:
        signals.append(f"✅ КАЧЕСТВО СВЕЧИ: Хорошее закрытие ({close_quality:.1f}%)")
        signal_strength += 1
    elif close_quality < 40:
        signals.append(f"⚠️ КАЧЕСТВО СВЕЧИ: Слабое закрытие ({close_quality:.1f}% - длинная тень)")
        # Не добавляем баллы, возможно даже вычитаем
        signal_strength -= 1
    
    # Проверка волатильности
    if volatility_warning:
        signals.append(volatility_warning)
        # Если волатильность неприемлема - блокируем вход
        if not volatility_acceptable:
            action = "STOP"
            action_emoji = "🔴"
            action_text = f"НЕ ВХОДИТЬ - {volatility_warning}"
    
    if trend_1d == "BULLISH":
        # БЫЧИЙ СЦЕНАРИЙ 1D - ищем завершение коррекции вниз
        # Требуем: 1) Была коррекция вниз (подтверждено выше)
        #          2) Текущая свеча показывает разворот вверх
        
        # 1. MACD: гистограмма растет после падения или бычья дивергенция
        # Проверяем, что гистограмма росла последние 2 свечи (подтверждение)
        if hist_diff > 0 and current_hist < 0:
            # Проверяем подтверждение от предыдущей свечи
            if prev_hist_2 is not None and prev_hist > prev_hist_2:
                signals.append("✅✅ MACD: Гистограмма СТАБИЛЬНО растет 2+ свечи!")
                signal_strength += 2
            else:
                signals.append("✅ MACD: Гистограмма начинает расти")
                signal_strength += 1
        if macd_action == "BUY":
            signals.append("✅ MACD: Сигнал на покупку")
            signal_strength += 1
            
        # 2. RSI: выход из зоны перепроданности
        # Требуем подтверждение: RSI был низким 2+ свечи, затем начал расти
        if current_rsi is not None:
            if current_rsi < 30:
                # Проверяем, сколько свечей RSI был низким
                rsi_low_candles = 1
                if prev_rsi and prev_rsi < 30:
                    rsi_low_candles += 1
                if prev_rsi_2 and prev_rsi_2 < 30:
                    rsi_low_candles += 1
                
                if rsi_low_candles >= 2:
                    signals.append(f"✅✅ RSI: В зоне перепроданности {rsi_low_candles} свечи!")
                    signal_strength += 2
                else:
                    signals.append("✅ RSI: В зоне перепроданности (<30)")
                    signal_strength += 1
            elif prev_rsi and prev_rsi < 30 and current_rsi > 30:
                # Выход из зоны - проверяем, что RSI действительно рос
                if prev_rsi_2 and prev_rsi_2 < prev_rsi:
                    signals.append("✅✅✅ RSI: УВЕРЕННЫЙ ВЫХОД из зоны перепроданности!")
                    signal_strength += 3
                else:
                    signals.append("✅✅ RSI: ВЫХОД из зоны перепроданности!")
                    signal_strength += 2
                
        # 3. Stochastic: пересечение снизу вверх в зоне перепроданности
        if stoch_k and stoch_d and prev_stoch_k and prev_stoch_d:
            if prev_stoch_k < prev_stoch_d and stoch_k > stoch_d:
                if stoch_k < 20:
                    signals.append("✅✅ Stochastic: ЗОЛОТОЙ КРЕСТ в зоне перепроданности!")
                    signal_strength += 2
                else:
                    signals.append("✅ Stochastic: Бычье пересечение")
                    signal_strength += 1
                    
        # 4. EMA: отскок от EMA20 или EMA50
        # Требуем: цена была НИЖЕ EMA, теперь отскакивает вверх
        if distance_to_ema20 < 1.0 and is_bullish_candle:
            # Проверяем, что предыдущая свеча была ближе/ниже EMA
            if prev_close_1 < current_price:
                signals.append("✅✅ EMA: ПОДТВЕРЖДЕННЫЙ отскок от EMA20!")
                signal_strength += 2
            else:
                signals.append("✅ EMA: Отскок от EMA20")
                signal_strength += 1
        elif distance_to_ema50 < 1.5 and is_bullish_candle:
            if prev_close_1 < current_price:
                signals.append("✅✅✅ EMA: ПОДТВЕРЖДЕННЫЙ отскок от EMA50!")
                signal_strength += 3
            else:
                signals.append("✅✅ EMA: Отскок от EMA50!")
                signal_strength += 2
            
        # 5. Bollinger Bands: отскок от нижней полосы
        # Требуем: была внизу несколько свечей, сейчас отскок
        if current_price <= bb_lower and is_bullish_candle:
            # Проверяем, что предыдущие свечи были у нижней полосы
            if prev_close_1 <= bb_lower or prev_close_2 <= bb_lower:
                signals.append("✅✅✅ BB: СИЛЬНЫЙ отскок от нижней полосы с подтверждением!")
                signal_strength += 3
            else:
                signals.append("✅✅ BB: Отскок от нижней полосы!")
                signal_strength += 2
        elif current_price <= bb_middle and is_bullish_candle:
            if prev_close_1 < current_price:
                signals.append("✅✅ BB: ПОДТВЕРЖДЕННЫЙ отскок от средней линии!")
                signal_strength += 2
            else:
                signals.append("✅ BB: Отскок от средней линии")
                signal_strength += 1
            
        # 6. Volume: высокий объем на бычьей свече + сравнение с коррекционными свечами
        # Требуем: СИЛЬНУЮ бычью свечу с высоким объемом (подтверждение разворота)
        if volume_ratio > 1.5 and is_bullish_candle and candle_size > 1.5:
            # Проверяем ВЗРЫВНОЙ рост объема на развороте vs коррекционные свечи
            if reversal_vs_correction > 2.0:
                # Объем разворотной свечи более чем в 2 раза выше среднего объема коррекции
                signals.append(f"✅✅✅✅ Volume: ВЗРЫВНОЙ объем на развороте! ({reversal_vs_correction:.1f}x выше коррекции)")
                signal_strength += 4
            elif reversal_vs_correction > 1.5:
                signals.append(f"✅✅✅ Volume: Очень высокий объем на развороте ({reversal_vs_correction:.1f}x выше коррекции)")
                signal_strength += 3
            elif not prev_candle_bullish:
                # Обычный разворот с хорошим объемом
                signals.append("✅✅ Volume: Высокий объем на РАЗВОРОТЕ (медвежья→бычья)!")
                signal_strength += 2
            else:
                signals.append("✅ Volume: Высокий объем на бычьей свече")
                signal_strength += 1
        elif volume_ratio > 1.2 and is_bullish_candle:
            # Умеренно повышенный объем
            if reversal_vs_correction > 1.3:
                signals.append(f"✅✅ Volume: Повышенный объем на развороте ({reversal_vs_correction:.1f}x выше коррекции)")
                signal_strength += 2
            else:
                signals.append("✅ Volume: Немного повышенный объем")
                signal_strength += 1
        elif volume_ratio < 0.8:
            # Низкий объем - плохой знак для разворота
            signals.append("⚠️ Volume: НИЗКИЙ объем на развороте - слабое подтверждение")
            signal_strength -= 1
            
    else:  # trend_1d == "BEARISH"
        # МЕДВЕЖИЙ СЦЕНАРИЙ 1D - ищем завершение отскока вверх
        # Требуем: 1) Был отскок вверх (подтверждено выше)
        #          2) Текущая свеча показывает разворот вниз
        
        # 1. MACD: гистограмма падает после роста или медвежья дивергенция
        # Проверяем, что гистограмма падала последние 2 свечи (подтверждение)
        if hist_diff < 0 and current_hist > 0:
            # Проверяем подтверждение от предыдущей свечи
            if prev_hist_2 is not None and prev_hist < prev_hist_2:
                signals.append("✅✅ MACD: Гистограмма СТАБИЛЬНО падает 2+ свечи!")
                signal_strength += 2
            else:
                signals.append("✅ MACD: Гистограмма начинает падать")
                signal_strength += 1
        if macd_action == "SELL":
            signals.append("✅ MACD: Сигнал на продажу")
            signal_strength += 1
            
        # 2. RSI: выход из зоны перекупленности
        # Требуем подтверждение: RSI был высоким 2+ свечи, затем начал падать
        if current_rsi is not None:
            if current_rsi > 70:
                # Проверяем, сколько свечей RSI был высоким
                rsi_high_candles = 1
                if prev_rsi and prev_rsi > 70:
                    rsi_high_candles += 1
                if prev_rsi_2 and prev_rsi_2 > 70:
                    rsi_high_candles += 1
                
                if rsi_high_candles >= 2:
                    signals.append(f"✅✅ RSI: В зоне перекупленности {rsi_high_candles} свечи!")
                    signal_strength += 2
                else:
                    signals.append("✅ RSI: В зоне перекупленности (>70)")
                    signal_strength += 1
            elif prev_rsi and prev_rsi > 70 and current_rsi < 70:
                # Выход из зоны - проверяем, что RSI действительно падал
                if prev_rsi_2 and prev_rsi_2 > prev_rsi:
                    signals.append("✅✅✅ RSI: УВЕРЕННЫЙ ВЫХОД из зоны перекупленности!")
                    signal_strength += 3
                else:
                    signals.append("✅✅ RSI: ВЫХОД из зоны перекупленности!")
                    signal_strength += 2
                
        # 3. Stochastic: пересечение сверху вниз в зоне перекупленности
        if stoch_k and stoch_d and prev_stoch_k and prev_stoch_d:
            if prev_stoch_k > prev_stoch_d and stoch_k < stoch_d:
                if stoch_k > 80:
                    signals.append("✅✅ Stochastic: МЕРТВЫЙ КРЕСТ в зоне перекупленности!")
                    signal_strength += 2
                else:
                    signals.append("✅ Stochastic: Медвежье пересечение")
                    signal_strength += 1
                    
        # 4. EMA: отскок вниз от EMA20 или EMA50
        # Требуем: цена была ВЫШЕ EMA, теперь отскакивает вниз
        if distance_to_ema20 < 1.0 and not is_bullish_candle:
            # Проверяем, что предыдущая свеча была выше/дальше от EMA
            if prev_close_1 > current_price:
                signals.append("✅✅ EMA: ПОДТВЕРЖДЕННЫЙ отскок вниз от EMA20!")
                signal_strength += 2
            else:
                signals.append("✅ EMA: Отскок вниз от EMA20")
                signal_strength += 1
        elif distance_to_ema50 < 1.5 and not is_bullish_candle:
            if prev_close_1 > current_price:
                signals.append("✅✅✅ EMA: ПОДТВЕРЖДЕННЫЙ отскок вниз от EMA50!")
                signal_strength += 3
            else:
                signals.append("✅✅ EMA: Отскок вниз от EMA50!")
                signal_strength += 2
            
        # 5. Bollinger Bands: отскок вниз от верхней полосы
        # Требуем: была вверху несколько свечей, сейчас отскок вниз
        if current_price >= bb_upper and not is_bullish_candle:
            # Проверяем, что предыдущие свечи были у верхней полосы
            if prev_close_1 >= bb_upper or prev_close_2 >= bb_upper:
                signals.append("✅✅✅ BB: СИЛЬНЫЙ отскок вниз от верхней полосы с подтверждением!")
                signal_strength += 3
            else:
                signals.append("✅✅ BB: Отскок вниз от верхней полосы!")
                signal_strength += 2
        elif current_price >= bb_middle and not is_bullish_candle:
            if prev_close_1 > current_price:
                signals.append("✅✅ BB: ПОДТВЕРЖДЕННЫЙ отскок вниз от средней линии!")
                signal_strength += 2
            else:
                signals.append("✅ BB: Отскок вниз от средней линии")
                signal_strength += 1
            
        # 6. Volume: высокий объем на медвежьей свече + сравнение с коррекционными свечами
        # Требуем: СИЛЬНУЮ медвежью свечу с высоким объемом (подтверждение разворота)
        if volume_ratio > 1.5 and not is_bullish_candle and candle_size > 1.5:
            # Проверяем ВЗРЫВНОЙ рост объема на развороте vs отскоковые свечи
            if reversal_vs_correction > 2.0:
                # Объем разворотной свечи более чем в 2 раза выше среднего объема отскока
                signals.append(f"✅✅✅✅ Volume: ВЗРЫВНОЙ объем на развороте! ({reversal_vs_correction:.1f}x выше отскока)")
                signal_strength += 4
            elif reversal_vs_correction > 1.5:
                signals.append(f"✅✅✅ Volume: Очень высокий объем на развороте ({reversal_vs_correction:.1f}x выше отскока)")
                signal_strength += 3
            elif prev_candle_bullish:
                # Обычный разворот с хорошим объемом
                signals.append("✅✅ Volume: Высокий объем на РАЗВОРОТЕ (бычья→медвежья)!")
                signal_strength += 2
            else:
                signals.append("✅ Volume: Высокий объем на медвежьей свече")
                signal_strength += 1
        elif volume_ratio > 1.2 and not is_bullish_candle:
            # Умеренно повышенный объем
            if reversal_vs_correction > 1.3:
                signals.append(f"✅✅ Volume: Повышенный объем на развороте ({reversal_vs_correction:.1f}x выше отскока)")
                signal_strength += 2
            else:
                signals.append("✅ Volume: Немного повышенный объем")
                signal_strength += 1
        elif volume_ratio < 0.8:
            # Низкий объем - плохой знак для разворота
            signals.append("⚠️ Volume: НИЗКИЙ объем на развороте - слабое подтверждение")
            signal_strength -= 1
    
    # === ОПРЕДЕЛЕНИЕ ДЕЙСТВИЯ (СВЕТОФОР) ===
    # Новая шкала: с учетом подтверждений можно набрать до 20+ баллов
    # STOP: 0-4 балла (очень слабые сигналы или нет подтверждения)
    # ATTENTION: 5-8 баллов (есть некоторые сигналы, но мало подтверждений)
    # GO: 9+ баллов (множественные подтвержденные сигналы)
    
    if signal_strength == 0:
        action = "STOP"
        action_emoji = "🔴"
        action_text = "НЕ ВХОДИТЬ - Коррекция/отскок не завершен"
    elif signal_strength <= 4:
        action = "STOP"
        action_emoji = "🔴"
        action_text = "НЕ ВХОДИТЬ - Слишком мало подтвержденных сигналов"
    elif signal_strength <= 8:
        action = "ATTENTION"
        action_emoji = "🟡"
        action_text = "ВНИМАНИЕ - Готовимся к входу, смотрим 4H"
    else:
        action = "GO"
        action_emoji = "🟢"
        action_text = "ВПЕРЕД - Множественные подтвержденные сигналы, переходим на 4H!"
    
    # Формируем резюме
    rsi_text = f"{current_rsi:.2f}" if current_rsi is not None else "n/a"
    prev_rsi_text = f"{prev_rsi:.2f}" if prev_rsi is not None else "n/a"
    stoch_k_text = f"{stoch_k:.2f}" if stoch_k is not None else "n/a"
    stoch_d_text = f"{stoch_d:.2f}" if stoch_d is not None else "n/a"
    volume_ratio_text = f"{volume_ratio:.2f}" if volume_ratio is not None else "n/a"
    candle_type_text = "🟢 Бычья" if is_bullish_candle else "🔴 Медвежья"
    
    # Текст сравнения объемов
    volume_comparison = (
        f"Текущая свеча: {current_volume:.0f}\n"
        f"Коррекционная -1: {prev_volume_1:.0f} (разворот/коррекция = {reversal_vs_prev1:.2f}x)\n"
        f"Коррекционная -2: {prev_volume_2:.0f} (разворот/коррекция = {reversal_vs_prev2:.2f}x)\n"
        f"Средний коррекции: {correction_avg_volume:.0f} (разворот/коррекция = {reversal_vs_correction:.2f}x)\n"
        f"Средний 20MA: {avg_volume:.0f} (разворот/средний = {reversal_vs_avg:.2f}x)"
    )
    
    # Определяем качество закрытия текстом
    if close_quality >= 80:
        quality_text = "⭐ Отличное"
    elif close_quality >= 60:
        quality_text = "✅ Хорошее"
    elif close_quality >= 40:
        quality_text = "⚠️ Среднее"
    else:
        quality_text = "❌ Слабое"
    
    summary = (
        f"=== 12H СТРАТЕГИЯ КОРРЕКЦИИ ===\n"
        f"Тренд 1D: {trend_1d}\n"
        f"Ожидаем на 12H: {expected_12h_direction}\n"
        f"✅ Подтверждение движения: {trend_strength} свечи ({correction_type})\n"
        f"Последние цены: {prev_price_2:.4f} → {prev_price_1:.4f} → {current_price:.4f}\n"
        f"\n📊 СИГНАЛЫ ({signal_strength} баллов):\n"
        f"{chr(10).join(signals) if signals else 'Нет сигналов'}\n"
        f"\n{action_emoji} ДЕЙСТВИЕ: {action_text}\n"
        f"\n📈 ДЕТАЛИ:\n"
        f"RSI: {rsi_text} (prev: {prev_rsi_text})\n"
        f"Stochastic %K: {stoch_k_text}, %D: {stoch_d_text}\n"
        f"MACD Action: {macd_action}\n"
        f"Volume Ratio: {volume_ratio_text}\n"
        f"\n📊 АНАЛИЗ ОБЪЕМА:\n"
        f"{volume_comparison}\n"
        f"\nЦена vs EMA20: {distance_to_ema20:.2f}%, vs EMA50: {distance_to_ema50:.2f}%\n"
        f"Текущая свеча: {candle_type_text} ({candle_size:.2f}%)\n"
        f"Качество закрытия: {quality_text} ({close_quality:.1f}%)\n"
        f"---\n"
    )
    
    log_to_file("12h_correction_strategy_log.txt", summary)
    
    return {
        "action": action,
        "signal_strength": signal_strength,
        "trend_confirmation": trend_confirmation,
        "trend_strength": trend_strength,
        "correction_type": correction_type,
        "close_quality": close_quality,
        "signals": signals,
        "rsi": current_rsi,
        "stoch_k": stoch_k,
        "stoch_d": stoch_d,
        "macd_action": macd_action,
        "volume_ratio": volume_ratio,
        "summary": summary
    }

def analyze_4h_entry_strategy(df_4h, trend_1d, twelve_h_signal, symbol="UNKNOWN"):
    """
    Тактический анализ 4H - подтверждает возможность поиска точки входа на 1H.
    НЕ рассчитывает точку входа! Только проверяет условия для перехода к 1H анализу.
    
    Args:
        df_4h: DataFrame с данными 4H
        trend_1d: Тренд с 1D ("BULLISH" или "BEARISH") 
        twelve_h_signal: Результат анализа 12H
        symbol: Название инструмента
    
    Returns:
        dict: Результаты анализа с решением GO/WAIT/STOP для перехода на 1H
    """
    from analyzes.multi_timeframe_ma_analysis import calculate_ema
    
    if len(df_4h) < 20:
        return None
    
    current_price = df_4h['close'].iloc[-1]
    prev_price_1 = df_4h['close'].iloc[-2]
    prev_price_2 = df_4h['close'].iloc[-3]
    
    # === БАЗОВЫЕ ИНДИКАТОРЫ 4H ===
    
    # 1. Быстрые EMA для точного входа
    ema9 = calculate_ema(df_4h, 9)
    ema21 = calculate_ema(df_4h, 21)
    ema50 = calculate_ema(df_4h, 50)
    
    ema9_current = ema9.iloc[-1]
    ema21_current = ema21.iloc[-1]
    ema50_current = ema50.iloc[-1]
    
    # 2. MACD на 4H для timing
    macd_df = calculate_macd(df_4h.copy(), fast_period=8, slow_period=21, signal_period=5, symbol=f"{symbol} [4H]")
    macd_hist = macd_df['macd_hist']
    current_hist = macd_hist.iloc[-1]
    prev_hist = macd_hist.iloc[-2]
    hist_diff = current_hist - prev_hist
    
    # 3. RSI для перекупленности/перепроданности на 4H
    rsi_log, rsi_series = calculate_rsi(df_4h, period=14)
    current_rsi = rsi_series.iloc[-1] if not rsi_series.empty else None
    
    # 4. Stochastic для точных пересечений
    stoch_log, stoch_df = calculate_stochastic(df_4h.copy(), k_period=7, d_period=3)
    stoch_k = stoch_df['stoch_k'].iloc[-1] if not stoch_df.empty else None
    stoch_d = stoch_df['stoch_d'].iloc[-1] if not stoch_df.empty else None
    prev_stoch_k = stoch_df['stoch_k'].iloc[-2] if len(stoch_df) > 1 else None
    prev_stoch_d = stoch_df['stoch_d'].iloc[-2] if len(stoch_df) > 1 else None
    
    # 5. Volume анализ
    volume_res = analyze_volume(df_4h.copy(), volume_ma_period=10, symbol=f"{symbol} [4H]")
    volume_ratio = volume_res.get('volume_ratio', 1.0)
    
    # 6. ATR для рисков и фильтра волатильности
    atr_log, atr_res = calculate_atr(df_4h, period=14)
    
    if atr_res is not None and not atr_res.empty:
        current_atr = atr_res['ATR'].iloc[-1]
        current_atr_pct = atr_res['ATR_PCT'].iloc[-1]
        volatility_state = atr_res['volatility'].iloc[-1]
    else:
        current_atr = 0
        current_atr_pct = 0
        volatility_state = "NORMAL"
    
    # Фильтр волатильности (блокирует анализ при неадекватных условиях)
    volatility_acceptable = True
    volatility_warning = None
    
    if current_atr_pct is not None and current_atr_pct > 0:
        if current_atr_pct < 0.8:
            volatility_acceptable = False
            volatility_warning = f"🔴 НИЗКАЯ волатильность ({current_atr_pct:.2f}%) - боковик, сложно торговать"
        elif current_atr_pct > 12.0:
            volatility_acceptable = False
            volatility_warning = f"🔴 ЭКСТРЕМАЛЬНАЯ волатильность ({current_atr_pct:.2f}%) - очень высокий риск!"
        elif current_atr_pct > 8.0:
            volatility_warning = f"⚠️ ВЫСОКАЯ волатильность ({current_atr_pct:.2f}%) - повышенный риск"
        elif current_atr_pct >= 0.8 and current_atr_pct <= 8.0:
            volatility_warning = f"✅ Нормальная волатильность ({current_atr_pct:.2f}%) - хорошие условия"
    
    # 7. Анализ свечи
    current_open = df_4h['open'].iloc[-1]
    current_close = df_4h['close'].iloc[-1]
    current_high = df_4h['high'].iloc[-1]
    current_low = df_4h['low'].iloc[-1]
    is_bullish_candle = current_close > current_open
    
    # Предыдущая свеча для паттернов
    prev_open = df_4h['open'].iloc[-2]
    prev_close = df_4h['close'].iloc[-2]
    prev_high = df_4h['high'].iloc[-2]
    prev_low = df_4h['low'].iloc[-2]
    is_prev_bullish = prev_close > prev_open
    
    # === АНАЛИЗ СВЕЧНЫХ ПАТТЕРНОВ 4H ===
    candlestick_pattern = None
    pattern_strength = 0
    
    # Размеры тела и теней текущей свечи
    candle_range = current_high - current_low
    body_size = abs(current_close - current_open)
    upper_shadow = current_high - max(current_open, current_close)
    lower_shadow = min(current_open, current_close) - current_low
    
    if candle_range > 0:
        body_ratio = body_size / candle_range
        lower_shadow_ratio = lower_shadow / candle_range
        upper_shadow_ratio = upper_shadow / candle_range
        candle_size_pct = abs(current_close - current_open) / current_open * 100
        
        # 1. МОЛОТ (Hammer) - бычий разворотный паттерн
        if (lower_shadow_ratio > 0.6 and  # Длинная нижняя тень (>60% диапазона)
            body_ratio < 0.3 and           # Маленькое тело (<30% диапазона)
            upper_shadow_ratio < 0.1 and   # Короткая верхняя тень (<10% диапазона)
            candle_size_pct > 0.5):        # Значимый размер свечи (>0.5%)
            
            if is_bullish_candle:
                candlestick_pattern = "МОЛОТ (бычий)"
                pattern_strength = 3
            else:
                candlestick_pattern = "ВИСЕЛЬНИК (медвежий молот)"
                pattern_strength = 2
        
        # 2. ПАДАЮЩАЯ ЗВЕЗДА (Shooting Star) - медвежий разворотный паттерн
        elif (upper_shadow_ratio > 0.6 and   # Длинная верхняя тень
              body_ratio < 0.3 and           # Маленькое тело
              lower_shadow_ratio < 0.1 and   # Короткая нижняя тень
              candle_size_pct > 0.5):
            
            if not is_bullish_candle:
                candlestick_pattern = "ПАДАЮЩАЯ ЗВЕЗДА (медвежий)"
                pattern_strength = 3
            else:
                candlestick_pattern = "ПЕРЕВЕРНУТЫЙ МОЛОТ (бычий)"
                pattern_strength = 2
        
        # 3. ПОГЛОЩЕНИЕ (Engulfing) - сильный разворотный паттерн
        prev_body_size = abs(prev_close - prev_open)
        
        # Бычье поглощение (для входа в лонг)
        if (is_bullish_candle and not is_prev_bullish and  # Смена направления
            current_close > prev_open and                   # Закрытие выше открытия предыдущей
            current_open < prev_close and                   # Открытие ниже закрытия предыдущей
            body_size > prev_body_size * 1.2):              # Тело больше предыдущего на 20%+
            
            if candlestick_pattern is None:
                candlestick_pattern = "БЫЧЬЕ ПОГЛОЩЕНИЕ"
                pattern_strength = 4  # Очень сильный паттерн
        
        # Медвежье поглощение (для входа в шорт)
        elif (not is_bullish_candle and is_prev_bullish and  # Смена направления
              current_close < prev_open and                   # Закрытие ниже открытия предыдущей
              current_open > prev_close and                   # Открытие выше закрытия предыдущей
              body_size > prev_body_size * 1.2):              # Тело больше предыдущего на 20%+
            
            if candlestick_pattern is None:
                candlestick_pattern = "МЕДВЕЖЬЕ ПОГЛОЩЕНИЕ"
                pattern_strength = 4
        
        # 4. ПИН-БАР (Pin Bar) - сильный разворотный сигнал
        # Признаки: длинная тень с одной стороны (>2/3 диапазона), маленькое тело
        elif body_ratio < 0.25:
            if lower_shadow_ratio > 0.66:
                candlestick_pattern = "ПИН-БАР БЫЧИЙ (длинная нижняя тень)"
                pattern_strength = 3
            elif upper_shadow_ratio > 0.66:
                candlestick_pattern = "ПИН-БАР МЕДВЕЖИЙ (длинная верхняя тень)"
                pattern_strength = 3
        
        # 5. ДОДЖИ (Doji) - неопределенность
        elif body_ratio < 0.05 and candle_size_pct < 0.3:
            candlestick_pattern = "ДОДЖИ (неопределенность)"
            pattern_strength = 1
    
    # === ОПРЕДЕЛЕНИЕ СИГНАЛОВ 4H ===
    signals_4h = []
    readiness_score = 0  # Оценка готовности для перехода на 1H
    
    # Добавляем информацию о волатильности в начало
    if volatility_warning:
        signals_4h.append(volatility_warning)
    
    if trend_1d == "BULLISH" and twelve_h_signal.get('action') in ['GO', 'ATTENTION']:
        # БЫЧИЙ СЦЕНАРИЙ - проверяем готовность для поиска входа в лонг на 1H
        
        # 0. СВЕЧНОЙ ПАТТЕРН - подтверждение разворота
        if candlestick_pattern:
            if "МОЛОТ" in candlestick_pattern or "БЫЧЬЕ ПОГЛОЩЕНИЕ" in candlestick_pattern or "ПИН-БАР БЫЧИЙ" in candlestick_pattern:
                signals_4h.append(f"🕯️✅✅ ПАТТЕРН: {candlestick_pattern} - бычий разворот подтвержден!")
                readiness_score += pattern_strength
            elif "ДОДЖИ" in candlestick_pattern:
                signals_4h.append(f"🕯️⚠️ ПАТТЕРН: {candlestick_pattern} - неопределенность")
                readiness_score += 1
            elif "ПАДАЮЩАЯ ЗВЕЗДА" in candlestick_pattern or "МЕДВЕЖЬЕ ПОГЛОЩЕНИЕ" in candlestick_pattern:
                signals_4h.append(f"🕯️❌ ПАТТЕРН: {candlestick_pattern} - ПРОТИВОРЕЧИТ тренду!")
                readiness_score -= 3
        
        # 1. Проверка тренда 4H - цена должна быть выше быстрых EMA
        price_above_ema9 = current_price > ema9_current
        price_above_ema21 = current_price > ema21_current
        ema9_above_ema21 = ema9_current > ema21_current
        
        if price_above_ema9 and price_above_ema21 and ema9_above_ema21:
            signals_4h.append("✅✅ 4H Тренд: Сильная бычья структура (цена > EMA9 > EMA21)")
            readiness_score += 3
        elif price_above_ema21:
            signals_4h.append("✅ 4H Тренд: Цена выше EMA21 (восходящий)")
            readiness_score += 2
        else:
            signals_4h.append("⚠️ 4H Тренд: Цена ниже EMA21 - слабая структура")
            readiness_score -= 2
        
        # 2. MACD - импульс должен поддерживать направление
        if hist_diff > 0 and current_hist > prev_hist:
            signals_4h.append("✅ MACD 4H: Растущий импульс")
            readiness_score += 2
        elif hist_diff > 0:
            signals_4h.append("✅ MACD 4H: Положительная динамика")
            readiness_score += 1
        elif current_hist < 0 and hist_diff < 0:
            signals_4h.append("⚠️ MACD 4H: Негативный импульс")
            readiness_score -= 1
        
        # 3. RSI - не должен быть перекуплен
        if current_rsi and current_rsi < 60:
            signals_4h.append(f"✅ RSI 4H: {current_rsi:.1f} (есть запас для роста)")
            readiness_score += 2
        elif current_rsi and current_rsi < 70:
            signals_4h.append(f"✅ RSI 4H: {current_rsi:.1f} (допустимо)")
            readiness_score += 1
        elif current_rsi and current_rsi >= 70:
            signals_4h.append(f"⚠️ RSI 4H: {current_rsi:.1f} (перекупленность - риск коррекции)")
            readiness_score -= 2
        
        # 4. Stochastic - подтверждение направления
        if stoch_k and stoch_d and prev_stoch_k and prev_stoch_d:
            if stoch_k > stoch_d and prev_stoch_k < prev_stoch_d and stoch_k < 80:
                signals_4h.append("✅✅ Stochastic 4H: Свежее бычье пересечение")
                readiness_score += 3
            elif stoch_k > stoch_d and stoch_k < 80:
                signals_4h.append("✅ Stochastic 4H: Бычье направление")
                readiness_score += 1
            elif stoch_k > 80:
                signals_4h.append("⚠️ Stochastic 4H: Перекупленность")
                readiness_score -= 1
        
        # 5. Volume - подтверждение интереса
        if volume_ratio > 1.3:
            signals_4h.append(f"✅ Volume 4H: Повышенный интерес ({volume_ratio:.2f}x)")
            readiness_score += 2
        elif volume_ratio > 1.1:
            signals_4h.append(f"✅ Volume 4H: Нормальный ({volume_ratio:.2f}x)")
            readiness_score += 1
        elif volume_ratio < 0.8:
            signals_4h.append(f"⚠️ Volume 4H: Низкий интерес ({volume_ratio:.2f}x)")
            readiness_score -= 1
        
        # 6. Расстояние до EMA - не должно быть перегрева
        distance_to_ema9 = abs(current_price - ema9_current) / ema9_current * 100
        if distance_to_ema9 < 2.0:
            signals_4h.append(f"✅ Цена близко к EMA9 ({distance_to_ema9:.2f}%) - хорошая зона для входа")
            readiness_score += 2
        elif distance_to_ema9 < 5.0:
            signals_4h.append(f"✅ Цена умеренно выше EMA9 ({distance_to_ema9:.2f}%)")
            readiness_score += 1
        else:
            signals_4h.append(f"⚠️ Цена далеко от EMA9 ({distance_to_ema9:.2f}%) - возможна коррекция")
            readiness_score -= 1
    
    elif trend_1d == "BEARISH" and twelve_h_signal.get('action') in ['GO', 'ATTENTION']:
        # МЕДВЕЖИЙ СЦЕНАРИЙ - проверяем готовность для поиска входа в шорт на 1H
        
        # 0. СВЕЧНОЙ ПАТТЕРН - подтверждение разворота
        if candlestick_pattern:
            if "ПАДАЮЩАЯ ЗВЕЗДА" in candlestick_pattern or "МЕДВЕЖЬЕ ПОГЛОЩЕНИЕ" in candlestick_pattern or "ПИН-БАР МЕДВЕЖИЙ" in candlestick_pattern:
                signals_4h.append(f"🕯️✅✅ ПАТТЕРН: {candlestick_pattern} - медвежий разворот подтвержден!")
                readiness_score += pattern_strength
            elif "ДОДЖИ" in candlestick_pattern:
                signals_4h.append(f"🕯️⚠️ ПАТТЕРН: {candlestick_pattern} - неопределенность")
                readiness_score += 1
            elif "МОЛОТ" in candlestick_pattern or "БЫЧЬЕ ПОГЛОЩЕНИЕ" in candlestick_pattern:
                signals_4h.append(f"🕯️❌ ПАТТЕРН: {candlestick_pattern} - ПРОТИВОРЕЧИТ тренду!")
                readiness_score -= 3
        
        # 1. Проверка тренда 4H - цена должна быть ниже быстрых EMA
        price_below_ema9 = current_price < ema9_current
        price_below_ema21 = current_price < ema21_current
        ema9_below_ema21 = ema9_current < ema21_current
        
        if price_below_ema9 and price_below_ema21 and ema9_below_ema21:
            signals_4h.append("✅✅ 4H Тренд: Сильная медвежья структура (цена < EMA9 < EMA21)")
            readiness_score += 3
        elif price_below_ema21:
            signals_4h.append("✅ 4H Тренд: Цена ниже EMA21 (нисходящий)")
            readiness_score += 2
        else:
            signals_4h.append("⚠️ 4H Тренд: Цена выше EMA21 - слабая структура")
            readiness_score -= 2
        
        # 2. MACD - импульс должен поддерживать направление
        if hist_diff < 0 and current_hist < prev_hist:
            signals_4h.append("✅ MACD 4H: Падающий импульс")
            readiness_score += 2
        elif hist_diff < 0:
            signals_4h.append("✅ MACD 4H: Отрицательная динамика")
            readiness_score += 1
        elif current_hist > 0 and hist_diff > 0:
            signals_4h.append("⚠️ MACD 4H: Позитивный импульс (противоречие)")
            readiness_score -= 1
        
        # 3. RSI - не должен быть перепродан
        if current_rsi and current_rsi > 40:
            signals_4h.append(f"✅ RSI 4H: {current_rsi:.1f} (есть запас для падения)")
            readiness_score += 2
        elif current_rsi and current_rsi > 30:
            signals_4h.append(f"✅ RSI 4H: {current_rsi:.1f} (допустимо)")
            readiness_score += 1
        elif current_rsi and current_rsi <= 30:
            signals_4h.append(f"⚠️ RSI 4H: {current_rsi:.1f} (перепроданность - риск отскока)")
            readiness_score -= 2
        
        # 4. Stochastic - подтверждение направления
        if stoch_k and stoch_d and prev_stoch_k and prev_stoch_d:
            if stoch_k < stoch_d and prev_stoch_k > prev_stoch_d and stoch_k > 20:
                signals_4h.append("✅✅ Stochastic 4H: Свежее медвежье пересечение")
                readiness_score += 3
            elif stoch_k < stoch_d and stoch_k > 20:
                signals_4h.append("✅ Stochastic 4H: Медвежье направление")
                readiness_score += 1
            elif stoch_k < 20:
                signals_4h.append("⚠️ Stochastic 4H: Перепроданность")
                readiness_score -= 1
        
        # 5. Volume - подтверждение интереса
        if volume_ratio > 1.3:
            signals_4h.append(f"✅ Volume 4H: Повышенный интерес ({volume_ratio:.2f}x)")
            readiness_score += 2
        elif volume_ratio > 1.1:
            signals_4h.append(f"✅ Volume 4H: Нормальный ({volume_ratio:.2f}x)")
            readiness_score += 1
        elif volume_ratio < 0.8:
            signals_4h.append(f"⚠️ Volume 4H: Низкий интерес ({volume_ratio:.2f}x)")
            readiness_score -= 1
        
        # 6. Расстояние до EMA - не должно быть перегрева
        distance_to_ema9 = abs(current_price - ema9_current) / ema9_current * 100
        if distance_to_ema9 < 2.0:
            signals_4h.append(f"✅ Цена близко к EMA9 ({distance_to_ema9:.2f}%) - хорошая зона для входа")
            readiness_score += 2
        elif distance_to_ema9 < 5.0:
            signals_4h.append(f"✅ Цена умеренно ниже EMA9 ({distance_to_ema9:.2f}%)")
            readiness_score += 1
        else:
            signals_4h.append(f"⚠️ Цена далеко от EMA9 ({distance_to_ema9:.2f}%) - возможен отскок")
            readiness_score -= 1
    
    # === ФИНАЛЬНОЕ РЕШЕНИЕ 4H ===
    # Блокировка при неприемлемой волатильности
    if not volatility_acceptable:
        action_4h = "STOP"
        action_emoji = "🔴"
        action_text = f"СТОП - {volatility_warning}"
    # Определяем готовность для перехода к анализу 1H
    elif readiness_score >= 6:
        action_4h = "GO"
        action_emoji = "🟢"
        action_text = "ПЕРЕХОДИМ К 1H - Условия выполнены, ищем точку входа"
    elif readiness_score >= 3:
        action_4h = "ATTENTION"
        action_emoji = "🟡" 
        action_text = "ОСТОРОЖНО - Условия неполные, следим за 1H"
    else:
        action_4h = "STOP"
        action_emoji = "🔴"
        action_text = "СТОП - Условия не выполнены, не переходим к 1H"
    
    summary_4h = (
        f"=== 4H ТАКТИЧЕСКИЙ ФИЛЬТР ===\n"
        f"Сигнал 12H: {twelve_h_signal.get('action', 'UNKNOWN')} ({twelve_h_signal.get('signal_strength', 0)} баллов)\n"
        f"Тренд 1D: {trend_1d}\n"
        f"🕯️ СВЕЧНОЙ ПАТТЕРН: {candlestick_pattern if candlestick_pattern else 'Не обнаружен'}\n"
        f"Оценка готовности 4H: {readiness_score} баллов\n"
        f"\n📊 ПРОВЕРКА УСЛОВИЙ 4H:\n"
        f"{chr(10).join(signals_4h) if signals_4h else 'Нет сигналов'}\n"
        f"\n{action_emoji} РЕШЕНИЕ 4H: {action_text}\n"
        f"\n💡 СЛЕДУЮЩИЙ ШАГ:\n"
    )
    
    if action_4h == "GO":
        summary_4h += "✅ Переходим к анализу 1H для поиска точной точки входа\n"
    elif action_4h == "ATTENTION":
        summary_4h += "⚠️ Можно следить за 1H, но с осторожностью\n"
    else:
        summary_4h += "🔴 НЕ анализируем 1H - ждем улучшения условий на 4H\n"
    
    summary_4h += "---\n"
    
    log_to_file("4h_entry_strategy_log.txt", summary_4h)
    
    return {
        "action": action_4h,
        "readiness_score": readiness_score,
        "candlestick_pattern": candlestick_pattern,
        "pattern_strength": pattern_strength,
        # Ключевые уровни для анализа 1H
        "key_levels": {
            "ema9": ema9_current,
            "ema21": ema21_current,
            "ema50": ema50_current,
            "current_price": current_price
        },
        # Информация о волатильности для 1H
        "volatility_info": {
            "atr_pct": current_atr_pct,
            "state": volatility_state,
            "acceptable": volatility_acceptable
        },
        "signals": signals_4h,
        "summary": summary_4h
    }
    
def analyze_1h_execution(df_1h, four_h_signal, trend_1d, symbol="UNKNOWN"):
    """
    Анализ 1H для точного входа в сделку.
    Определяет конкретную точку входа, стоп-лосс и тейк-профит.
    
    Args:
        df_1h: DataFrame с данными 1H
        four_h_signal: Результат анализа 4H 
        trend_1d: Тренд с 1D ("BULLISH" или "BEARISH")
        symbol: Название инструмента
    
    Returns:
        dict: Результаты анализа с точкой входа и управлением рисками
    """
    from analyzes.multi_timeframe_ma_analysis import calculate_ema
    from bybit_client import bybit_client
    
    if len(df_1h) < 20:
        return None
    
    current_price = df_1h['close'].iloc[-1]
    prev_price_1 = df_1h['close'].iloc[-2]
    prev_price_2 = df_1h['close'].iloc[-3]
    
    # === БАЗОВЫЕ ИНДИКАТОРЫ 1H ===
    
    # 1. EMA для точных отскоков
    ema9 = calculate_ema(df_1h, 9)
    ema20 = calculate_ema(df_1h, 20)
    ema50 = calculate_ema(df_1h, 50)
    
    ema9_current = ema9.iloc[-1]
    ema20_current = ema20.iloc[-1]
    ema50_current = ema50.iloc[-1]
    
    # 2. MACD на 1H для timing входа
    macd_df = calculate_macd(df_1h.copy(), fast_period=12, slow_period=26, signal_period=9, symbol=f"{symbol} [1H]")
    macd_line = macd_df['macd']
    macd_signal = macd_df['macd_signal'] 
    macd_hist = macd_df['macd_hist']
    
    current_macd = macd_line.iloc[-1]
    current_signal = macd_signal.iloc[-1]
    current_hist = macd_hist.iloc[-1]
    prev_hist = macd_hist.iloc[-2]
    hist_diff = current_hist - prev_hist
    
    # 3. RSI для перекупленности/перепроданности на 1H
    rsi_log, rsi_series = calculate_rsi(df_1h, period=14)
    current_rsi = rsi_series.iloc[-1] if not rsi_series.empty else None
    
    # 4. Stochastic для точных пересечений на 1H
    stoch_log, stoch_df = calculate_stochastic(df_1h.copy(), k_period=14, d_period=3)
    stoch_k = stoch_df['stoch_k'].iloc[-1] if not stoch_df.empty else None
    stoch_d = stoch_df['stoch_d'].iloc[-1] if not stoch_df.empty else None
    prev_stoch_k = stoch_df['stoch_k'].iloc[-2] if len(stoch_df) > 1 else None
    prev_stoch_d = stoch_df['stoch_d'].iloc[-2] if len(stoch_df) > 1 else None
    
    # 5. Volume анализ на 1H
    volume_res = analyze_volume(df_1h.copy(), volume_ma_period=20, symbol=f"{symbol} [1H]")
    volume_ratio = volume_res.get('volume_ratio', 1.0)
    volume_trend = volume_res.get('volume_trend', 'NEUTRAL')
    
    # 6. ATR для расчета стоп-лосса
    atr_log, atr_res = calculate_atr(df_1h, period=14)
    
    if atr_res is not None and not atr_res.empty:
        current_atr = atr_res['ATR'].iloc[-1]
        current_atr_pct = atr_res['ATR_PCT'].iloc[-1]
    else:
        current_atr = 0
        current_atr_pct = 0
    
    # 7. Анализ свечи 1H
    current_open = df_1h['open'].iloc[-1]
    current_close = df_1h['close'].iloc[-1]
    current_high = df_1h['high'].iloc[-1]
    current_low = df_1h['low'].iloc[-1]
    is_bullish_candle = current_close > current_open
    
    # Предыдущие свечи для паттернов
    prev_open = df_1h['open'].iloc[-2]
    prev_close = df_1h['close'].iloc[-2]
    prev_high = df_1h['high'].iloc[-2]
    prev_low = df_1h['low'].iloc[-2]
    is_prev_bullish = prev_close > prev_open
    
    # === КЛЮЧЕВЫЕ УРОВНИ ПОДДЕРЖКИ/СОПРОТИВЛЕНИЯ ===
    support_level = df_1h['low'].tail(10).min()
    resistance_level = df_1h['high'].tail(10).max()
    
    # Расстояние до ключевых уровней
    distance_to_support = ((current_price - support_level) / current_price * 100) if support_level > 0 else 100
    distance_to_resistance = ((resistance_level - current_price) / current_price * 100) if resistance_level > 0 else 100
    
    # === АНАЛИЗ ORDERBOOK (СТАКАНА) ===
    orderbook_score = 0
    orderbook_signals = []
    
    try:
        # Получаем стакан цен
        bids, asks, bid_volume, ask_volume, whale_bids, whale_asks = bybit_client.get_orderbook(
            symbol=symbol, 
            levels=50,  # Берем 50 уровней для детального анализа
            whale_size=None
        )
        
        if bids and asks:
            # === КЛАСТЕРИЗАЦИЯ ОРДЕРОВ ПО УРОВНЯМ ===
            # Группируем ордера по ценовым кластерам (шаг 0.1% от текущей цены)
            cluster_step = current_price * 0.001  # 0.1% шаг
            
            bid_clusters = {}
            ask_clusters = {}
            
            # Группируем биды (заявки на покупку)
            for bid in bids:
                price = float(bid[0])
                volume = float(bid[1])
                cluster_level = round(price / cluster_step) * cluster_step
                bid_clusters[cluster_level] = bid_clusters.get(cluster_level, 0) + volume
            
            # Группируем аски (заявки на продажу)
            for ask in asks:
                price = float(ask[0])
                volume = float(ask[1])
                cluster_level = round(price / cluster_step) * cluster_step
                ask_clusters[cluster_level] = ask_clusters.get(cluster_level, 0) + volume
            
            # === ПОИСК КРУПНЫХ КЛАСТЕРОВ ===
            total_bid_volume = sum(bid_clusters.values())
            total_ask_volume = sum(ask_clusters.values())
            total_volume = total_bid_volume + total_ask_volume
            
            # Порог для "крупного" кластера - 5% от общего объема
            large_cluster_threshold = total_volume * 0.05
            
            # Крупные кластеры поддержки (биды)
            large_support_clusters = {
                level: vol for level, vol in bid_clusters.items() 
                if vol > large_cluster_threshold and level < current_price
            }
            
            # Крупные кластеры сопротивления (аски)
            large_resistance_clusters = {
                level: vol for level, vol in ask_clusters.items() 
                if vol > large_cluster_threshold and level > current_price
            }
            
            # === АНАЛИЗ БАЛАНСА ОБЪЕМОВ ===
            bid_ask_ratio = bid_volume / ask_volume if ask_volume > 0 else 1.0
            
            if bid_ask_ratio > 1.5:
                orderbook_signals.append(f"✅ Сильное давление покупателей (Bid/Ask: {bid_ask_ratio:.2f})")
                if trend_1d == "BULLISH":
                    orderbook_score += 2
                else:
                    orderbook_score += 1
            elif bid_ask_ratio > 1.2:
                orderbook_signals.append(f"✅ Умеренное давление покупателей (Bid/Ask: {bid_ask_ratio:.2f})")
                if trend_1d == "BULLISH":
                    orderbook_score += 1
            elif bid_ask_ratio < 0.67:
                orderbook_signals.append(f"✅ Сильное давление продавцов (Bid/Ask: {bid_ask_ratio:.2f})")
                if trend_1d == "BEARISH":
                    orderbook_score += 2
                else:
                    orderbook_score += 1
            elif bid_ask_ratio < 0.83:
                orderbook_signals.append(f"✅ Умеренное давление продавцов (Bid/Ask: {bid_ask_ratio:.2f})")
                if trend_1d == "BEARISH":
                    orderbook_score += 1
            else:
                orderbook_signals.append(f"⚖️ Баланс покупателей/продавцов (Bid/Ask: {bid_ask_ratio:.2f})")
            
            # === АНАЛИЗ КРУПНЫХ КЛАСТЕРОВ ПОДДЕРЖКИ ===
            if large_support_clusters:
                # Сортируем по близости к текущей цене
                sorted_supports = sorted(
                    large_support_clusters.items(), 
                    key=lambda x: abs(x[0] - current_price)
                )
                
                for level, volume in sorted_supports[:3]:  # Берем 3 ближайших
                    distance_pct = abs(level - current_price) / current_price * 100
                    volume_pct = (volume / total_volume) * 100
                    
                    if distance_pct < 0.5:  # Очень близко (<0.5%)
                        orderbook_signals.append(
                            f"✅✅ МОЩНАЯ поддержка: {level:.4f} "
                            f"({volume_pct:.1f}% объема, -{distance_pct:.2f}%)"
                        )
                        if trend_1d == "BULLISH":
                            orderbook_score += 3
                        else:
                            orderbook_score += 1
                    elif distance_pct < 1.0:  # Близко (<1%)
                        orderbook_signals.append(
                            f"✅ Крупная поддержка: {level:.4f} "
                            f"({volume_pct:.1f}% объема, -{distance_pct:.2f}%)"
                        )
                        if trend_1d == "BULLISH":
                            orderbook_score += 2
                        else:
                            orderbook_score += 1
            
            # === АНАЛИЗ КРУПНЫХ КЛАСТЕРОВ СОПРОТИВЛЕНИЯ ===
            if large_resistance_clusters:
                # Сортируем по близости к текущей цене
                sorted_resistances = sorted(
                    large_resistance_clusters.items(), 
                    key=lambda x: abs(x[0] - current_price)
                )
                
                for level, volume in sorted_resistances[:3]:  # Берем 3 ближайших
                    distance_pct = abs(level - current_price) / current_price * 100
                    volume_pct = (volume / total_volume) * 100
                    
                    if distance_pct < 0.5:  # Очень близко (<0.5%)
                        orderbook_signals.append(
                            f"⚠️⚠️ МОЩНОЕ сопротивление: {level:.4f} "
                            f"({volume_pct:.1f}% объема, +{distance_pct:.2f}%)"
                        )
                        if trend_1d == "BULLISH":
                            orderbook_score -= 2  # Плохо для лонга
                        else:
                            orderbook_score += 3  # Хорошо для шорта
                    elif distance_pct < 1.0:  # Близко (<1%)
                        orderbook_signals.append(
                            f"⚠️ Крупное сопротивление: {level:.4f} "
                            f"({volume_pct:.1f}% объема, +{distance_pct:.2f}%)"
                        )
                        if trend_1d == "BULLISH":
                            orderbook_score -= 1
                        else:
                            orderbook_score += 2
            
            # === ПРОВЕРКА "СТЕНЫ" (WALLS) ===
            # Стена - это экстремально крупный ордер (>10% общего объема)
            wall_threshold = total_volume * 0.10
            
            bid_walls = {level: vol for level, vol in bid_clusters.items() if vol > wall_threshold}
            ask_walls = {level: vol for level, vol in ask_clusters.items() if vol > wall_threshold}
            
            if bid_walls:
                closest_bid_wall = min(bid_walls.items(), key=lambda x: abs(x[0] - current_price))
                wall_distance = abs(closest_bid_wall[0] - current_price) / current_price * 100
                wall_volume_pct = (closest_bid_wall[1] / total_volume) * 100
                
                if wall_distance < 2.0:
                    orderbook_signals.append(
                        f"🧱 СТЕНА поддержки: {closest_bid_wall[0]:.4f} "
                        f"({wall_volume_pct:.1f}% объема!)"
                    )
                    if trend_1d == "BULLISH":
                        orderbook_score += 2
            
            if ask_walls:
                closest_ask_wall = min(ask_walls.items(), key=lambda x: abs(x[0] - current_price))
                wall_distance = abs(closest_ask_wall[0] - current_price) / current_price * 100
                wall_volume_pct = (closest_ask_wall[1] / total_volume) * 100
                
                if wall_distance < 2.0:
                    orderbook_signals.append(
                        f"🧱 СТЕНА сопротивления: {closest_ask_wall[0]:.4f} "
                        f"({wall_volume_pct:.1f}% объема!)"
                    )
                    if trend_1d == "BEARISH":
                        orderbook_score += 2
                    else:
                        orderbook_score -= 1
    
    except Exception as e:
        orderbook_signals.append(f"⚠️ Ошибка анализа orderbook: {e}")
        orderbook_score = 0
    
    # === АНАЛИЗ СВЕЧНЫХ ПАТТЕРНОВ 1H ===
    candlestick_pattern = None
    pattern_strength = 0
    
    candle_range = current_high - current_low
    body_size = abs(current_close - current_open)
    
    if candle_range > 0:
        body_ratio = body_size / candle_range
        upper_shadow = current_high - max(current_open, current_close)
        lower_shadow = min(current_open, current_close) - current_low
        lower_shadow_ratio = lower_shadow / candle_range
        upper_shadow_ratio = upper_shadow / candle_range
        
        # Бычье поглощение
        if (is_bullish_candle and not is_prev_bullish and
            current_close > prev_open and current_open < prev_close):
            candlestick_pattern = "БЫЧЬЕ ПОГЛОЩЕНИЕ"
            pattern_strength = 3
        
        # Медвежье поглощение  
        elif (not is_bullish_candle and is_prev_bullish and
              current_close < prev_open and current_open > prev_close):
            candlestick_pattern = "МЕДВЕЖЬЕ ПОГЛОЩЕНИЕ"
            pattern_strength = 3
        
        # Молот / Повешенный
        elif (lower_shadow_ratio > 0.6 and body_ratio < 0.3 and upper_shadow_ratio < 0.2):
            if is_bullish_candle:
                candlestick_pattern = "МОЛОТ"
                pattern_strength = 2
            else:
                candlestick_pattern = "ПОВЕШЕННЫЙ"
                pattern_strength = 2
        
        # Падающая звезда / Перевернутый молот
        elif (upper_shadow_ratio > 0.6 and body_ratio < 0.3 and lower_shadow_ratio < 0.2):
            if not is_bullish_candle:
                candlestick_pattern = "ПАДАЮЩАЯ ЗВЕЗДА"
                pattern_strength = 2
            else:
                candlestick_pattern = "ПЕРЕВЕРНУТЫЙ МОЛОТ"
                pattern_strength = 2
    
    # === СИСТЕМА ОЦЕНКИ ВХОДА 1H ===
    signals_1h = []
    entry_score = 0
    entry_price = current_price
    stop_loss = 0
    take_profit = 0
    entry_type = None
    
    # Получаем ключевые уровни и волатильность из 4H
    key_levels_4h = four_h_signal.get('key_levels', {})
    ema9_4h = key_levels_4h.get('ema9')
    ema21_4h = key_levels_4h.get('ema21')
    ema50_4h = key_levels_4h.get('ema50')
    
    volatility_info = four_h_signal.get('volatility_info', {})
    volatility_acceptable = volatility_info.get('acceptable', True)
    volatility_state = volatility_info.get('state', 'NORMAL')
    atr_pct_4h = volatility_info.get('atr_pct', 0)
    
    # Проверяем волатильность перед входом
    if not volatility_acceptable:
        signals_1h.append(f"🔴 Волатильность неприемлема ({volatility_state}, {atr_pct_4h:.2f}%) - блокировка входа")
        entry_score = 0
    # Проверяем, что 4H дал зеленый или желтый свет
    elif four_h_signal.get('action') == 'STOP':
        signals_1h.append("🔴 4H заблокировал вход - пропускаем")
        entry_score = 0
    elif four_h_signal.get('action') == 'ATTENTION':
        signals_1h.append("🟡 4H в режиме ОСТОРОЖНО - повышенные требования к входу")
        entry_score -= 2  # Штраф за неуверенность 4H
    
    if entry_score == 0 or four_h_signal.get('action') == 'STOP':
        # Пропускаем дальнейший анализ
        pass
    elif trend_1d == "BULLISH":
        # === БЫЧИЙ СЦЕНАРИЙ - поиск входа в LONG ===
        
        # 0. ПОДТВЕРЖДЕНИЕ ТРЕНДА через EMA21(4H)
        if ema21_4h and current_price > ema21_4h:
            signals_1h.append(f"✅ Цена выше EMA21(4H): {current_price:.4f} > {ema21_4h:.4f} - тренд подтвержден")
            entry_score += 1
        elif ema21_4h and current_price < ema21_4h:
            signals_1h.append(f"⚠️ Цена ниже EMA21(4H): {current_price:.4f} < {ema21_4h:.4f} - слабая позиция")
            entry_score -= 1
        
        # 1. ПАТТЕРН - сильное подтверждение
        if candlestick_pattern in ["БЫЧЬЕ ПОГЛОЩЕНИЕ", "МОЛОТ"]:
            signals_1h.append(f"🕯️✅ Свечной паттерн: {candlestick_pattern}")
            entry_score += pattern_strength
        
        # 2. ОТСКОК ОТ EMA - лучшая точка входа
        distance_to_ema20 = abs(current_price - ema20_current) / ema20_current * 100
        
        if distance_to_ema20 < 0.5:  # Очень близко к EMA20
            signals_1h.append(f"✅✅ ИДЕАЛЬНЫЙ ОТСКОК от EMA20 ({distance_to_ema20:.2f}%)")
            entry_score += 3
            entry_type = "BOUNCE_EMA20"
            entry_price = current_price
            stop_loss = min(ema20_current * 0.995, current_low * 0.995)
        
        elif distance_to_ema20 < 1.0:  # Хорошая зона
            signals_1h.append(f"✅ Хорошая зона у EMA20 ({distance_to_ema20:.2f}%)")
            entry_score += 2
            entry_type = "NEAR_EMA20"
            entry_price = current_price
            stop_loss = ema20_current * 0.99
        
        # 3. MACD ПОДТВЕРЖДЕНИЕ
        if current_macd > current_signal and hist_diff > 0:
            signals_1h.append("✅ MACD: Бычье пересечение + растущая гистограмма")
            entry_score += 2
        elif current_macd > current_signal:
            signals_1h.append("✅ MACD: Бычье расположение")
            entry_score += 1
        
        # 4. STOCHASTIC - вход из перепроданности
        if stoch_k and stoch_d:
            if stoch_k < 30 and stoch_k > stoch_d and prev_stoch_k < prev_stoch_d:
                signals_1h.append("✅✅ Stochastic: Выход из перепроданности с пересечением")
                entry_score += 3
            elif stoch_k < 30:
                signals_1h.append("✅ Stochastic: Зона перепроданности")
                entry_score += 1
        
        # 5. RSI - подтверждение
        if current_rsi and current_rsi < 60:
            signals_1h.append(f"✅ RSI: {current_rsi:.1f} (есть пространство для роста)")
            entry_score += 1
        elif current_rsi and current_rsi > 70:
            signals_1h.append(f"⚠️ RSI: {current_rsi:.1f} (перекупленность)")
            entry_score -= 1
        
        # 6. VOLUME - подтверждение движения
        if volume_ratio > 1.5:
            signals_1h.append(f"✅✅ Volume: Сильный интерес ({volume_ratio:.2f}x)")
            entry_score += 2
        elif volume_ratio > 1.2:
            signals_1h.append(f"✅ Volume: Повышенный интерес ({volume_ratio:.2f}x)")
            entry_score += 1
        elif volume_ratio < 0.8:
            signals_1h.append(f"⚠️ Volume: Слабый интерес ({volume_ratio:.2f}x)")
            entry_score -= 1
        
        # 7. РАССТОЯНИЕ ДО УРОВНЕЙ
        if distance_to_resistance > 2.0:
            signals_1h.append(f"✅ До сопротивления: {distance_to_resistance:.2f}% (хороший запас)")
            entry_score += 1
        elif distance_to_resistance < 1.0:
            signals_1h.append(f"⚠️ Близко к сопротивлению: {distance_to_resistance:.2f}%")
            entry_score -= 1
        
        # 8. ORDERBOOK АНАЛИЗ
        if orderbook_signals:
            for signal in orderbook_signals:
                signals_1h.append(f"📚 {signal}")
            
            if orderbook_score > 0:
                signals_1h.append(f"✅ Orderbook поддерживает LONG (+{orderbook_score} баллов)")
                entry_score += min(orderbook_score, 3)  # Максимум +3 балла
            elif orderbook_score < 0:
                signals_1h.append(f"⚠️ Orderbook против LONG ({orderbook_score} баллов)")
                entry_score += orderbook_score  # Вычитаем баллы
    
    elif trend_1d == "BEARISH":
        # === МЕДВЕЖИЙ СЦЕНАРИЙ - поиск входа в SHORT ===
        
        # 0. ПОДТВЕРЖДЕНИЕ ТРЕНДА через EMA21(4H)
        if ema21_4h and current_price < ema21_4h:
            signals_1h.append(f"✅ Цена ниже EMA21(4H): {current_price:.4f} < {ema21_4h:.4f} - тренд подтвержден")
            entry_score += 1
        elif ema21_4h and current_price > ema21_4h:
            signals_1h.append(f"⚠️ Цена выше EMA21(4H): {current_price:.4f} > {ema21_4h:.4f} - слабая позиция")
            entry_score -= 1
        
        # 1. ПАТТЕРН - сильное подтверждение
        if candlestick_pattern in ["МЕДВЕЖЬЕ ПОГЛОЩЕНИЕ", "ПАДАЮЩАЯ ЗВЕЗДА"]:
            signals_1h.append(f"🕯️✅ Свечной паттерн: {candlestick_pattern}")
            entry_score += pattern_strength
        
        # 2. ОТСКОК ОТ EMA - лучшая точка входа
        distance_to_ema20 = abs(current_price - ema20_current) / ema20_current * 100
        
        if distance_to_ema20 < 0.5:  # Очень близко к EMA20
            signals_1h.append(f"✅✅ ИДЕАЛЬНЫЙ ОТСКОК от EMA20 ({distance_to_ema20:.2f}%)")
            entry_score += 3
            entry_type = "BOUNCE_EMA20"
            entry_price = current_price
            stop_loss = max(ema20_current * 1.005, current_high * 1.005)
        
        elif distance_to_ema20 < 1.0:  # Хорошая зона
            signals_1h.append(f"✅ Хорошая зона у EMA20 ({distance_to_ema20:.2f}%)")
            entry_score += 2
            entry_type = "NEAR_EMA20"
            entry_price = current_price
            stop_loss = ema20_current * 1.01
        
        # 3. MACD ПОДТВЕРЖДЕНИЕ
        if current_macd < current_signal and hist_diff < 0:
            signals_1h.append("✅ MACD: Медвежье пересечение + падающая гистограмма")
            entry_score += 2
        elif current_macd < current_signal:
            signals_1h.append("✅ MACD: Медвежье расположение")
            entry_score += 1
        
        # 4. STOCHASTIC - вход из перекупленности
        if stoch_k and stoch_d:
            if stoch_k > 70 and stoch_k < stoch_d and prev_stoch_k > prev_stoch_d:
                signals_1h.append("✅✅ Stochastic: Выход из перекупленности с пересечением")
                entry_score += 3
            elif stoch_k > 70:
                signals_1h.append("✅ Stochastic: Зона перекупленности")
                entry_score += 1
        
        # 5. RSI - подтверждение
        if current_rsi and current_rsi > 40:
            signals_1h.append(f"✅ RSI: {current_rsi:.1f} (есть пространство для падения)")
            entry_score += 1
        elif current_rsi and current_rsi < 30:
            signals_1h.append(f"⚠️ RSI: {current_rsi:.1f} (перепроданность)")
            entry_score -= 1
        
        # 6. VOLUME - подтверждение движения
        if volume_ratio > 1.5:
            signals_1h.append(f"✅✅ Volume: Сильный интерес ({volume_ratio:.2f}x)")
            entry_score += 2
        elif volume_ratio > 1.2:
            signals_1h.append(f"✅ Volume: Повышенный интерес ({volume_ratio:.2f}x)")
            entry_score += 1
        elif volume_ratio < 0.8:
            signals_1h.append(f"⚠️ Volume: Слабый интерес ({volume_ratio:.2f}x)")
            entry_score -= 1
        
        # 7. РАССТОЯНИЕ ДО УРОВНЕЙ
        if distance_to_support > 2.0:
            signals_1h.append(f"✅ До поддержки: {distance_to_support:.2f}% (хороший запас)")
            entry_score += 1
        elif distance_to_support < 1.0:
            signals_1h.append(f"⚠️ Близко к поддержке: {distance_to_support:.2f}%")
            entry_score -= 1
        
        # 8. ORDERBOOK АНАЛИЗ
        if orderbook_signals:
            for signal in orderbook_signals:
                signals_1h.append(f"📚 {signal}")
            
            if orderbook_score > 0:
                signals_1h.append(f"✅ Orderbook поддерживает SHORT (+{orderbook_score} баллов)")
                entry_score += min(orderbook_score, 3)  # Максимум +3 балла
            elif orderbook_score < 0:
                signals_1h.append(f"⚠️ Orderbook против SHORT ({orderbook_score} баллов)")
                entry_score += orderbook_score  # Вычитаем баллы
    
    # === РАСЧЕТ РИСК-МЕНЕДЖМЕНТА ===
    if stop_loss == 0 and entry_score >= 5:
        # Автоматический расчет стоп-лосса на основе ATR
        if trend_1d == "BULLISH":
            stop_loss = current_low - (current_atr * 1.5)
            # Защита от слишком большого стопа
            max_stop_distance = current_price * 0.03  # Максимум 3%
            if (current_price - stop_loss) / current_price > 0.03:
                stop_loss = current_price * 0.97
        else:
            stop_loss = current_high + (current_atr * 1.5)
            max_stop_distance = current_price * 0.03
            if (stop_loss - current_price) / current_price > 0.03:
                stop_loss = current_price * 1.03
        
        signals_1h.append(f"💰 Стоп-лосс рассчитан по ATR: {stop_loss:.4f}")
    
    # Расчет тейк-профита (риск:прибыль = 1:2)
    if stop_loss > 0:
        if trend_1d == "BULLISH":
            risk_amount = entry_price - stop_loss
            take_profit = entry_price + (risk_amount * 2)
        else:
            risk_amount = stop_loss - entry_price
            take_profit = entry_price - (risk_amount * 2)
        
        risk_reward_ratio = 2.0
        risk_percent = (abs(entry_price - stop_loss) / entry_price) * 100
        
        signals_1h.append(f"🎯 Тейк-профит: {take_profit:.4f} (риск {risk_percent:.2f}%, R:R = 1:{risk_reward_ratio})")
    
    # === ФИНАЛЬНОЕ РЕШЕНИЕ 1H ===
    if entry_score >= 7:
        action_1h = "ENTER"
        action_emoji = "🎯"
        action_text = "ВХОД - Сильные сигналы на 1H"
    elif entry_score >= 5:
        action_1h = "WAIT_BETTER"
        action_emoji = "🟡"
        action_text = "ЖДАТЬ ЛУЧШЕЙ ЦЕНЫ - Хорошие сигналы, но можно улучшить вход"
    else:
        action_1h = "SKIP"
        action_emoji = "🔴"
        action_text = "ПРОПУСТИТЬ - Слабые сигналы на 1H"
    
    summary_1h = (
        f"=== 1H СТРАТЕГИЯ ВХОДА ===\n"
        f"Сигнал 4H: {four_h_signal.get('action', 'UNKNOWN')} (готовность: {four_h_signal.get('readiness_score', 0)} баллов)\n"
        f"Тренд 1D: {trend_1d}\n"
        f"Волатильность 4H: {volatility_state} ({atr_pct_4h:.2f}%)\n"
        f"Оценка входа 1H: {entry_score} баллов\n"
        f"Тип входа: {entry_type if entry_type else 'Не определен'}\n"
        f"\n📊 СИГНАЛЫ 1H:\n"
        f"{chr(10).join(signals_1h) if signals_1h else 'Нет сигналов'}\n"
        f"\n{action_emoji} РЕШЕНИЕ 1H: {action_text}\n"
    )
    
    if action_1h == "ENTER":
        summary_1h += (
            f"\n🎯 ДЕТАЛИ СДЕЛКИ:\n"
            f"Цена входа: {entry_price:.4f}\n"
            f"Стоп-лосс: {stop_loss:.4f}\n"
            f"Тейк-профит: {take_profit:.4f}\n"
            f"Риск: {abs(entry_price - stop_loss) / entry_price * 100:.2f}%\n"
        )
    
    summary_1h += "---\n"
    
    log_to_file("1h_execution_log.txt", summary_1h)
    
    return {
        "action": action_1h,
        "entry_score": entry_score,
        "entry_price": entry_price,
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "entry_type": entry_type,
        "risk_percent": abs(entry_price - stop_loss) / entry_price * 100 if stop_loss > 0 else 0,
        "risk_reward_ratio": 2.0,
        "signals": signals_1h,
        "summary": summary_1h
    }
    
def analyze_15m_stoch_ema_volume(df, symbol="UNKNOWN"):
    """
    Анализирует 15m сигналы: Stochastic (5,3,3), EMA(9), Volume.
    Возвращает словарь с результатами и кратким текстовым резюме.
    """
    stoch_k_period = 5
    stoch_d_period = 3
    stoch_smooth = 3
    ema_period = 9
    volume_ma_period = 20

    # Stochastic (5,3,3)
    from analyzes.atr_rsi_stochastic import calculate_stochastic
    stoch_log, data = calculate_stochastic(df.copy(), k_period=stoch_k_period, d_period=stoch_d_period)
    stoch_k = data['stoch_k'].iloc[-1] if not data.empty else None
    stoch_d = data['stoch_d'].iloc[-1] if not data.empty else None

    # EMA(9)
    from analyzes.multi_timeframe_ma_analysis import calculate_ema
    ema_series = calculate_ema(df['close'], ema_period)
    last_ema = ema_series.iloc[-1] if not ema_series.empty else None
    last_price = df['close'].iloc[-1] if not df.empty else None
    if last_ema is not None and last_price is not None:
        if last_price > last_ema:
            ema_signal = "BUY"
        elif last_price < last_ema:
            ema_signal = "SELL"
        else:
            ema_signal = "NEUTRAL"
    else:
        ema_signal = "n/a"

    # Volume
    from analyzes.multi_timeframe_ma_analysis import analyze_volume
    volume_res = analyze_volume(df, volume_ma_period=volume_ma_period, symbol=f"{symbol} [15m]")

    # Формируем краткое текстовое резюме
    summary = (
        f"=== 15m Stochastic/EMA/Volume Analysis ===\n"
        f"Stochastic %K: {stoch_k:.2f if stoch_k is not None else 'n/a'}, %D: {stoch_d:.2f if stoch_d is not None else 'n/a'}\n"
        f"EMA(9) сигнал: {ema_signal}\n"
        f"Объем: {volume_res.get('current_volume', 'n/a')} vs средний {volume_res.get('avg_volume', 'n/a')}\n"
        f"Сигнал по объему: {volume_res.get('signal', 'n/a')}\n"
        f"---\n"
    )

    # Логирование
    log_to_file("stoch_ema_volume_15m_log.txt", summary)

    return {
        "stoch_k": stoch_k,
        "stoch_d": stoch_d,
        "ema_signal": ema_signal,
        "volume_result": volume_res,
        "summary": summary
    }