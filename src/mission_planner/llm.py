import os
from typing import Protocol

from .llm_adapters import OpenAIAdapter, GeminiAdapter
try:
    from .llm_adapters import TransformersAdapter
except Exception:
    TransformersAdapter = None


class LLMClient(Protocol):
    def generate(self, prompt: str, stream: bool = False) -> str:
        ...


class MockLLM:
    """A deterministic mock LLM for local development and testing.

    The mock 'generates' by returning a short JSON fragment describing which
    source doc_ids it saw in the prompt. This is intentionally simple and
    deterministic so it can be used in CI and offline demos.
    """

    def generate(self, prompt: str, stream: bool = False) -> str:
        # Extract any occurrences of doc_id:XXXX from the prompt and summarize
        doc_ids = []
        for token in prompt.split():
            if token.startswith("doc_id:"):
                did = token.split("doc_id:", 1)[1].strip().strip(',')
                if did and did not in doc_ids:
                    doc_ids.append(did)
        # return a simple JSON-like string
        return '{"rationale":"Enriched using docs: ' + ",".join(doc_ids) + '"}'


def get_default_llm() -> LLMClient:
    # Prefer Gemini if provided, then OpenAI, else fall back to MockLLM
    gem_key = os.environ.get("GEMINI_API_KEY")
    if gem_key:
        try:
            return GeminiAdapter(api_key=gem_key)
        except Exception:
            pass
    key = os.environ.get("OPENAI_API_KEY")
    if key:
        return OpenAIAdapter(api_key=key)
    # If transformers are available, use a local model as a non-cloud fallback
    if TransformersAdapter is not None:
        try:
            return TransformersAdapter()
        except Exception:
            pass
    return MockLLM()
