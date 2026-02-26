"""
Lumina Studio - Statistics Module
Usage statistics functionality
"""

import os
import shutil
from config import OUTPUT_DIR


class Stats:
    """Usage statistics (local counter)"""
    _file = os.path.join(OUTPUT_DIR, "lumina_stats.txt")
    _cache_dirs = [
        os.path.join(OUTPUT_DIR, ".gradio_cache"),
        os.path.join(OUTPUT_DIR, "cache"),
        os.path.join(OUTPUT_DIR, "temp"),
        os.path.join(OUTPUT_DIR, "previews"),
    ]

    @staticmethod
    def increment(key: str) -> int:
        data = Stats._load()
        data[key] = data.get(key, 0) + 1
        Stats._save(data)
        return data[key]

    @staticmethod
    def get_all() -> dict:
        return Stats._load()

    @staticmethod
    def reset_all() -> dict:
        """Reset all counters to zero."""
        data = {"calibrations": 0, "extractions": 0, "conversions": 0}
        Stats._save(data)
        return data

    @staticmethod
    def clear_cache() -> tuple:
        """
        Clear all cache directories.

        Returns:
            tuple: (success_count, failed_items)
        """
        success_count = 0
        failed_items = []

        for cache_dir in Stats._cache_dirs:
            if os.path.exists(cache_dir):
                try:
                    for item in os.listdir(cache_dir):
                        item_path = os.path.join(cache_dir, item)
                        try:
                            if os.path.isfile(item_path):
                                os.remove(item_path)
                            elif os.path.isdir(item_path):
                                shutil.rmtree(item_path)
                            success_count += 1
                        except Exception:
                            failed_items.append(item_path)
                except Exception:
                    pass

        return success_count, failed_items

    @staticmethod
    def get_cache_size() -> int:
        """
        Get total size of cache directories in bytes.

        Returns:
            int: Total size in bytes
        """
        total_size = 0
        for cache_dir in Stats._cache_dirs:
            if os.path.exists(cache_dir):
                try:
                    for dirpath, dirnames, filenames in os.walk(cache_dir):
                        for f in filenames:
                            fp = os.path.join(dirpath, f)
                            if os.path.exists(fp):
                                total_size += os.path.getsize(fp)
                except Exception:
                    pass
        return total_size

    @staticmethod
    def _load() -> dict:
        try:
            with open(Stats._file, 'r') as f:
                lines = f.readlines()
                return {l.split(':')[0]: int(l.split(':')[1]) for l in lines if ':' in l}
        except Exception:
            return {"calibrations": 0, "extractions": 0, "conversions": 0}

    @staticmethod
    def _save(data: dict):
        try:
            with open(Stats._file, 'w') as f:
                for k, v in data.items():
                    f.write(f"{k}:{v}\n")
        except Exception:
            pass
