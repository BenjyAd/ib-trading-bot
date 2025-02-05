from ib_insync import *
import requests
import datetime
import time
import logging

# Global variables
STARTING_CAPITAL = 1000
RESERVE_PERCENTAGE = 0.25
RESERVE_FUND = 0  # This will be tracked in logs but not withdrawn

# Market open/close times for different exchanges
MARKET_TIMES = {
    "NYSE": {"open": (9, 30), "close": (15, 55)},
    "NASDAQ": {"open": (9, 30), "close": (15, 55)},
    "TSX": {"open": (9, 30), "close": (15, 55)},
    "LSE": {"open": (8, 0), "close": (16, 25)},
    "TSE": {"open": (9, 0), "close": (13, 25)},  # Taiwan Stock Exchange
}

# Logging setup
def setup_logging():
    logging.basicConfig(filename='trade_log.txt', level=logging.INFO, format='%(asctime)s - %(message)s')

def log(message):
    print(message)
    logging.info(message)

# Fetch trending stocks
def fetch_trending_stocks(retries=3, delay=5):
    url = "https://apewisdom.io/api/v1.0/filter/all-stocks"
    for attempt in range(retries):
        try:
            response = requests.get(url)
            response.raise_for_status()
            data = response.json()
            stocks = [(item['ticker'], item['exchange']) for item in data.get('results', [])[:10]]
            if not stocks:
                raise ValueError("No stocks received from API")
            return stocks
        except (requests.RequestException, ValueError) as e:
            log(f"API fetch failed ({e}), retrying in {delay} seconds...")
            time.sleep(delay)
    raise Exception("Failed to fetch trending stocks after multiple attempts.")

# Connect to IB
def connect_ib():
    ib = IB()
    for _ in range(3):
        try:
            ib.connect('127.0.0.1', 7497, clientId=1)
            return ib
        except Exception as e:
            log(f"IB connection failed: {e}. Retrying in 5 seconds...")
            time.sleep(5)
    raise Exception("Failed to connect to Interactive Brokers after multiple attempts.")

# Get available funds with reserve
def get_available_funds(ib, reserve_fund):
    account_summary = ib.accountSummary()
    net_liquidation = float(account_summary.loc['NetLiquidation', 'value'])
    return (net_liquidation - reserve_fund) * 0.95

# Get market open/close times dynamically
def get_market_times(exchange):
    return MARKET_TIMES.get(exchange, MARKET_TIMES["NYSE"])  # Default to NYSE if exchange not listed

# Close all positions before starting fresh trades
def close_all_positions(ib):
    positions = ib.positions()
    for pos in positions:
        contract = pos.contract
        order = MarketOrder('SELL', pos.position)
        ib.placeOrder(contract, order)
    log("Closed all open positions.")

# Main function
def main():
    setup_logging()
    ib = connect_ib()
    close_all_positions(ib)
    reserve_fund = 0  # This will accumulate daily

    stocks = fetch_trending_stocks()
    
    # Calculate trading capital
    available_funds = get_available_funds(ib, reserve_fund)
    allocation_per_stock = available_funds / len(stocks)
    positions = []
    
    for stock, exchange in stocks:
        contract = Stock(stock, 'SMART', 'USD')
        ib.qualifyContracts(contract)
        market_data = ib.reqMktData(contract)
        ib.sleep(1)
        market_price = market_data.last if market_data.last else market_data.close
        quantity = int(allocation_per_stock / market_price) if market_price > 0 else 0
        
        if quantity > 0:
            order = MarketOrder('BUY', quantity)
            trade = ib.placeOrder(contract, order)
            ib.sleep(2)
            if trade.orderStatus.status not in ['Filled', 'Submitted']:
                log(f"Order for {contract.symbol} failed: {trade.orderStatus.status}")
            positions.append((contract, quantity, exchange))
    
    # Sell at market close based on exchange times
    total_profit = 0
    for contract, quantity, exchange in positions:
        _, close_time = get_market_times(exchange)
        while datetime.datetime.now().time() < datetime.time(*close_time):
            time.sleep(1)
        
        sell_order = MarketOrder('SELL', quantity)
        trade = ib.placeOrder(contract, sell_order)
        ib.sleep(2)
        if trade.orderStatus.status == 'Filled':
            total_profit += (trade.orderStatus.avgFillPrice - market_price) * quantity
    
    # Calculate and track reserve fund
    daily_reserve = total_profit * RESERVE_PERCENTAGE
    reserve_fund += daily_reserve
    log(f"Daily profit: {total_profit}, Reserve added: {daily_reserve}, Total reserve: {reserve_fund}")
    
    ib.disconnect()
    log("All positions sold. Trading complete.")

if __name__ == "__main__":
    main()
