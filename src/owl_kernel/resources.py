"""Best-effort host resource snapshot. Never claims an 8GB machine is unlimited."""

from __future__ import annotations

import os
from pathlib import Path


def snapshot(min_free_mb: int = 256) -> dict:
    info: dict = {"ok": True, "cpu_count": os.cpu_count() or 1}
    try:
        import psutil  # optional

        vm = psutil.virtual_memory()
        info["ram_available_mb"] = int(vm.available / 1024 / 1024)
        info["ram_total_mb"] = int(vm.total / 1024 / 1024)
        if info["ram_available_mb"] < min_free_mb:
            info["ok"] = False
            info["reason"] = "low_memory"
    except Exception:
        # /proc/meminfo on Linux
        mem = Path("/proc/meminfo")
        if mem.exists():
            kv = {}
            for line in mem.read_text().splitlines():
                k, _, rest = line.partition(":")
                kv[k] = rest.strip()
            def mb(key: str) -> int:
                return int(kv.get(key, "0 kB").split()[0]) // 1024

            info["ram_available_mb"] = mb("MemAvailable")
            info["ram_total_mb"] = mb("MemTotal")
            if info["ram_available_mb"] < min_free_mb:
                info["ok"] = False
                info["reason"] = "low_memory"
        else:
            info["ram_available_mb"] = None
    return info
