import asyncio
import aiohttp
import pandas as pd
import matplotlib.pyplot as plt

# === 設定回測參數 ===
SYMBOL = "BTCUSDT"
INTERVAL = "30m"      # 使用 30 分鐘 K 線
LIMIT = 3000         # 回測過去 1000 根 K 線
RISK_REWARD = 1.5    # 損益比 1:1.5
THRESHOLD = 0.001    # 0.1% 的過濾門檻
RISK_PERCENT = 0.02  # 願意虧損本金2%

async def fetch_historical_data():
    """ 從幣安抓取歷史數據 """
    url = "https://api.binance.com/api/v3/klines"
    params = {"symbol": SYMBOL, "interval": INTERVAL, "limit": LIMIT}
    
    print(f"🔄 正在下載 {SYMBOL} 過去 {LIMIT} 根 K 線數據...")
    async with aiohttp.ClientSession() as session:
        async with session.get(url, params=params) as response:
            data = await response.json()
            df = pd.DataFrame(data, columns=[
                "open_time", "open", "high", "low", "close", "volume", 
                "close_time", "q_vol", "num_trades", "t_base", "t_quote", "ignore"
            ])
            # 轉換數據格式
            for col in ["open", "high", "low", "close"]:
                df[col] = df[col].astype(float)
            return df

def run_backtest(df):
    """ 執行回測邏輯 (包含繪圖功能) """
    trades = []
    balance = 1000 # 初始本金
    
    # === 記錄資金變化的列表 (畫圖用) ===
    equity_curve = [balance] 
    
    wins = 0
    losses = 0

    print(f"🚀 開始回測 (策略: FVG + RR 1:{RISK_REWARD})...")
    
    # 迴圈遍歷每一根 K 線 (扣掉最後 50 根以免數據不足)
    for i in range(2, len(df) - 50):
        # 取得當下這組 K 線
        candle_n = df.iloc[i]     # 當前
        candle_n2 = df.iloc[i-2]  # 前兩根
        current_close = candle_n['close']
        
        signal = None
        entry = 0
        sl = 0
        tp = 0

        # 1.看漲 FVG
        if candle_n["low"] > candle_n2["high"]:
            gap = candle_n["low"] - candle_n2["high"]
            if (gap / current_close) > THRESHOLD:
                signal = "LONG"
                entry = candle_n2["high"] # 缺口下緣
                sl = candle_n2["low"]     # 止損
                risk = entry - sl
                tp = entry + (risk * RISK_REWARD)

        # 2. 看跌 FVG
        elif candle_n["high"] < candle_n2["low"]:
            gap = candle_n2["low"] - candle_n["high"]
            if (gap / current_close) > THRESHOLD:
                signal = "SHORT"
                entry = candle_n2["low"]  # 缺口上緣
                sl = candle_n2["high"]    # 止損
                risk = sl - entry
                tp = entry - (risk * RISK_REWARD)

        # === 模擬未來走勢 (驗證訊號) ===
        if signal:
            trade_result = "PENDING"
            
            # 往未來檢查接下來的 48 根 K 線
            for j in range(i + 1, i + 49):
                future_candle = df.iloc[j]
                
                if signal == "LONG":
                    if future_candle['low'] <= sl:
                        trade_result = "LOSS"
                        break
                    elif future_candle['high'] >= tp:
                        trade_result = "WIN"
                        break
                    if future_candle['low'] > entry:
                        continue 

                elif signal == "SHORT":
                    if future_candle['high'] >= sl:
                        trade_result = "LOSS"
                        break
                    elif future_candle['low'] <= tp:
                        trade_result = "WIN"
                        break
            
            # === 記錄結果 ===
            if trade_result != "PENDING":
                trades.append({
                    "index": i, "type": signal, "result": trade_result,
                    "entry": entry, "sl": sl, "tp": tp
                })

                # 每次願意虧損當下本金的 2% 
                risk_percent = 0.02
                risk_amount = balance * risk_percent

                # 更新餘額
                if trade_result == "WIN":
                    wins += 1
                    # 獲利 = 風險金額 * 盈虧比
                    profit = risk_amount * RISK_REWARD
                    balance += profit
                else: # LOSS
                    losses += 1
                    # 虧損 = 風險金額
                    loss = risk_amount
                    balance -= loss
                
                # 新餘額加入曲線列表
                equity_curve.append(balance)

    # === 輸出統計結果 ===
    total_trades = wins + losses
    win_rate = (wins / total_trades * 100) if total_trades > 0 else 0
    
    print("\n" + "="*30)
    print(f"📊 回測報告 - {SYMBOL} ({INTERVAL})")
    print("="*30)
    print(f"總交易次數: {total_trades} 次")
    print(f"✅ 獲利次數: {wins} 次")
    print(f"❌ 虧損次數: {losses} 次")
    print(f"🏆 勝率 (Win Rate): {win_rate:.2f}%")
    print(f"💰 模擬最終餘額: ${balance:.2f} (初始 $1000)")
    print("="*30)

    # === 畫出資金曲線 ===
    try:
        plt.figure(figsize=(10, 6))
        plt.plot(equity_curve, label='Account Balance ($)', color='blue', linewidth=2)
        plt.title(f'Backtest Equity Curve (Win Rate: {win_rate:.2f}%)')
        plt.xlabel('Number of Trades')
        plt.ylabel('Balance (USD)')
        plt.legend()
        plt.grid(True, linestyle='--')
        
        # 儲存圖片
        plt.savefig('equity_curve.png') 
        print("📈 資金曲線圖已儲存為 equity_curve.png")
        plt.show()
    except Exception as e:
        print(f"繪圖時發生錯誤 (可能是環境問題，但不影響數據): {e}")

# 執行程式
if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    df = loop.run_until_complete(fetch_historical_data())
    run_backtest(df)