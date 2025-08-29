# bot/analyzers/tvl_analyzer.py
import pandas as pd
import logging  # Используем стандартный логгер

class TVLAnalyzer:
    def analyze_total_tvl(self, tvl_data):
        """Анализирует общий TVL рынка"""
        if not tvl_data:
            return 0
        
        # Берем последние 30 дней для анализа
        recent_data = tvl_data[-30:]
        
        df = pd.DataFrame(recent_data, columns=['date', 'tvl'])
        df['date'] = pd.to_datetime(df['date'], unit='s')
        df['change'] = df['tvl'].pct_change()
        
        # Анализ тренда
        trend_score = 0
        last_7_days = df['change'].tail(7).mean()
        last_30_days = df['change'].mean()
        
        if last_7_days > 0.01:  # +1% за неделю
            trend_score += 20
            logging.info("📈 Сильный рост TVL - бычий сигнал")
        elif last_7_days > 0:
            trend_score += 10
            logging.info("📈 Умеренный рост TVL")
        elif last_7_days < -0.01:  # -1% за неделю
            trend_score -= 20
            logging.info("📉 Сильное падение TVL - медвежий сигнал")
        
        return trend_score
    
    def analyze_chain_rotation(self, current_tvl_data):
        """Анализирует вращение капитала между блокчейнами"""
        if not current_tvl_data:
            return {}
        
        # Сортируем по TVL
        chains_sorted = sorted(current_tvl_data, key=lambda x: x['tvl'], reverse=True)
        
        insights = {}
        for chain in chains_sorted[:10]:  # Топ-10 цепочек
            chain_name = chain['name']
            chain_tvl = chain['tvl']
            chain_change = chain.get('change', 0)
            
            insights[chain_name] = {
                'tvl': chain_tvl,
                'change_24h': chain_change,
                'score': self._calculate_chain_score(chain_change)
            }
        
        return insights
    
    def _calculate_chain_score(self, change_24h):
        """Рассчитывает score для цепочки based на изменении TVL"""
        if change_24h > 0.05:  # +5% за 24h
            return 25
        elif change_24h > 0.02:  # +2% за 24h
            return 15
        elif change_24h > 0:
            return 5
        elif change_24h < -0.05:  # -5% за 24h
            return -20
        else:
            return 0