import threading

DNS_PORT = 53
CACHE_FILE = 'dns_cache.pkl'
SOCKET_TIMEOUT = 2.0

CACHE_LOCK = threading.Lock()
IS_EXITING = threading.Event()

