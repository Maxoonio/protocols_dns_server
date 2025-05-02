import pickle
import os
from collections import defaultdict

from config import CACHE_FILE, CACHE_LOCK
from cache_logic import CacheEntry


def save_cache(cache):
    print("Сохранение кэша...")
    with CACHE_LOCK:
        cache_to_save = {k: v for k, v in cache.items() if not v.is_empty()}

        if not cache_to_save:
            print("Кэш пуст, файл не сохраняется.")
            if os.path.exists(CACHE_FILE):
                try:
                    os.remove(CACHE_FILE)
                    print(f"Удален старый файл кэша: {CACHE_FILE}")
                except Exception as e:
                    print(f"Не удалось удалить старый файл кэша: {e}")
            return

        try:
            with open(CACHE_FILE, 'wb') as f:
                pickle.dump(cache_to_save, f)
            print(f"Кэш успешно сохранен в {CACHE_FILE} ({len(cache_to_save)} записей)")
        except Exception as e:
            print(f"Ошибка при сохранении кэша: {e}")


def load_cache():
    cache = defaultdict(CacheEntry)
    if not os.path.exists(CACHE_FILE):
        print("Файл кэша не найден. Запуск с пустым кэшем.")
        return cache

    print(f"Загрузка кэша из {CACHE_FILE}...")
    try:
        with open(CACHE_FILE, 'rb') as f:
            loaded_data = pickle.load(f)
            if isinstance(loaded_data, dict):
                cache.update(loaded_data)
                print(f"Кэш успешно загружен ({len(loaded_data)} записей).")
            else:
                print("Ошибка: файл кэша содержит некорректные данные.")
                return defaultdict(CacheEntry)
    except Exception as e:
        print(f"Ошибка при загрузке кэша: {e}. Запуск с пустым кэшем.")
        return defaultdict(CacheEntry)

    print("Очистка просроченных записей из загруженного кэша...")
    keys_to_delete = []
    records_deleted_count = 0
    with CACHE_LOCK:
        for key, cache_entry in list(cache.items()):
            initial_state_empty = cache_entry.is_empty()
            cache_entry.delete_expired_records()
            if not initial_state_empty and cache_entry.is_empty():
                records_deleted_count += 1
                print(f"  Запись для '{key}' полностью просрочена и будет удалена.")
                keys_to_delete.append(key)
            elif cache_entry.is_empty():
                keys_to_delete.append(key)

        for key in keys_to_delete:
            if key in cache:
                del cache[key]

    print(f"Очистка завершена. Удалено {records_deleted_count} полностью просроченных записей.")
    if not cache:
        print("Кэш стал пустым после очистки.")
    return cache


