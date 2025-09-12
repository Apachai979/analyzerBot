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

    # --- Новый анализ: расположение крупных ордеров относительно текущей цены ---
    def analyze_whale_orders_relative(orders, order_type):
        closest = sorted(orders, key=lambda x: abs(float(x[0]) - current_price))
        if closest:
            price = float(closest[0][0])
            size = float(closest[0][1])
            distance = abs(price - current_price)
            direction = "ниже" if price < current_price else "выше"
            print(f"   🧭 Ближайший китовый {order_type}: {size:.0f} по цене {price} ({direction} рынка, расстояние {distance:.2f})")
            # --- Умозаключения ---
            if distance < current_price * 0.001:  # менее 0.1% от цены
                if order_type == "bid":
                    print("      🟢 Крупная заявка на покупку близко к рынку — это может быть поддержкой, цена с меньшей вероятностью упадёт ниже.")
                else:
                    print("      🔴 Крупная заявка на продажу близко к рынку — это может быть сопротивлением, цена с меньшей вероятностью вырастет выше.")
            elif distance < current_price * 0.005:
                print("      ℹ️ Крупный ордер относительно близко к рынку, влияние умеренное.")
            else:
                print("      💤 Крупный ордер далеко от текущей цены, влияние незначительное.")

    if whale_bids:
        analyze_whale_orders_relative(whale_bids, "bid")
    if whale_asks:
        analyze_whale_orders_relative(whale_asks, "ask")