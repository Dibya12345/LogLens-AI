from __future__ import annotations

from loglens.llm.config import LLMConfig
from loglens.llm.providers import get_provider, parse_response
from loglens.llm.transport import HttpTransport, LLMResponse


class LLMClient:
    def __init__(self, config: LLMConfig):
        self.config = config
        self.provider = get_provider(config)
        self.transport = HttpTransport(timeout=config.timeout, retries=config.retries)

    def chat(self, messages: list[dict[str, str]]) -> LLMResponse:
        p = self.provider
        data = self.transport.post_json(
            p.endpoint(),
            p.headers(),
            p.payload(messages),
            on_http_error=p.explain_error,
        )
        content, usage = parse_response(data)
        return LLMResponse(
            content=content,
            usage=usage,
            model=self.config.model,
            provider=self.config.provider,
        )
