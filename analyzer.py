import pandas as pd
import os
from datetime import datetime
from bybit_client import bybit_client  # Для работы со стаканом и ценами
from config import *
from telegram_utils import send_telegram_message

def calculate_rsi(data, period=14):
    """Рассчитывает RSI"""
    delta = data['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    return rsi

def calculate_sma(data, period):
    """Рассчитывает SMA для заданного периода"""
    return data['close'].rolling(window=period).mean()

def calculate_volatility_stats(df, fast_period, slow_period, lookback_periods):
    """Рассчитывает историческую волатильность расстояния между SMA"""
    if len(df) < slow_period + lookback_periods:
        return None, None, None, None, None
    
    df['sma_fast'] = calculate_sma(df, fast_period)
    df['sma_slow'] = calculate_sma(df, slow_period)
    
    df_clean = df.dropna(subset=['sma_fast', 'sma_slow']).copy()
    df_clean['sma_distance_pct'] = ((df_clean['sma_fast'] - df_clean['sma_slow']) / df_clean['sma_slow']) * 100
    
    recent_data = df_clean['sma_distance_pct'].tail(lookback_periods)
    
    mean_distance = recent_data.mean()
    std_distance = recent_data.std()
    max_distance = recent_data.max()
    min_distance = recent_data.min()
    current_distance = df_clean['sma_distance_pct'].iloc[-1]
    
    return current_distance, mean_distance, std_distance, max_distance, min_distance

def analyze_market_data(market_data, symbol):
    """Анализирует рыночные данные от CoinMarketCap"""
    if not market_data:
        print(f"Нет данных CMC для {symbol}, пропуск.")
        return 0

    # Проверяем, что все нужные поля есть и не None
    required_fields = [
        'volume_mcap_ratio', 'market_cap', 'volume_24h',
        'volume_change_24h', 'market_cap_change_24h'
    ]
    for field in required_fields:
        if field not in market_data or market_data[field] is None:
            print(f"Нет данных CMC для {symbol} (отсутствует {field}), пропуск.")
            return 0

    print(f"\n📈 COINMARKETCAP ANALYSIS: {symbol}")
    print("─" * 40)

    ratio = market_data['volume_mcap_ratio']
    print(f"🔄 Volume/MCap Ratio: {ratio:.2%}")

    score = 0

    if ratio > 0.1:
        print("   🚀 ВЫСОКАЯ ликвидность - актив популярен")
        score += 25
    elif ratio > 0.05:
        print("   📊 ХОРОШАЯ ликвидность - нормальная активность") 
        score += 15
    elif ratio > 0.02:
        print("   ⚪ УМЕРЕННАЯ ликвидность")
        score += 5
    else:
        print("   💤 НИЗКАЯ ликвидность - осторожно с большими объемами")

    print(f"💰 Market Cap: ${market_data['market_cap']:,.0f}")
    print(f"📊 24h Volume: ${market_data['volume_24h']:,.0f}")
    print(f"📉 24h Volume Change: {market_data['volume_change_24h']:+.2f}%")
    print(f"📈 24h Market Cap Change: {market_data['market_cap_change_24h']:+.2f}%")

    if market_data['volume_change_24h'] > 5:
        score += 10
        print("   📈 Объем растет - положительный сигнал")

    if market_data['market_cap_change_24h'] > 2:
        score += 10
        print("   💹 Капитализация растет - бычий сигнал")

    print(f"🎯 CMC Score: {min(25, score)}/25")
    return min(25, score)

def analyze_fear_greed(fgi_data):
    """Анализирует Fear and Greed Index и выдает инсайты"""
    if not fgi_data:
        return 0
    
    current_value = fgi_data['current_value']
    classification = fgi_data['current_classification']
    average_30d = fgi_data['average_30d']
    
    print(f"\n😨😊 FEAR AND GREED INDEX")
    print("─" * 40)
    print(f"📊 Текущее значение: {current_value} - {classification}")
    print(f"📈 Среднее за 30 дней: {average_30d:.1f}")
    
    score = 0
    insights = []
    
    if current_value >= 80:
        insights.append("🚨 ЭКСТРЕМАЛЬНАЯ ЖАДНОСТЬ - возможен разворот вниз")
        score -= 15
    elif current_value >= 60:
        insights.append("📈 ЖАДНОСТЬ - рынок оптимистичен")
        score -= 5
    elif current_value >= 40:
        insights.append("⚪ НЕЙТРАЛЬНО - сбалансированные эмоции")
        score += 5
    elif current_value >= 20:
        insights.append("📉 СТРАХ - рынок пессимистичен")
        score += 10
    else:
        insights.append("🚨 ЭКСТРЕМАЛЬНЫЙ СТРАХ - возможен разворот вверх")
        score += 20
    
    deviation = current_value - average_30d
    if abs(deviation) > 20:
        insights.append("📊 Сильное отклонение от среднего - возможна коррекция")
        if deviation < 0:
            score += 10
        else:
            score -= 10
    
    for insight in insights:
        print(f"   {insight}")
    
    print(f"🎯 FGI Score: {score}/25")
    
    return min(25, max(-25, score))

def analyze_orderbook(bids, asks, bid_volume, ask_volume, whale_bids, whale_asks, current_price, config):
    """Анализирует стакан цен"""
    if not bids or not asks:
        print("❌ Не удалось получить данные стакана")
        return
    
    print(f"\n📊 ORDER BOOK ANALYSIS ({config.orderbook_levels} уровней)")
    print("─" * 50)
    print(f"⚙️ Параметры: WHALE_SIZE={config.whale_size:,}, Уровней={config.orderbook_levels}")
    
    if ask_volume > 0:
        liquidity_ratio = bid_volume / ask_volume
        print(f"📈 Соотношение объемов: {liquidity_ratio:.2f}")
        
        if liquidity_ratio > 2.0:
            print("   🟢 СИЛЬНЫЕ ПОКУПАТЕЛИ - преобладают bids")
        elif liquidity_ratio > 1.5:
            print("   🟡 Умеренные покупатели")
        elif liquidity_ratio > 0.8:
            print("   ⚪ БАЛАНС - паритет сил")
        elif liquidity_ratio > 0.5:
            print("   🟠 Умеренные продавцы")
        else:
            print("   🔴 СИЛЬНЫЕ ПРОДАВЦЫ - преобладают asks")
    
    print(f"🐋 Крупные ордера (> {config.whale_size:,}): {len(whale_bids)} bids, {len(whale_asks)} asks")
    
    if whale_bids:
        print(f"   🟢 Китские покупки: {', '.join([f'{float(b[1]):.0f}@{b[0]}' for b in whale_bids[:3]])}")
    if whale_asks:
        print(f"   🔴 Китские продажи: {', '.join([f'{float(a[1]):.0f}@{a[0]}' for a in whale_asks[:3]])}")

def analyze_sma_signals(df, current_price, symbol, config, cmc_score=0, fgi_score=0):
    """Анализирует данные и возвращает результат с учетом CMC и Fear and Greed Index"""
    if df is None or len(df) < SLOW_PERIOD:
        print("Недостаточно данных для анализа")
        return None
    
    result = calculate_volatility_stats(df, FAST_PERIOD, SLOW_PERIOD, VOLATILITY_LOOKBACK)
    if result[0] is None:
        return None
        
    current_dist, mean_dist, std_dist, max_dist, min_dist = result
    
    df['sma_fast'] = calculate_sma(df, FAST_PERIOD)
    df['sma_slow'] = calculate_sma(df, SLOW_PERIOD)
    current_sma_fast = df['sma_fast'].iloc[-1]
    current_sma_slow = df['sma_slow'].iloc[-1]
    previous_sma_fast = df['sma_fast'].iloc[-2]
    previous_sma_slow = df['sma_slow'].iloc[-2]
    
    print(f"\n=== АНАЛИЗ ДЛЯ {symbol} ===")
    print(f"Текущая цена: {current_price:.2f}")
    print(f"SMA{FAST_PERIOD}: {current_sma_fast:.2f}")
    print(f"SMA{SLOW_PERIOD}: {current_sma_slow:.2f}")
    print(f"Текущее расстояние между SMA: {current_dist:+.2f}%")
    print(f"Анализ волатильности за последние {VOLATILITY_LOOKBACK} баров")
    
    if std_dist > 0:
        z_score = (current_dist - mean_dist) / std_dist
        print(f"Z-score расстояния: {z_score:+.2f}")
        
        if abs(z_score) < 0.5:
            print("📊 Расстояние near исторической нормы")
        elif abs(z_score) < 1.5:
            print("⚠️  Расстояние умеренно отклоняется от нормы")
        else:
            print("🚨 ЭКСТРЕМАЛЬНОЕ расстояние! Возможна коррекция")
    
    print(f"Исторический диапазон: [{min_dist:+.2f}%, {max_dist:+.2f}%]")
    
    signal = "NEUTRAL"
    if previous_sma_fast < previous_sma_slow and current_sma_fast > current_sma_slow:
        print("🎯 СИГНАЛ ПОКУПКИ: Золотой крест")
        signal = "BUY"
    elif previous_sma_fast > previous_sma_slow and current_sma_fast < current_sma_slow:
        print("🎯 СИГНАЛ ПРОДАЖИ: Мертвый крест")
        signal = "SELL"
    else:
        print("📊 Пересечения SMA нет - сигнал отсутствует")
    
    if current_price > current_sma_slow:
        print("📈 Цена выше SMA50 - восходящий тренд")
        trend = "BULLISH"
    else:
        print("📉 Цена ниже SMA50 - нисходящий тренд")
        trend = "BEARISH"
    
    df['volume_ma'] = df['volume'].rolling(window=VOLUME_MA_PERIOD).mean()
    current_volume = df['volume'].iloc[-1]
    avg_volume = df['volume_ma'].iloc[-1]
    volume_ratio = current_volume / avg_volume
    
    print(f"📊 Объем: {current_volume:.0f} vs средний {avg_volume:.0f} (x{volume_ratio:.1f})")
    if volume_ratio > 2.0:
        print("🚀 ВЫСОКИЙ ОБЪЕМ! Движение подтверждено")
    elif volume_ratio < 0.5:
        print("⚠️  НИЗКИЙ ОБЪЕМ! Движение не подтверждено")
    
    df['rsi'] = calculate_rsi(df, RSI_PERIOD)
    current_rsi = df['rsi'].iloc[-1]
    print(f"📶 RSI({RSI_PERIOD}): {current_rsi:.1f}")
    
    if current_rsi > 70:
        print("🎯 Перекупленность (RSI > 70)")
    elif current_rsi < 30:
        print("🎯 Перепроданность (RSI < 30)")
    
    tech_score = 0
    
    if current_dist < -2.5: 
        tech_score += 20
        print("   📉 +20 очков: Сильная перепроданность по SMA")
    elif current_dist < -1.5:
        tech_score += 12
        print("   📉 +12 очков: Умеренная перепроданность по SMA")
    elif current_dist < -0.5:
        tech_score += 5
        print("   📉 +5 очков: Легкая перепроданность по SMA")
    elif current_dist > 2.5:
        tech_score -= 10
        print("   📈 -10 очков: Сильная перекупленность по SMA")
    elif current_dist > 1.5:
        tech_score -= 5
        print("   📈 -5 очков: Умеренная перекупленность по SMA")
        
    if current_rsi < 30:
        tech_score += 15
        print("   📶 +15 очков: Сильная перепроданность по RSI")
    elif current_rsi < 35:
        tech_score += 10
        print("   📶 +10 очков: Перепроданность по RSI")
    elif current_rsi < 40:
        tech_score += 5
        print("   📶 +5 очков: Приближение к перепроданности по RSI")
    elif current_rsi > 70:
        tech_score -= 10
        print("   📶 -10 очков: Перекупленность по RSI")
    elif current_rsi > 65:
        tech_score -= 5
        print("   📶 -5 очков: Приближение к перекупленности по RSI")
        
    if volume_ratio > 2.0:
        tech_score += 10
        print("   📊 +10 очков: Высокий объем подтверждает движение")
    elif volume_ratio > 1.2:
        tech_score += 5
        print("   📊 +5 очков: Хороший объем")
    elif volume_ratio < 0.5:
        tech_score -= 5
        print("   📊 -5 очков: Низкий объем")
        
    if current_price > current_sma_slow:
        tech_score += 10
        print("   📈 +10 очков: Цена выше долгосрочного тренда")
    else:
        print("   📉 +0 очков: Цена ниже долгосрочного тренда")
    
    cmc_score_limited = min(25, max(0, cmc_score))
    print(f"   🌐 +{cmc_score_limited} очков: CoinMarketCap анализ")
    
    fgi_positive_score = max(0, fgi_score)
    fgi_score_limited = min(20, fgi_positive_score)
    print(f"   😨😊 +{fgi_score_limited} очков: Fear and Greed Index")
    
    bonus_score = 0
    if signal == "BUY" and current_dist < -2.0 and current_rsi < 35 and fgi_score > 15:
        bonus_score = 10
        print("   🎯 +10 очков: Сильный бычий конфирмация")
    elif signal == "SELL" and current_dist > 2.0 and current_rsi > 65 and fgi_score < -15:
        bonus_score = 10
        print("   🎯 +10 очков: Сильный медвежий конфирмация")
    
    total_score = tech_score + cmc_score_limited + fgi_score_limited + bonus_score
    final_score = max(0, min(100, total_score))
    
    print(f"\n🎯 ИТОГОВЫЙ SCORE: {final_score}/100")
    print(f"   📊 Тех. анализ: {tech_score}/55")
    print(f"   🌐 CMC: {cmc_score_limited}/25") 
    print(f"   😨😊 FGI: {fgi_score_limited}/20")
    if bonus_score > 0:
        print(f"   🎯 Бонус: {bonus_score}/10")
    
    if final_score >= 80:
        print("   💪 СИЛЬНЫЙ СИГНАЛ - высокая уверенность")
    elif final_score >= 60:
        print("   👍 ХОРОШИЙ СИГНАЛ - умеренная уверенность")
    elif final_score >= 40:
        print("   🤔 СЛАБЫЙ СИГНАЛ - низкая уверенность")
    else:
        print("   ⚪ НЕЙТРАЛЬНО - недостаточно сигналов")
    
    return {
        'signal': signal,
        'score': final_score,
        'trend': trend,
        'rsi': current_rsi,
        'volume_ratio': volume_ratio,
        'sma_distance': current_dist,
        'tech_score': tech_score,
        'cmc_score': cmc_score_limited,
        'fgi_score': fgi_score_limited,
        'bonus_score': bonus_score
    }

def print_summary_table(results):
    """
    Формирует и сохраняет сводную таблицу по всем монетам в Excel-файл с датой в отдельной папке 'tables'.
    """
    if not results:
        print("❌ Нет данных для отображения")
        return

    # Создаём папку tables, если её нет
    tables_dir = "tables"
    os.makedirs(tables_dir, exist_ok=True)

    # Формируем имя файла с датой и временем
    now_str = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    filename = f"analysis_summary_{now_str}.xlsx"
    filepath = os.path.join(tables_dir, filename)

    # Формируем DataFrame
    df = pd.DataFrame(results)
    if 'note' not in df.columns:
        df['note'] = ""
    df = df.rename(columns={
        'symbol': 'Монета',
        'price': 'Цена',
        'signal': 'Сигнал',
        'score': 'Общий балл',
        'cmc_score': 'CMC',
        'fgi_score': 'FGI',
        'tvl_score': 'TVL',
        'trend': 'Тренд',
        'note': 'Комментарий'
    })
    df = df.sort_values(by='Общий балл', ascending=False)
    df.to_excel(filepath, index=False)
    print(f"✅ Сводная таблица сохранена в {filepath}")

    display_cols = ['Монета', 'Цена', 'Сигнал', 'Общий балл', 'CMC', 'FGI', 'TVL', 'Тренд', 'Комментарий']
    print("\n🎯 СВОДНАЯ ТАБЛИЦА АНАЛИЗА")
    print(df[display_cols].to_string(index=False))

    buy_signals = (df['Сигнал'] == 'BUY').sum()
    sell_signals = (df['Сигнал'] == 'SELL').sum()
    neutral_signals = len(df) - buy_signals - sell_signals
    print(f"\n📊 Статистика: 🟢 {buy_signals} | 🔴 {sell_signals} | ⚪ {neutral_signals}")

def send_telegram_signals(results):
    """
    Отправляет сигналы в Telegram для сильных BUY/SELL по результатам анализа.
    """
    if not results:
        return

    df = pd.DataFrame(results)
    for _, row in df.iterrows():
        if row['signal'] == 'BUY' and row['score'] > 70:
            action = "🚀 СИЛЬНАЯ ПОКУПКА"
        elif row['signal'] == 'SELL' and row['score'] > 70:
            action = "🔻 СИЛЬНАЯ ПРОДАЖА"
        elif row['signal'] == 'BUY' and row['score'] > 50:
            action = "📈 ПОКУПКА"
        elif row['signal'] == 'SELL' and row['score'] > 50:
            action = "📉 ПРОДАЖA"
        else:
            action = None

        if action:
            message = (
                f"⚡️ {row['symbol']}\n"
                f"Цена: ${row['price']:.4f}\n"
                f"Сигнал: {row['signal']}\n"
                f"Общий балл: {row['score']}\n"
                f"CMC: {row.get('cmc_score', '')}, FGI: {row.get('fgi_score', '')}, TVL: {row.get('tvl_score', '')}\n"
                f"Действие: {action}\n"
                f"Комментарий: {row.get('note', '')}"
            )
            send_telegram_message(message)