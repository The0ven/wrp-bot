import asyncio

# Shared in-process locks for JSON file read-modify-write sections.
CONFIG_LOCK = asyncio.Lock()
PENDING_LOCK = asyncio.Lock()
