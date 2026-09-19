import numpy as np

from loglens.models import LogEntry
from loglens.pipeline.embeddings import EmbeddingEngine


def test_embed_chunking_matches_single_pass():
    entries = [
        LogEntry(
            timestamp="t",
            level="INFO",
            service="s",
            message=f"request {i % 30} ok status=200",
            raw="x",
            metadata={},
        )
        for i in range(500)
    ]
    eng = EmbeddingEngine()
    eng.fit(entries)
    single = eng.embed(entries, chunk_size=10_000)  # one pass
    chunked = eng.embed(entries, chunk_size=64)  # forced chunking
    assert single.shape == chunked.shape
    assert np.allclose(single, chunked)
