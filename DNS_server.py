import socket
import threading
import dnslib

from config import DNS_PORT, SOCKET_TIMEOUT, IS_EXITING, CACHE_LOCK
from cache_logic import (
    update_cache_from_response,
    get_info_from_cache,
    CacheEntry,
    remain_ttl
)


class DNSServer:
    def __init__(self, cache, upstream_dns):
        self.cache = cache
        self.upstream_dns = upstream_dns
        self.server_socket = None
        self.host = '0.0.0.0'

    def start(self, host='0.0.0.0'):
        self.host = host
        try:
            self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.server_socket.bind((self.host, DNS_PORT))
            self.server_socket.settimeout(SOCKET_TIMEOUT)
            print(f"DNS сервер запущен на {self.host}:{DNS_PORT}")
            print(f"Вышестоящий DNS сервер: {self.upstream_dns}")

            while not IS_EXITING.is_set():
                try:
                    query_data, client_addr = self.server_socket.recvfrom(4096)
                    handler_thread = threading.Thread(
                        target=self.handle_query,
                        args=(query_data, client_addr),
                        daemon=True
                    )
                    handler_thread.start()
                except socket.timeout:
                    continue
                except Exception as e:
                    print(f"Ошибка в основном цикле сервера (при приеме данных): {e}")

        except OSError as e:
            print(f"Критическая ошибка при запуске сервера на {self.host}:{DNS_PORT}. Порт занят? {e}")
            IS_EXITING.set()
        except Exception as e:
            print(f"Критическая ошибка сервера: {e}")
            IS_EXITING.set()
        finally:
            if self.server_socket:
                self.server_socket.close()
            print("DNS сервер остановлен.")

    def handle_query(self, query_data, client_addr):
        query = None
        try:
            query = dnslib.DNSRecord.parse(query_data)
            qname = str(query.q.qname).lower()
            qtype = query.q.qtype
            qtype_name = dnslib.QTYPE[qtype]

            print(f"[Поток {threading.get_ident()}] Запрос: {qname} ({qtype_name}) от {client_addr}")

            cached_entry = None
            required_data = None
            with CACHE_LOCK:
                if qname in self.cache:
                    cached_entry = self.cache[qname]
                    cached_entry.delete_expired_records()
                    if cached_entry.is_empty():
                        del self.cache[qname]
                        print(
                            f"  [Поток {threading.get_ident()}] Запись для {qname} удалена из кэша (была просрочена).")
                        cached_entry = None
                    else:
                        required_data = get_info_from_cache(cached_entry, qtype)

            if required_data:
                if remain_ttl(required_data) > 0:
                    print(f"  [Поток {threading.get_ident()}] Ответ для {qname} ({qtype_name}) найден в кэше.")
                    response = self._build_response_from_cache(query, required_data)
                    self.server_socket.sendto(response.pack(), client_addr)
                    return
                else:
                    print(
                        f"  [Поток {threading.get_ident()}] Кэш для {qname} ({qtype_name}) просрочен (повторная проверка).")
                    with CACHE_LOCK:
                        if qname in self.cache:
                            entry_to_check = self.cache[qname]
                            entry_to_check.delete_expired_records()
                            if entry_to_check.is_empty():
                                del self.cache[qname]

            print(
                f"  [Поток {threading.get_ident()}] Запрос для {qname} ({qtype_name}) перенаправляется на {self.upstream_dns}")
            response_data = self._forward_query(query_data)

            if response_data:
                self.server_socket.sendto(response_data, client_addr)
                print(f"  [Поток {threading.get_ident()}] Ответ от {self.upstream_dns} отправлен клиенту {client_addr}")

                try:
                    dns_response = dnslib.DNSRecord.parse(response_data)
                    if dns_response.header.rcode == dnslib.RCODE.NOERROR:
                        update_cache_from_response(dns_response, self.cache)
                        print(f"  [Поток {threading.get_ident()}] Кэш обновлен для записей из ответа по {qname}")
                    else:
                        print(
                            f"  [Поток {threading.get_ident()}] Ответ от upstream с ошибкой ({dnslib.RCODE[dns_response.header.rcode]}), кэш не обновлен.")

                except Exception as e:
                    print(
                        f"  [Поток {threading.get_ident()}] Ошибка парсинга ответа от {self.upstream_dns} или обновления кэша: {e}")
            else:
                print(f"  [Поток {threading.get_ident()}] Не получен ответ от {self.upstream_dns} для {qname}")
                error_response = query.reply()
                error_response.header.rcode = dnslib.RCODE.SERVFAIL
                self.server_socket.sendto(error_response.pack(), client_addr)

        except dnslib.DNSError as e:
            print(f"  [Поток {threading.get_ident()}] Ошибка обработки DNS запроса от {client_addr}: {e}")
            if query:
                error_response = dnslib.DNSRecord(
                    dnslib.DNSHeader(id=query.header.id, qr=1, aa=1, ra=1, rcode=dnslib.RCODE.FORMERR))
                try:
                    self.server_socket.sendto(error_response.pack(), client_addr)
                except Exception as send_err:
                    print(f"  [Поток {threading.get_ident()}] Не удалось отправить FORMERR клиенту: {send_err}")
        except Exception as e:
            print(f"Неожиданная ошибка при обработке запроса от {client_addr} в потоке {threading.get_ident()}: {e}")
            if query:
                try:
                    error_response = query.reply()
                    error_response.header.rcode = dnslib.RCODE.SERVFAIL
                    self.server_socket.sendto(error_response.pack(), client_addr)
                except Exception as send_err:
                    print(
                        f"  [Поток {threading.get_ident()}] Не удалось отправить SERVFAIL клиенту после ошибки: {send_err}")

    def _build_response_from_cache(self, query, cached_data):
        response = query.reply()
        q_type = query.q.qtype
        q_name = query.q.qname
        ttl = remain_ttl(cached_data)

        if ttl <= 0:
            response.header.rcode = dnslib.RCODE.NXDOMAIN
            return response

        try:
            if q_type == dnslib.QTYPE.A and cached_data.objects:
                for ip in cached_data.objects:
                    response.add_answer(dnslib.RR(q_name, q_type, ttl=ttl, rdata=dnslib.A(ip)))
            elif q_type == dnslib.QTYPE.AAAA and cached_data.objects:
                for ip in cached_data.objects:
                    response.add_answer(dnslib.RR(q_name, q_type, ttl=ttl, rdata=dnslib.AAAA(ip)))
            elif q_type == dnslib.QTYPE.NS and cached_data.objects:
                for ns_name in cached_data.objects:
                    response.add_answer(dnslib.RR(q_name, q_type, ttl=ttl, rdata=dnslib.NS(ns_name)))
            elif q_type == dnslib.QTYPE.PTR and cached_data.name:
                response.add_answer(dnslib.RR(q_name, q_type, ttl=ttl, rdata=dnslib.PTR(cached_data.name)))
            else:
                response.header.rcode = dnslib.RCODE.NXDOMAIN


        except Exception as e:
            print(f"Ошибка при сборке ответа из кэша для {q_name} ({dnslib.QTYPE[q_type]}): {e}")
            response.header.rcode = dnslib.RCODE.SERVFAIL

        return response

    def _forward_query(self, query_data):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as upstream_sock:
                upstream_sock.settimeout(SOCKET_TIMEOUT)
                upstream_sock.sendto(query_data, (self.upstream_dns, DNS_PORT))
                response_data, _ = upstream_sock.recvfrom(4096)
                return response_data
        except socket.timeout:
            print(f"Таймаут при ожидании ответа от {self.upstream_dns}")
            return None
        except Exception as e:
            print(f"Ошибка при перенаправлении запроса на {self.upstream_dns}: {e}")
            return None
