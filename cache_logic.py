import time
import dnslib
from collections import defaultdict

from config import CACHE_LOCK


class DNSObject:
    def __init__(self, ttl, name=None):
        self.name = name
        self.init_time = time.time()
        self.ttl = ttl
        self.objects = []

    def __repr__(self):
        return f"DNSObject(ttl={self.ttl}, name={self.name}, objects={self.objects}, init_time={self.init_time})"


class CacheEntry:
    def __init__(self):
        self.a = None
        self.aaaa = None
        self.ns = None
        self.ptr = None

    def delete_expired_records(self):
        if self.a is not None and remain_ttl(self.a) == 0:
            self.a = None
        if self.aaaa is not None and remain_ttl(self.aaaa) == 0:
            self.aaaa = None
        if self.ns is not None and remain_ttl(self.ns) == 0:
            self.ns = None
        if self.ptr is not None and remain_ttl(self.ptr) == 0:
            self.ptr = None

    def is_empty(self):
        return self.a is None and self.aaaa is None and self.ns is None and self.ptr is None

    def __repr__(self):
        return f"CacheEntry(A={self.a}, AAAA={self.aaaa}, NS={self.ns}, PTR={self.ptr})"


def remain_ttl(dns_object):
    if not dns_object:
        return 0
    passed_time = int(time.time() - dns_object.init_time)
    return max(0, dns_object.ttl - passed_time)


def _update_a(new_record, cache_entry):
    if not isinstance(new_record.rdata, dnslib.A): return
    if cache_entry.a is None or remain_ttl(cache_entry.a) == 0:
        cache_entry.a = DNSObject(new_record.ttl)
    cache_entry.a.ttl = max(cache_entry.a.ttl, new_record.ttl)
    ip_addr = str(new_record.rdata.data)
    if ip_addr not in cache_entry.a.objects:
        cache_entry.a.objects.append(ip_addr)
    cache_entry.a.init_time = time.time()


def _update_aaaa(new_record, cache_entry):
    if not isinstance(new_record.rdata, dnslib.AAAA): return
    if cache_entry.aaaa is None or remain_ttl(cache_entry.aaaa) == 0:
        cache_entry.aaaa = DNSObject(new_record.ttl)
    cache_entry.aaaa.ttl = max(cache_entry.aaaa.ttl, new_record.ttl)
    ip_addr = str(new_record.rdata.data)
    if ip_addr not in cache_entry.aaaa.objects:
        cache_entry.aaaa.objects.append(ip_addr)
    cache_entry.aaaa.init_time = time.time()


def _update_ns(new_record, cache_entry):
    if not isinstance(new_record.rdata, dnslib.NS): return
    if cache_entry.ns is None or remain_ttl(cache_entry.ns) == 0:
        cache_entry.ns = DNSObject(new_record.ttl)
    cache_entry.ns.ttl = max(cache_entry.ns.ttl, new_record.ttl)
    ns_name = str(new_record.rdata.label)
    if ns_name not in cache_entry.ns.objects:
        cache_entry.ns.objects.append(ns_name)
    cache_entry.ns.init_time = time.time()


def _update_ptr(new_record, cache_entry):
    if not isinstance(new_record.rdata, dnslib.PTR): return
    ptr_name = str(new_record.rdata.label)
    cache_entry.ptr = DNSObject(new_record.ttl, name=ptr_name)


def update_cache_from_response(dns_response, cache):
    all_records = dns_response.rr + dns_response.ar + dns_response.auth
    if not all_records:
        return

    with CACHE_LOCK:
        for record in all_records:
            try:
                record_name = str(record.rname).lower()
                record_type = record.rtype
                cache_entry = cache[record_name]

                if record_type == dnslib.QTYPE.A:
                    _update_a(record, cache_entry)
                elif record_type == dnslib.QTYPE.AAAA:
                    _update_aaaa(record, cache_entry)
                elif record_type == dnslib.QTYPE.NS:
                    _update_ns(record, cache_entry)
                elif record_type == dnslib.QTYPE.PTR:
                    _update_ptr(record, cache_entry)
            except Exception as e:
                print(f"Ошибка при обработке записи {record}: {e}")


def get_info_from_cache(cache_entry, query_type):
    if query_type == dnslib.QTYPE.A:
        return cache_entry.a
    elif query_type == dnslib.QTYPE.AAAA:
        return cache_entry.aaaa
    elif query_type == dnslib.QTYPE.NS:
        return cache_entry.ns
    elif query_type == dnslib.QTYPE.PTR:
        return cache_entry.ptr
    return None


