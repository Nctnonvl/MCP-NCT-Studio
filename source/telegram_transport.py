"""Thread-local Telegram HTTPS connections. Never retry a possibly sent action."""
import logging
import threading
import httpx

# Telegram puts the bot token in the URL. HTTP request loggers must not log it.
logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('httpcore').setLevel(logging.WARNING)
_clients=threading.local()

def request_telegram(token,method,payload,timeout=30):
    client=getattr(_clients,'client',None)
    if client is None:
        client=httpx.Client(timeout=timeout,limits=httpx.Limits(max_connections=2,max_keepalive_connections=2,keepalive_expiry=60))
        _clients.client=client
    try:
        response=client.post('https://api.telegram.org/bot'+token+'/'+method,json=payload,timeout=timeout)
        result=response.json()
        if not isinstance(result,dict):raise ValueError()
        if not result.get('ok'):
            description=str(result.get('description','Lỗi Telegram')).replace(token,'[TOKEN]')
            raise RuntimeError(description[:400])
        response.raise_for_status()
        return result.get('result')
    except (httpx.HTTPError,ValueError):
        # Discard a broken connection; the NEXT action creates a new one.
        # Do not re-send this request: Telegram may have already processed it.
        client.close();_clients.client=None
        raise RuntimeError('Không kết nối được Telegram hoặc hết thời gian chờ. Chưa tự gửi lại thao tác này.') from None
