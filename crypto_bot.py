import aiohttp
import pandas as pd
import asyncio
import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler

#Logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# === 核心邏輯區 ===
class StrategyEngine:
    def __init__(self):
        self.base_url = "https://api.binance.com/api/v3/klines"
        self.symbol = "BTCUSDT"
        self.interval = "1h" #1小時的雜訊少

    async def fetch_data(self):
        params = {
            "symbol": self.symbol,
            "interval": self.interval,
            "limit": 100 # 抓過去 100 小時的資料
        }
        async with aiohttp.ClientSession() as session:
            async with session.get(self.base_url, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    # === 資料轉換 (Data Parsing) ===
                    # 幣安給的資料是純數字陣列
                    df = pd.DataFrame(data, columns=[
                        "open_time", "open", "high", "low", "close", "volume", 
                        "close_time", "q_vol", "num_trades", "t_base", "t_quote", "ignore"
                    ])
                    # 把文字格式的數字轉成浮點數 (Float)
                    df["high"] = df["high"].astype(float)
                    df["low"] = df["low"].astype(float)
                    df["close"] = df["close"].astype(float)
                    return df
                else:
                    return None

    def detect_fvg(self, df):
        """
        演算法：檢測 FVG 並計算「進場、止損、止盈」價格
        """
        last_candle = df.iloc[-2] # 第 n 根 (收盤)
        prev_candle = df.iloc[-4] # 第 n-2 根 (信號起始點)
        
        current_price = df.iloc[-1]["close"]
        threshold_percent = 0.002 # 0.2% 的過濾門檻

        # 1. 判斷看漲 FVG (Bullish)
        # 缺口範圍：[第 n-2 根的高點] <---> [第 n 根的低點]
        if last_candle["low"] > prev_candle["high"]:
            gap_size = last_candle["low"] - prev_candle["high"]
            gap_percent = gap_size / current_price
            
            if gap_percent > threshold_percent:
                # === 策略計算邏輯 ===
                entry_price = prev_candle["high"] # 進場點：缺口下緣 (回踩買入)
                stop_loss = prev_candle["low"]    # 止損點：第 n-2 根的低點 (跌破就跑)
                
                # 計算風險 (Risk)
                risk = entry_price - stop_loss
                # 設定 1.5 倍的獲利目標 (Reward)
                take_profit = entry_price + (risk * 1.5)
                
                msg = (
                    f"📈 **發現看漲機會 (Bullish FVG)**\n"
                    f"------------------\n"
                    f"🎯 **建議進場 (Buy Limit)**: ${entry_price:,.2f}\n"
                    f"🛑 **止損價格 (Stop Loss)**: ${stop_loss:,.2f}\n"
                    f"💰 **止盈目標 (Take Profit)**: ${take_profit:,.2f}\n"
                    f"⚖️ **損益比 (R/R Ratio)**: 1:1.5"
                )
                return msg, gap_size
            
        # 2. 判斷看跌 FVG (Bearish)
        # 缺口範圍：[第 n 根的高點] <---> [第 n-2 根的低點]
        elif last_candle["high"] < prev_candle["low"]:
            gap_size = prev_candle["low"] - last_candle["high"]
            gap_percent = gap_size / current_price
            
            if gap_percent > threshold_percent:
                # === 策略計算邏輯 ===
                entry_price = prev_candle["low"]  # 進場點：缺口上緣 (反彈做空)
                stop_loss = prev_candle["high"]   # 止損點：第 n-2 根的高點
                
                risk = stop_loss - entry_price
                take_profit = entry_price - (risk * 1.5)
                
                msg = (
                    f"📉 **發現看跌機會 (Bearish FVG)**\n"
                    f"------------------\n"
                    f"🎯 **建議進場 (Sell Limit)**: ${entry_price:,.2f}\n"
                    f"🛑 **止損價格 (Stop Loss)**: ${stop_loss:,.2f}\n"
                    f"💰 **止盈目標 (Take Profit)**: ${take_profit:,.2f}\n"
                    f"⚖️ **損益比 (R/R Ratio)**: 1:1.5"
                )
                return msg, gap_size
            
        return None, 0

    async def analyze_market(self):
        # 1.獲取資料
        df = await self.fetch_data()
        if df is None:
            return "⚠️ 無法連接到幣安 API，請稍後再試。"

        current_price = df.iloc[-1]["close"]
        
        # 2.計算 EMA (指數移動平均) - 判斷趨勢
        ema_200 = df["close"].ewm(span=200, adjust=False).mean().iloc[-1]
        
        # 判斷趨勢
        trend = "🟢 多頭趨勢" if current_price > ema_200 else "🔴 空頭趨勢"

        # 3.計算 FVG
        fvg_signal, gap_size = self.detect_fvg(df)

        # 4.產生分析報告
        report = (
            f"💰 **BTC 目前價格**: ${current_price:,.2f}\n"
            f"📊 **市場趨勢 (EMA 200)**: {trend}\n"
            f"----------------------\n"
        )
        
        if fvg_signal:
            report += f"⚡ **訊號觸發**: {fvg_signal}\n"
            report += f"📏 **缺口大小**: ${gap_size:.2f}\n"
            report += "💡 **建議**: 價格可能會回補此區域，請留意入場機會。"
        else:
            report += "💤 目前無明顯 FVG 訊號，建議觀望。"
            
        return report

# === 機器人介面區 ===
strategy = StrategyEngine()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    當使用者輸入 /start 時觸發
    """
    user_name = update.effective_user.first_name
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=f"嗨 {user_name}！\nCrypto-TeleBot 啟動成功。\n\n目前的架構：\n✅ AsyncIO 非同步核心\n✅ 策略引擎待命"
    )

async def check_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    當使用者輸入 /check 時觸發，呼叫策略引擎
    """
    await context.bot.send_message(chat_id=update.effective_chat.id, text="🔍 正在掃描市場與計算指標...")
    
    # 呼叫策略引擎
    result = await strategy.analyze_market()
    
    await context.bot.send_message(chat_id=update.effective_chat.id, text=f"📊 分析結果：\n{result}")

# === 主程式入口 ===
if __name__ == '__main__':
    TOKEN = '8130979448:AAEukBJkCdc9EvmsSnGsQyW28R7_X6D_BiI' 
    
    application = ApplicationBuilder().token(TOKEN).build()
    
    # 註冊指令
    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('check', check_price))
    
    print("機器人核心已啟動，正在監聽 Telegram 訊息...")
    application.run_polling()