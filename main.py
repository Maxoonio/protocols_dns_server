import threading
import signal
import sys
import time

from config import IS_EXITING
from cache_persistence import load_cache, save_cache
from DNS_server import DNSServer


def signal_handler(sig, frame):
    signal_name = signal.Signals(sig).name
    print(f"\nПолучен сигнал {signal_name}. Завершение работы...")
    IS_EXITING.set()


def check_exit_input():
    global IS_EXITING
    thread_name = f"Поток_Ввода ({threading.get_ident()})"
    print(f"[{thread_name}] Запущен. Введите 'exit' для остановки сервера.")
    while not IS_EXITING.is_set():
        try:
            inp = input()
            if inp.strip().lower() == 'exit':
                print(f"[{thread_name}] Получена команда 'exit'. Инициирую завершение...")
                IS_EXITING.set()
                break
        except EOFError:
            print(f"[{thread_name}] EOF получен. Поток ввода завершается.")
            break
        except Exception as e:
            if not IS_EXITING.is_set():
                print(f"[{thread_name}] Ошибка: {e}")
            break


if __name__ == '__main__':
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    print("=" * 30)
    print(" Запуск DNS Кэширующего Сервера ")
    print("=" * 30)

    cache = load_cache()

    host_ip = input(" > Укажите IP хоста для прослушивания [0.0.0.0]: ").strip() or '0.0.0.0'
    upstream_server_ip = input(" > Укажите IP вышестоящего DNS сервера [8.8.8.8]: ").strip() or '8.8.8.8'

    print(f"Настройки: Host={host_ip}, Upstream={upstream_server_ip}")
    print("-" * 30)

    dns_server = DNSServer(cache, upstream_server_ip)

    exit_thread = threading.Thread(target=check_exit_input, daemon=True)
    exit_thread.start()

    dns_server.start(host=host_ip)

    print("-" * 30)
    save_cache(cache)
    print("=" * 30)
    print("Программа завершена.")
    print("=" * 30)
    time.sleep(0.5)
