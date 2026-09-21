from __future__ import annotations

import os
from dataclasses import dataclass, field

from loglens.llm.transport import LLMError

DEFAULT_MODELS = {
    "openai": "gpt-4o-mini",
    "groq": "llama-3.3-70b-versatile",
    "azure": "",
}

SUPPORTED_PROVIDERS = ("openai", "azure", "groq")


@dataclass
class AzureOptions:
    endpoint: str = ""
    deployment: str = ""
    api_version: str = "2024-06-01"


@dataclass
class LLMConfig:
    provider: str = ""
    # repr=False so the secret never lands in logs, tracebacks, or repr(cfg).
    api_key: str = field(default="", repr=False)
    model: str = ""
    azure: AzureOptions | None = None
    # request behaviour
    temperature: float = 0.2
    max_tokens: int = 1200
    timeout: int = 60
    retries: int = 2

    @classmethod
    def from_env(cls, provider: str = "", model: str = "", api_key: str = "") -> LLMConfig:
        provider = (provider or os.getenv("LOGLENS_LLM_PROVIDER", "")).lower().strip()
        api_key = api_key or os.getenv("LOGLENS_LLM_API_KEY", "")
        model = model or os.getenv("LOGLENS_LLM_MODEL", "")

        if not provider:
            raise LLMError(
                "No LLM provider configured. Set LOGLENS_LLM_PROVIDER to "
                "'openai', 'azure' or 'groq' (or pass --provider)."
            )
        if provider not in SUPPORTED_PROVIDERS:
            raise LLMError(f"Unknown provider '{provider}'. Use openai | azure | groq.")
        if not api_key:
            raise LLMError("Missing API key. Set LOGLENS_LLM_API_KEY (or pass --api-key).")

        azure: AzureOptions | None = None
        if provider == "azure":
            azure = AzureOptions(
                endpoint=os.getenv("LOGLENS_AZURE_ENDPOINT", "").rstrip("/"),
                deployment=os.getenv("LOGLENS_AZURE_DEPLOYMENT", "") or model,
                api_version=os.getenv("LOGLENS_AZURE_API_VERSION", "2024-06-01"),
            )
            if not azure.endpoint:
                raise LLMError(
                    "Azure requires LOGLENS_AZURE_ENDPOINT (https://<resource>.openai.azure.com)."
                )
            if not azure.deployment:
                raise LLMError("Azure requires LOGLENS_AZURE_DEPLOYMENT (or LOGLENS_LLM_MODEL).")
            # For display/reporting; the real target is the deployment in the URL.
            if not model:
                model = azure.deployment
        else:
            if not model:
                model = DEFAULT_MODELS[provider]

        if not model:
            raise LLMError(f"No model resolved for provider '{provider}'.")

        return cls(provider=provider, api_key=api_key, model=model, azure=azure)
