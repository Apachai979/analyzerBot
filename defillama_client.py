# bot/data/defillama_client.py
import requests
import logging  # Используем стандартный логгер
import numpy as np

class DefiLlamaClient:
    def __init__(self):
        self.base_url = "https://api.llama.fi"
    
    def get_total_tvl(self):
        """Получает общий TVL всего DeFi рынка"""
        try:
            response = requests.get(f"{self.base_url}/v2/historicalChainTvl")
            data = response.json()
            return data
        except Exception as e:
            logging.error(f"Ошибка получения общего TVL: {e}")
            return None
    
    def get_chain_tvl(self, chain):
        """Получает TVL конкретного блокчейна"""
        try:
            response = requests.get(f"{self.base_url}/v2/historicalChainTvl/{chain}")
            data = response.json()
            return data
        except Exception as e:
            logging.error(f"Ошибка получения TVL для {chain}: {e}")
            return None
    
    def get_current_tvl(self):
        """Текущий TVL по всем цепочкам"""
        try:
            response = requests.get(f"{self.base_url}/v2/chains")
            data = response.json()
            return data
        except Exception as e:
            logging.error(f"Ошибка получения текущего TVL: {e}")
            return None    
    
def analyze_tvl(chains_data, historical_data_dict):
    """
    Анализирует TVL по цепочкам.
    chains_data: список данных по цепочкам (результат get_current_tvl)
    historical_data_dict: словарь {chain_name: historical_tvl_list} (результат get_chain_tvl для каждой цепочки)
    """
    result = {}
 
    # 1. Определяем рост/падение TVL для каждой цепочки
    for chain in chains_data:
        name = chain.get('name')
        current_tvl = chain.get('tvl', 0)
        historical = historical_data_dict.get(name, [])
        if historical:
            tvl_values = [item['tvl'] for item in historical]
            if len(tvl_values) >= 2:
                change = (current_tvl - tvl_values[-2]) / tvl_values[-2] * 100
                trend = "Рост" if change > 0 else "Падение"
            else:
                trend = "Недостаточно данных"
        else:
            trend = "Нет исторических данных"
        result[name] = {
            "current_tvl": current_tvl,
            "trend": trend
        }
 
    # 2. Наиболее популярные цепочки (по TVL)
    sorted_chains = sorted(chains_data, key=lambda x: x.get('tvl', 0), reverse=True)
    top_chains = [chain['name'] for chain in sorted_chains[:3]]
 
    # 3. Распределение ликвидности
    total_tvl = sum(chain.get('tvl', 0) for chain in chains_data)
    liquidity_distribution = {
        chain['name']: round(chain.get('tvl', 0) / total_tvl * 100, 2) if total_tvl else 0
        for chain in chains_data
    }
 
    # 4. Перспективные экосистемы (рост + высокая ликвидность)
    perspective = [
        name for name, info in result.items()
        if info['trend'] == "Рост" and liquidity_distribution.get(name, 0) > 5
    ]
 
    return {
        "tvl_trends": result,
        "top_chains": top_chains,
        "liquidity_distribution": liquidity_distribution,
        "perspective_chains": perspective
    }