from defillama_client import DefiLlamaClient, analyze_tvl

def analyze_chains_and_market(cmc_data):
    """
    Фильтрует chains по платформам из cmc_data, анализирует TVL,
    сравнивает с объемом торгов и ценой токена, добавляет рекомендации.
    Возвращает список словарей с результатами анализа.
    """
    defillama_client = DefiLlamaClient()
    chains = defillama_client.get_current_tvl()
    if not chains:
        print("❌ Не удалось получить данные цепочек с DefiLlama.")
        return []

    # Словарь: {platform_name: [token_symbol1, token_symbol2, ...]}
    platform_token_map = {}
    for info in cmc_data.values():
        platform_name = info.get('platform_name')
        token_symbol = info.get('symbol')
        if platform_name and token_symbol:
            platform_token_map.setdefault(platform_name, []).append(token_symbol)

    filtered_chains = [chain for chain in chains if chain.get('name') in platform_token_map]
    historical = {chain['name']: defillama_client.get_chain_tvl(chain['name']) for chain in filtered_chains}
    tvl_analysis = analyze_tvl(filtered_chains, historical)

    results = []
    for chain in filtered_chains:
        chain_name = chain.get('name')
        token_symbols = platform_token_map.get(chain_name, [])
        for token_symbol in token_symbols:
            # Ищем данные токена в cmc_data
            cmc_info = None
            for info in cmc_data.values():
                if info.get('symbol') == token_symbol:
                    cmc_info = info
                    break
            if not cmc_info:
                continue

            tvl = chain.get('tvl', 0)
            price = cmc_info.get('price', 0)
            volume_24h = cmc_info.get('volume_24h', 0)
            market_cap = cmc_info.get('market_cap', 0)
            percent_change_24h = cmc_info.get('percent_change_24h')
            percent_change_7d = cmc_info.get('percent_change_7d')
            percent_change_30d = cmc_info.get('percent_change_30d')

            volume_tvl_ratio = volume_24h / tvl if tvl else 0
            price_tvl_ratio = price / tvl if tvl else 0
            mcap_tvl_ratio = market_cap / tvl if tvl else 0

            # Рекомендации
            recs = []
            # TVL/объем/капитализация
            if volume_tvl_ratio > 1:
                recs.append("Высокий объем торгов относительно TVL — возможна спекуляция.")
            elif volume_tvl_ratio < 0.05:
                recs.append("Низкий объем торгов относительно TVL — низкая активность.")

            if mcap_tvl_ratio < 1:
                recs.append("Капитализация ниже TVL — возможно недооценена.")
            elif mcap_tvl_ratio > 5:
                recs.append("Капитализация сильно выше TVL — возможен перегрев.")

            if price_tvl_ratio > 0.0001:
                recs.append("Цена токена высока относительно TVL — осторожно с покупкой.")
            elif price_tvl_ratio < 0.00001:
                recs.append("Цена токена низка относительно TVL — возможен потенциал роста.")

            # Дополнительные рекомендации по волатильности и динамике цены
            if volume_24h and market_cap and market_cap > 0:
                volume_mcap_ratio = volume_24h / market_cap
                if volume_mcap_ratio > 2:
                    recs.append("Монета волатильна и интересна для краткосрочных сделок.")
                elif volume_mcap_ratio > 0.5:
                    recs.append("Высокий объем может означать продолжение волатильности.")

            if percent_change_30d and percent_change_30d > 50:
                if percent_change_24h and percent_change_24h < 0:
                    recs.append("Сейчас идет коррекция после сильного роста.")
                else:
                    recs.append("Монета находится в фазе роста.")

            if percent_change_24h and abs(percent_change_24h) > 10:
                recs.append("Требуется осторожность: возможны резкие движения как вверх, так и вниз.")

            tvl_trend = tvl_analysis['tvl_trends'].get(chain_name, {}).get('trend', 'N/A')

            results.append({
                'chain': chain_name,
                'token': token_symbol,
                'token_name': cmc_info.get('name', ''),
                'tvl': tvl,
                'price': price,
                'volume_24h': volume_24h,
                'market_cap': market_cap,
                'percent_change_24h': percent_change_24h,
                'percent_change_7d': percent_change_7d,
                'percent_change_30d': percent_change_30d,
                'volume_tvl_ratio': round(volume_tvl_ratio, 4),
                'price_tvl_ratio': round(price_tvl_ratio, 8),
                'mcap_tvl_ratio': round(mcap_tvl_ratio, 4),
                'tvl_trend': tvl_trend,
                'recommendations': recs
            })
    return results