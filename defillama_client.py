# bot/data/defillama_client.py
import requests
import logging  # Используем стандартный логгер

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