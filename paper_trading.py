import os
import pandas as pd
from ta.momentum import RSIIndicator
from binance.client import Client
from datetime import datetime
import time

# Replace with your Binance Testnet API keys
api_key = os.getenv("BINANCE_API_KEY")
api_secret = os.getenv("BINANCE_API_SECRET")

client = Client(api_key, api_secret, testnet=True)

# Parameters
symbol = "ETHUSDT"  # Trading pair
interval = Client.KLINE_INTERVAL_1MINUTE  # Use 1-minute candlesticks
limit = 100  # Fetch the latest 100 candles
trading_fee = 0.001  # 0.1% fee
trade_log = []
stop_loss_threshold = 0.98  # 2% below the entry price
volatility_threshold = 0.02  # 2% price movement in 1 minute considered volatile

# Initialize variables
entry_price = None  # Track the entry price for stop-loss logic

# Fetch initial testnet account balances
account_info = client.get_account()
balances = {
    balance["asset"]: float(balance["free"]) for balance in account_info["balances"]
}
usdt_balance = balances.get("USDT", 0)  # USDT balance for trading
eth_balance = balances.get("ETH", 0)  # ETH balance for trading

print(f"Initial Testnet Balances: USDT={usdt_balance:.2f}, ETH={eth_balance:.6f}")


# Function to determine optimal parameters dynamically
def determine_dynamic_parameters(df):
    rsi_buy = df["rsi"].quantile(0.25)  # Lower 25% of RSI for buy signal
    rsi_sell = df["rsi"].quantile(0.75)  # Upper 25% of RSI for sell signal
    volume_threshold = df["volume"].median()  # Median volume as threshold
    return rsi_buy, rsi_sell, volume_threshold


try:
    while True:  # Run indefinitely until interrupted
        try:
            # Fetch historical candlestick data
            candlesticks = client.get_klines(
                symbol=symbol, interval=interval, limit=limit
            )
            df = pd.DataFrame(
                candlesticks,
                columns=[
                    "timestamp",
                    "open",
                    "high",
                    "low",
                    "close",
                    "volume",
                    "close_time",
                    "quote_asset_volume",
                    "number_of_trades",
                    "taker_buy_base_asset_volume",
                    "taker_buy_quote_asset_volume",
                    "ignore",
                ],
            )
            df["close"] = df["close"].astype(float)
            df["volume"] = df["volume"].astype(float)

            # Indicators
            rsi = RSIIndicator(close=df["close"], window=14)
            df["rsi"] = rsi.rsi()

            # Dynamically determine RSI and volume thresholds
            rsi_buy, rsi_sell, volume_threshold = determine_dynamic_parameters(df)
            print(
                f"Dynamically determined thresholds - RSI Buy: {rsi_buy:.2f}, RSI Sell: {rsi_sell:.2f}, Volume Threshold: {volume_threshold:.2f}"
            )

            # Check for volatility
            recent_candles = df.tail(3)  # Last 3 candles
            price_change = (
                recent_candles["close"].max() - recent_candles["close"].min()
            ) / recent_candles["close"].min()

            if price_change > volatility_threshold:
                print(
                    f"High volatility detected: {price_change * 100:.2f}%. Skipping trades."
                )
                time.sleep(60)  # Skip this iteration
                continue

            # Generate trading signals
            df["signal"] = 0
            df.loc[
                (df["rsi"] < rsi_buy) & (df["volume"] > volume_threshold), "signal"
            ] = 1  # Buy
            df.loc[
                (df["rsi"] > rsi_sell) & (df["volume"] > volume_threshold), "signal"
            ] = -1  # Sell

            # Check the last row (latest data)
            latest_row = df.iloc[-1]
            timestamp = datetime.fromtimestamp(latest_row["timestamp"] / 1000).strftime(
                "%Y-%m-%d %H:%M:%S"
            )
            price = latest_row["close"]

            print(
                f"Debug: Timestamp={timestamp}, Price={price}, RSI={latest_row['rsi']:.2f}, Volume={latest_row['volume']}"
            )

            # Execute buy/sell logic
            if latest_row["signal"] == 1 and usdt_balance > 0:  # Buy
                eth_to_buy = (usdt_balance * (1 - trading_fee)) / price
                entry_price = price  # Set entry price
                usdt_balance = 0  # Update USDT balance
                eth_balance += eth_to_buy  # Update ETH balance
                trade_log.append((timestamp, "Buy", price, 0))
                print(
                    f"Buy at {price} on {timestamp}. New Balances: USDT={usdt_balance:.2f}, ETH={eth_balance:.6f}"
                )

            elif latest_row["signal"] == -1 and eth_balance > 0:  # Sell
                profit = (price - entry_price) / entry_price
                usdt_balance += eth_balance * price * (1 - trading_fee)
                eth_balance = 0  # Update ETH balance
                entry_price = None  # Reset entry price
                trade_log.append((timestamp, "Sell", price, profit))
                print(
                    f"Sell at {price} on {timestamp} (Profit: {profit * 100:.2f}%). New Balances: USDT={usdt_balance:.2f}, ETH={eth_balance:.6f}"
                )

            # Stop-loss logic
            elif (
                eth_balance > 0
                and entry_price
                and price < entry_price * stop_loss_threshold
            ):
                print(f"Stop-loss triggered. Selling at {price}.")
                usdt_balance += eth_balance * price * (1 - trading_fee)
                eth_balance = 0  # Reset ETH balance
                loss = (price - entry_price) / entry_price
                entry_price = None  # Reset entry price
                trade_log.append((timestamp, "Stop-Loss Sell", price, loss))
                print(
                    f"Stop-loss sell executed. New Balances: USDT={usdt_balance:.2f}, ETH={eth_balance:.6f}"
                )

            time.sleep(60)  # Wait for the next iteration

        except Exception as e:
            print(f"Error: {e}")
            import traceback

            traceback.print_exc()
            time.sleep(60)  # Wait and retry in case of an error

except KeyboardInterrupt:
    print("Bot interrupted by user.")
finally:
    # Save trade log
    trade_df = pd.DataFrame(
        trade_log, columns=["timestamp", "action", "price", "profit"]
    )
    trade_df.to_csv("paper_trading_results.csv", index=False)
    print(f"Trading log saved to 'paper_trading_results.csv'.")
    print(f"Final Balances: USDT={usdt_balance:.2f}, ETH={eth_balance:.6f}")
