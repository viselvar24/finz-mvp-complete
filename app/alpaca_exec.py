import os
try:
    from alpaca_trade_api.rest import REST
except Exception:
    REST = None

ALPACA_KEY = os.getenv('ALPACA_API_KEY')
ALPACA_SECRET = os.getenv('ALPACA_SECRET')
BASE = 'https://paper-api.alpaca.markets'

def get_client():
    if REST is None or not ALPACA_KEY:
        return None
    return REST(ALPACA_KEY, ALPACA_SECRET, BASE)

def place_order_buy(symbol, qty):
    client = get_client()
    if client is None:
        return {'error':'alpaca-not-configured'}
    return client.submit_order(symbol=symbol, qty=qty, side='buy', type='market', time_in_force='gtc').__dict__

def place_order_sell(symbol, qty):
    client = get_client()
    if client is None:
        return {'error':'alpaca-not-configured'}
    return client.submit_order(symbol=symbol, qty=qty, side='sell', type='market', time_in_force='gtc').__dict__
