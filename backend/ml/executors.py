"""Shared thread pools for CPU-heavy simulation and embedding work."""

from concurrent.futures import ThreadPoolExecutor

SIM_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="mc-sim")
EMBED_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="embed")

CF_SIM_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="cf-sim")

IO_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="blocking-io")
