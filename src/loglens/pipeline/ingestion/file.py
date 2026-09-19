from collections.abc import AsyncIterator

import aiofiles

CHUNK_LINES = 1000


class AsyncFileReader:
    def __init__(self, path: str):
        self.path = path

    async def __aiter__(self) -> AsyncIterator[str]:
        async with aiofiles.open(self.path, encoding="utf-8", errors="replace") as f:
            async for line in f:
                yield line.rstrip("\r\n")
