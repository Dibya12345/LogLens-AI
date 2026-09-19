from __future__ import annotations

from abc import ABC, abstractmethod

from loglens.llm.config import LLMConfig
from loglens.llm.transport import LLMError, TokenUsage


class LLMProvider(ABC):
    """Base class: build the request for one chat-completion backend."""

    name: str = ""

    def __init__(self, config: LLMConfig):
        self.config = config

    @abstractmethod
    def endpoint(self) -> str:
        """The full chat-completions URL for this provider."""

    @abstractmethod
    def headers(self) -> dict[str, str]:
        """Auth + content-type headers for this provider."""

    def payload(self, messages: list[dict[str, str]]) -> dict:
        """The JSON request body. Shared shape; subclasses may adjust."""
        c = self.config
        return {
            "model": c.model,
            "messages": messages,
            "temperature": c.temperature,
            "max_tokens": c.max_tokens,
        }

    def explain_error(self, code: int, detail: str) -> str | None:
        """Turn a non-retryable HTTP status into a friendly message (or None)."""
        if code == 401:
            return f"[{self.name}] Invalid API key (401). {detail}"
        return None


class _OpenAICompatible(LLMProvider):
    """Shared behaviour for OpenAI-compatible APIs (Bearer auth, model in body)."""

    base_url: str = ""

    def endpoint(self) -> str:
        return self.base_url

    def headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.config.api_key}",
        }


class OpenAIProvider(_OpenAICompatible):
    name = "openai"
    base_url = "https://api.openai.com/v1/chat/completions"


class GroqProvider(_OpenAICompatible):
    name = "groq"
    base_url = "https://api.groq.com/openai/v1/chat/completions"


class AzureProvider(LLMProvider):
    """Azure OpenAI: api-key header, deployment in the URL, no model in body."""

    name = "azure"

    def endpoint(self) -> str:
        az = self.config.azure
        return (
            f"{az.endpoint}/openai/deployments/{az.deployment}"
            f"/chat/completions?api-version={az.api_version}"
        )

    def headers(self) -> dict[str, str]:
        return {"Content-Type": "application/json", "api-key": self.config.api_key}

    def payload(self, messages: list[dict[str, str]]) -> dict:
        p = super().payload(messages)
        p.pop("model", None)  # Azure selects the model via the deployment in the URL
        return p

    def explain_error(self, code: int, detail: str) -> str | None:
        if code == 401:
            return f"[azure] Invalid API key (401). {detail}"
        if code == 404:
            return (
                f"[azure] 404 — check endpoint/deployment name "
                f"('{self.config.azure.deployment}') and api-version. {detail}"
            )
        return None


_REGISTRY = {
    "openai": OpenAIProvider,
    "groq": GroqProvider,
    "azure": AzureProvider,
}


def get_provider(config: LLMConfig) -> LLMProvider:
    try:
        cls = _REGISTRY[config.provider]
    except KeyError:
        raise LLMError(
            f"Unknown provider '{config.provider}'. Use {' | '.join(_REGISTRY)}."
        ) from None
    return cls(config)


def parse_response(data: dict) -> tuple[str, TokenUsage]:
    usage = data.get("usage") or {}
    content = data["choices"][0]["message"]["content"]
    return content, TokenUsage(
        prompt_tokens=usage.get("prompt_tokens", 0),
        completion_tokens=usage.get("completion_tokens", 0),
        total_tokens=usage.get("total_tokens", 0),
    )
