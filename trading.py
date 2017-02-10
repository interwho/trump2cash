# -*- coding: utf-8 -*-

from datetime import datetime
from datetime import timedelta
from dateutil import parser
from simplejson import loads
from oauth2 import Client
from os import getenv
from os import path
from pytz import timezone
from pytz import utc
import json
import __builtin__

from logs import Logs

# Base URL for retrieving oAuth tokens.
QUESTRADE_AUTH_API_URL = "https://login.questrade.com/oauth2/token?grant_type=refresh_token&refresh_token=%s"

# Read the Questrade account number from the environment variable.
QUESTRADE_ACCOUNT_NUMBER = getenv("QUESTRADE_ACCOUNT_NUMBER")

# Only allow actual trades when the environment variable confirms it.
USE_REAL_MONEY = getenv("USE_REAL_MONEY") == "YES"

# The amount of cash in dollars to hold from being spent.
CASH_HOLD = 1000

# Blacklisted stock ticker symbols, e.g. to avoid insider trading.
TICKER_BLACKLIST = []

# We're using NYSE and NASDAQ, which are both in the eastern timezone.
MARKET_TIMEZONE = timezone("US/Eastern")

# TODO: Use a comprehensive list.
# A list of days where the markets are closed apart from weekends.
TRADING_HOLIDAYS = [MARKET_TIMEZONE.localize(date) for date in [
    datetime(2017, 1, 2)]]

# The filename pattern for historical market data.
MARKET_DATA_FILE = "market_data/%s_%s.txt"


class Trading:
    """A helper for making stock trades."""

    def __init__(self, logs_to_cloud):
        self.logs = Logs(name="trading", to_cloud=logs_to_cloud)

        # Get initial API keys from Questrade
        url = QUESTRADE_AUTH_API_URL % __builtin__.QUESTRADE_REFRESH_TOKEN
        method = "GET"
        body = ""
        headers = None
        client = Client(None, None)

        self.logs.debug("Questrade request: %s %s %s %s" % (url, method, body, headers))
        response, content = client.request(url, method=method, body=body, headers=headers)
        self.logs.debug("Questrade response: %s %s" % (response, content))

        try:
            response = loads(content)
            self.access_token = response['access_token']
            self.api_server = response['api_server']
            self.expires_in = datetime.now() + datetime.timedelta(0, response['expires_in'])
            __builtin__.QUESTRADE_REFRESH_TOKEN = response['refresh_token']
            self.token_type = response['token_type']

        except ValueError:
            self.logs.error("Failed to retrieve initial API tokens: %s" % content)

    def refresh_tokens(self):
        """Refreshes Questrade's access tokens. Must be run before expires_in."""
        url = QUESTRADE_AUTH_API_URL % __builtin__.QUESTRADE_REFRESH_TOKEN
        method = "GET"
        body = ""
        headers = None
        client = Client(None, None)

        self.logs.debug("Questrade request: %s %s %s %s" % (url, method, body, headers))
        response, content = client.request(url, method=method, body=body, headers=headers)
        self.logs.debug("Questrade response: %s %s" % (response, content))

        try:
            response = loads(content)
            self.access_token = response['access_token']
            self.api_server = response['api_server']
            self.expires_in = datetime.now() + datetime.timedelta(0, response['expires_in'])
            __builtin__.QUESTRADE_REFRESH_TOKEN = response['refresh_token']
            self.token_type = response['token_type']

        except ValueError:
            self.logs.error("Failed to retrieve new API tokens: %s" % content)

    def make_trades(self, companies):
        """Executes trades for the specified companies based on sentiment."""

        # Determine whether the markets are open.
        market_status = self.get_market_status()
        if not market_status:
            self.logs.error("Not trading without market status.")
            return False

        # Filter for any strategies resulting in trades.
        actionable_strategies = []
        market_status = self.get_market_status()
        for company in companies:
            strategy = self.get_strategy(company, market_status)
            if strategy["action"] != "hold":
                actionable_strategies.append(strategy)
            else:
                self.logs.warn("Dropping strategy: %s" % strategy)

        if not actionable_strategies:
            self.logs.warn("No actionable strategies for trading.")
            return False

        # Calculate the budget per strategy.
        balance = self.get_balance()
        budget = self.get_budget(balance, len(actionable_strategies))

        if not budget:
            self.logs.warn("No budget for trading: %s %s %s" %
                           (budget, balance, actionable_strategies))
            return False

        self.logs.debug("Using budget: %s x $%s" %
                        (len(actionable_strategies), budget))

        # Handle trades for each strategy.
        success = True
        for strategy in actionable_strategies:
            ticker = strategy["ticker"]
            action = strategy["action"]

            # TODO: Use limits for orders.
            # Execute the strategy.
            if action == "bull":
                self.logs.debug("Bull: %s %s" % (ticker, budget))
                success = success and self.bull(ticker, budget)
            elif action == "bear":
                self.logs.debug("Bear: %s %s" % (ticker, budget))
                success = success and self.bear(ticker, budget)
            else:
                self.logs.error("Unknown strategy: %s" % strategy)

        return success

    def get_strategy(self, company, market_status):
        """Determines the strategy for trading a company based on sentiment and
        market status.
        """

        ticker = company["ticker"]
        sentiment = company["sentiment"]

        strategy = {}
        strategy["name"] = company["name"]
        if "root" in company:
            strategy["root"] = company["root"]
        strategy["sentiment"] = company["sentiment"]
        strategy["ticker"] = ticker
        strategy["exchange"] = company["exchange"]

        # Don't do anything with blacklisted stocks.
        if ticker in TICKER_BLACKLIST:
            strategy["action"] = "hold"
            strategy["reason"] = "blacklist"
            return strategy

        # TODO: Figure out some strategy for the markets closed case.
        # Don't trade unless the markets are open or are about to open.
        if market_status != "open" and market_status != "pre":
            strategy["action"] = "hold"
            strategy["reason"] = "market closed"
            return strategy

        # Can't trade without sentiment.
        if sentiment == 0:
            strategy["action"] = "hold"
            strategy["reason"] = "neutral sentiment"
            return strategy

        # Determine bull or bear based on sentiment direction.
        if sentiment > 0:
            strategy["action"] = "bull"
            strategy["reason"] = "positive sentiment"
            return strategy
        else:  # sentiment < 0
            strategy["action"] = "bear"
            strategy["reason"] = "negative sentiment"
            return strategy

    def get_budget(self, balance, num_strategies):
        """Calculates the budget per company based on the available balance."""

        if num_strategies <= 0:
            self.logs.warn("No budget without strategies.")
            return 0.0
        return round(max(0.0, balance - CASH_HOLD) / num_strategies, 2)

    def get_market_status(self):
        """Finds out whether the markets are open right now."""

        clock_url = self.api_server % "v1/time"
        response = self.make_request(url=clock_url)

        if not response or "time" not in response:
            self.logs.error("Missing clock response: %s" % response)
            return None

        clock_response = response["time"]
        timestamp = parser.parse(clock_response)

        if not self.is_trading_day(timestamp):
            return "closed"

        # Calculate the market hours for the given day. These are the same for NYSE
        # and NASDAQ and include Questrade's extended hours. (http://help.questrade.com/how-to/frequently-asked-questions-
        # (faqs)/self-directed-trading/learning-trading-basics/when-are-the-stock-markets-open-and-what-are-pre--and-post-market-hours-)
        pre_time = timestamp.replace(hour=7, minute=30)
        open_time = timestamp.replace(hour=9, minute=30)
        close_time = timestamp.replace(hour=16)
        after_time = timestamp.replace(hour=17, minute=30)

        # Return the market status for each bucket.
        if timestamp >= pre_time and timestamp < open_time:
            current = "pre"
        elif timestamp >= open_time and timestamp < close_time:
            current = "open"
        elif timestamp >= close_time and timestamp < after_time:
            current = "after"
        else:
            current = "closed"

        self.logs.debug("Current market status: %s" % current)
        return current

    def get_historical_prices(self, ticker, timestamp, depth=0):
        """Finds the last price at or before a timestamp and at EOD."""

        # Limit the recursion depth to two weeks.
        if depth >= 14:
            self.logs.warn("Limiting recursion.")
            return None

        # Start with today's quotes.
        quotes = self.get_day_quotes(ticker, timestamp)
        if not quotes:
            self.logs.warn("No quotes for day: %s" % timestamp)
            # Use the end of the previous trading day and retry recursively.
            timestamp_eod = timestamp.replace(hour=15, minute=59, second=59)
            previous_day = self.get_previous_day(timestamp_eod)
            return self.get_historical_prices(ticker, previous_day,
                                              depth=depth + 1)

        # Depending on where we land relative to the trading day, pick the
        # right quote and EOD quote.
        first_quote = quotes[0]
        first_quote_time = first_quote["time"]
        last_quote = quotes[-1]
        last_quote_time = last_quote["time"]
        if timestamp < first_quote_time:
            self.logs.debug("Using previous quote.")
            previous_day = self.get_previous_day(timestamp)
            previous_quotes = self.get_day_quotes(ticker, previous_day)
            if not previous_quotes:
                self.logs.error("No quotes for previous day: %s" %
                                previous_day)
                return None
            quote_at = previous_quotes[-1]
            quote_eod = last_quote
        elif timestamp >= first_quote_time and timestamp <= last_quote_time:
            self.logs.debug("Using closest quote.")
            # Walk through the quotes unitl we stepped over the timestamp.
            previous_quote = first_quote
            for quote in quotes:
                quote_time = quote["time"]
                if quote_time > timestamp:
                    break
                previous_quote = quote
            quote_at = previous_quote
            quote_eod = last_quote
        else:  # timestamp > last_quote_time
            self.logs.debug("Using last quote.")
            quote_at = last_quote
            next_day = self.get_next_day(timestamp)
            next_quotes = self.get_day_quotes(ticker, next_day)
            if not next_quotes:
                self.logs.error("No quotes for next day: %s" % next_day)
                return None
            quote_eod = next_quotes[-1]

        self.logs.debug("Using quotes: %s %s" % (quote_at, quote_eod))
        return {"at": quote_at["price"], "eod": quote_eod["price"]}

    def get_day_quotes(self, ticker, timestamp):
        """Collects all quotes from the day of the market timestamp."""

        # The timestamp is expected in market time.
        day = timestamp.strftime("%Y%m%d")
        filename = MARKET_DATA_FILE % (ticker, day)

        if not path.isfile(filename):
            self.logs.error("Day quotes not on file for: %s %s" %
                            (ticker, timestamp))
            return None

        quotes_file = open(filename, "r")
        try:
            lines = quotes_file.readlines()
            quotes = []

            # Skip the header line, then read the quotes.
            for line in lines[1:]:
                columns = line.split(",")

                market_time_str = columns[1]
                try:
                    market_time = MARKET_TIMEZONE.localize(datetime.strptime(
                        market_time_str, "%Y%m%d%H%M"))
                except ValueError:
                    self.logs.error("Failed to decode market time: %s" %
                                    market_time_str)
                    return None

                price_str = columns[2]
                try:
                    price = float(price_str)
                except ValueError:
                    self.logs.error("Failed to decode price: %s" % price_str)
                    return None

                quote = {"time": market_time, "price": price}
                quotes.append(quote)

            return quotes
        except IOError as exception:
            self.logs.error("Failed to read quotes cache file: %s" % exception)
            return None
        finally:
            quotes_file.close()

    def is_trading_day(self, timestamp):
        """Tests whether markets are open on a given day."""

        day = timestamp.replace(hour=0, minute=0, second=0)

        # Markets are closed on holidays.
        if day in TRADING_HOLIDAYS:
            self.logs.debug("Identified holiday: %s" % timestamp)
            return False

        # Markets are closed on weekends.
        if day.weekday() in [5, 6]:
            self.logs.debug("Identified weekend: %s" % timestamp)
            return False

        # Otherwise markets are open.
        return True

    def get_previous_day(self, timestamp):
        """Finds the previous trading day."""

        previous_day = timestamp - timedelta(days=1)

        # Walk backwards until we hit a trading day.
        while not self.is_trading_day(previous_day):
            previous_day -= timedelta(days=1)

        self.logs.debug("Previous trading day for %s: %s" %
                        (timestamp, previous_day))
        return previous_day

    def get_next_day(self, timestamp):
        """Finds the next trading day."""

        next_day = timestamp + timedelta(days=1)

        # Walk forward until we hit a trading day.
        while not self.is_trading_day(next_day):
            next_day += timedelta(days=1)

        self.logs.debug("Next trading day for %s: %s" %
                        (timestamp, next_day))
        return next_day

    def utc_to_market_time(self, timestamp):
        """Converts a UTC timestamp to local market time."""

        utc_time = utc.localize(timestamp)
        market_time = utc_time.astimezone(MARKET_TIMEZONE)

        return market_time

    def market_time_to_utc(self, timestamp):
        """Converts a timestamp in local market time to UTC."""

        market_time = MARKET_TIMEZONE.localize(timestamp)
        utc_time = market_time.astimezone(utc)

        return utc_time

    def as_market_time(self, year, month, day, hour=0, minute=0, second=0):
        """Creates a timestamp in market time."""

        market_time = datetime(year, month, day, hour, minute, second)
        return MARKET_TIMEZONE.localize(market_time)

    def make_request(self, url, method="GET", body="", headers=None):
        """Makes a request to the Questrade API."""

        client = Client(None, None)
        if headers is None:
            headers = {'Authorization': ("%s %s" % (self.token_type, self.access_token))}

        self.logs.debug("Questrade request: %s %s %s %s" %
                        (url, method, body, headers))
        response, content = client.request(url, method=method, body=body,
                                           headers=headers)
        self.logs.debug("Questrade response: %s %s" % (response, content))

        try:
            return loads(content)
        except ValueError:
            self.logs.error("Failed to decode JSON response: %s" % content)
            return None

    def get_balance(self):
        """Finds the cash balance in US dollars available to spend."""

        balances_url = self.api_server % ("v1/accounts/%s/balances" % QUESTRADE_ACCOUNT_NUMBER)
        response = self.make_request(url=balances_url)

        if not response or "perCurrencyBalances" not in response:
            self.logs.error("Missing balances response: %s" % response)
            return 0.0

        balances = response["perCurrencyBalances"]
        for i in balances:
            if i['currency'] == "USD":
                balances = i
                break

        if "cash" not in balances:
            self.logs.error("Malformed balance response: %s" % balances)
            return 0.0

        money = balances["cash"]
        try:
            cash = float(money)
            return cash
        except ValueError:
            self.logs.error("Malformed number in response: %s" % money)
            return 0.0

    def get_ticker_symbol_id(self, ticker):
        """Finds the Questrade symbol_id for the specified ticker"""

        symbols_url = self.api_server % "v1/symbols/search"
        symbols_url += "?prefix=%s" % ticker

        response = self.make_request(url=symbols_url)

        if not response or "symbols" not in response:
            self.logs.error("Missing quotes response for %s: %s" %
                            (ticker, response))
            return None

        symbols = response["symbols"]
        symbol_id = None
        for i in symbols:
            if ((i['currency'] == "USD") and
                    (i['symbol'] == ticker) and
                    (i['securityType'] == "Stock")):
                symbol_id = i['symbolId']
                break

        if symbol_id is None:
            self.logs.error("Ticker not found for %s: %s" %
                            (ticker, symbols))
            return None

        return symbol_id

    def get_last_price(self, ticker):
        """Finds the last trade price for the specified stock."""

        symbol_id = self.get_ticker_symbol_id(ticker)
        if symbol_id is None:
            self.logs.error("Ticker not found for %s: stack" % ticker)
            return None

        quotes_url = self.api_server % "v1/markets/quotes/%s" % symbol_id

        response = self.make_request(url=quotes_url)

        if not response or "quotes" not in response:
            self.logs.error("Missing quotes response for %s: %s" %
                            (ticker, response))
            return None

        quote = response["quotes"][0]
        if "lastTradePrice" not in quote:
            self.logs.error("Malformed quote for %s: %s" % (ticker, quote))
            return None

        # Halt, Volume, and Market Cap Safeguards
        if quote["isHalted"]:
            self.logs.error("Trading halt active for %s: %s" %
                            (ticker, response))
            return None

        details_url = self.api_server % "v1/symbols/%s" % symbol_id

        details_response = self.make_request(url=details_url)

        if not details_response or "symbols" not in details_response:
            self.logs.error("Missing detailed quotes response for %s: %s" %
                            (ticker, details_response))
            return None

        details = details_response['symbols'][0]
        if ("marketCap" not in details_response) or ("averageVol3Months" not in details_response):
            self.logs.error("Malformed detailed quotes response for %s: %s" %
                            (ticker, details_response))
            return None

        if details['marketCap'] < 1000000000:
            self.logs.error("Market cap too low (under 1B) for %s: %s" %
                            (ticker, details_response))
            return None

        if details['averageVol3Months'] < 250000:
            self.logs.error("Volume too low (under 250k) for %s: %s" %
                            (ticker, details_response))
            return None

        self.logs.debug("Quote for %s: %s" % (ticker, quote))

        try:
            last = float(quote["lastTradePrice"])
        except ValueError:
            self.logs.error("Malformed last for %s: %s" %
                            (ticker, quote["lastTradePrice"]))
            return None

        if last > 1:    # Prevent us from playing with penny stocks (under $1)
            return last
        else:
            self.logs.error("Zero quote for: %s" % ticker)
            return None

    def get_order_url(self):
        """Gets the Questrade URL for placing orders."""

        url_path = "v1/accounts/%s/orders" % QUESTRADE_ACCOUNT_NUMBER
        if not USE_REAL_MONEY:
            url_path += "/impact"
        return self.api_server % url_path

    def get_quantity(self, ticker, budget):
        """Calculates the quantity of a stock based on the current market price
        and a maximum budget.
        """

        # Calculate the quantity based on the current price and the budget.
        price = self.get_last_price(ticker)
        if not price:
            self.logs.error("Failed to determine price for: %s" % ticker)
            return None

        # Use maximum possible quantity within the budget.
        quantity = int(budget // price)
        self.logs.debug("Determined quantity %s for %s at $%s within $%s." %
                        (quantity, ticker, price, budget))

        # If quantity is too low we can't buy.
        if quantity <= 0:
            return None

        return quantity

    def bull(self, ticker, budget):
        """Executes the bullish strategy on the specified stock within the
        specified budget: Buy now at market rate.
        """

        # Calculate the quantity.
        quantity = self.get_quantity(ticker, budget)
        if not quantity:
            self.logs.warn("Not trading without quantity.")
            return False

        # Buy the stock now.
        if not self.make_order_request(ticker, quantity):
            return False

        return True

    def bear(self, ticker, budget):
        """Executes the bearish strategy on the specified stock within the
        specified budget: Sell short at market rate.
        """

        # Calculate the quantity.
        quantity = -1 * self.get_quantity(ticker, budget)
        if not quantity:
            self.logs.warn("Not trading without quantity.")
            return False

        # Short the stock now.
        if not self.make_order_request(ticker, quantity):
            return False

        return True

    def make_order_request(self, ticker, quantity):
        """Executes an order defined by ticker and quantity and verifies the response."""

        if quantity > 0 :
            action = "Buy"
        elif quantity < 0:
            action = "Sell"
            quantity *= -1
        else:
            self.logs.error("Cannot place order for 0 shares: %s %s" % (ticker, quantity))
            return False

        # Create the order
        data = dict()
        data['symbolId'] = self.get_ticker_symbol_id(ticker)
        data['quantity'] = quantity
        data['IcebergQuantity'] = 1
        data['orderType'] = "Market"
        data['action'] = action
        data['timeInForce'] = "Day"
        data['primaryRoute'] = "AUTO"
        data['secondaryRoute'] = "AUTO"
        body = json.dumps(data)

        response = self.make_request(url=self.get_order_url(), method="POST", body=body)

        # Check if there is a response.
        if not response or "orderId" not in response:
            self.logs.error("Order request failed: %s %s" % (body, response))
            return False

        # Check if the response is in the expected format.
        order_response = response["orders"]
        if not order_response or "id" not in order_response:
            self.logs.error("Malformed order response: %s" % order_response)
            return False

        self.logs.debug("Order for %s: %s" % (ticker, response))

        return True

    def get_current_positions(self):
        """Gets all current positions on the account"""

        positions_url = self.api_server % ("v1/accounts/%s/positions" % QUESTRADE_ACCOUNT_NUMBER)
        response = self.make_request(url=positions_url)

        if not response or "positions" not in response:
            self.logs.error("Missing positions response: %s" % response)
            return []

        positions = response["positions"]
        current_positions = []
        for i in positions:
            current_positions.append({"symbol": i["symbol"], "symbolId": i["symbolId"], "openQuantity": i["openQuantity"]})

        return current_positions

    def close_out_all_positions(self):
        """Closes out all active positions on the account 15 minutes before market close"""

        clock_url = self.api_server % "v1/time"
        response = self.make_request(url=clock_url)

        if not response or "time" not in response:
            self.logs.error("Missing clock response: %s" % response)
            return None

        clock_response = response["time"]
        timestamp = parser.parse(clock_response)

        if not self.is_trading_day(timestamp):
            return None

        sell_time = timestamp.replace(hour=15, minute=45)
        close_time = timestamp.replace(hour=16)

        # Short circuit if the market doesn't close within 15 minutes
        if timestamp < sell_time or timestamp > close_time:
            return None

        current_positions = self.get_current_positions()

        for i in current_positions:
            self.make_order_request(i["symbol"], (-1 * i["openQuantity"]))
