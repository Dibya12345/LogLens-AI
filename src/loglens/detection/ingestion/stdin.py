import asyncio
import sys
from collections.abc import AsyncIterator


class AsyncStdinReader:
    async def __aiter__(self) -> AsyncIterator[str]:
        loop = asyncio.get_running_loop()
        while True:
            line = await loop.run_in_executor(None, sys.stdin.readline)
            if not line:
                break
            yield line.rstrip("\r\n")
