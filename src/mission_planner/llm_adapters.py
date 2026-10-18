import os
import json
from typing import Protocol, Optional
import tenacity
import requests

try:
    import openai
except Exception:
    openai = None

try:
    from transformers import pipeline, AutoTokenizer, AutoModelForSeq2SeqLM
except Exception:
    pipeline = None



class LLMClientProtocol(Protocol):
    def generate(self, prompt: str, stream: bool = False) -> str:
        ...


class OpenAIAdapter:
    def __init__(self, api_key: Optional[str] = None, model: str = "gpt-4o-mini"):
        if openai is None:
            raise RuntimeError("openai package not installed")
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY")
        if not self.api_key:
            raise RuntimeError("OPENAI_API_KEY is not set")
        openai.api_key = self.api_key
        self.model = model

    @tenacity.retry(wait=tenacity.wait_exponential(min=1, max=10), stop=tenacity.stop_after_attempt(3), reraise=True)
    def generate(self, prompt: str, stream: bool = False) -> str:
        # Non-streaming call with basic retry via tenacity
        if stream:
            # streaming not implemented in this adapter for now; fall back
            stream = False
        resp = openai.ChatCompletion.create(model=self.model, messages=[{"role":"user","content":prompt}], max_tokens=800)
        # extract text
        if resp and resp.choices and len(resp.choices) > 0:
            return resp.choices[0].message.get('content', '')
        return ""


class GeminiAdapter:
    """Simple Gemini/Generative API adapter.

    NOTE: This adapter expects a bearer token in `GEMINI_API_KEY` and a model
    name in `GEMINI_MODEL` (defaults to `gemini-pro-preview`). The exact
    REST shape for the Google Generative API can vary; this implementation
    returns the first text candidate if present and falls back to a JSON
    dump of the response.
    """
    def __init__(self, api_key: Optional[str] = None, model: str | None = None):
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY")
        if not self.api_key:
            raise RuntimeError("GEMINI_API_KEY is not set")
        self.model = model or os.environ.get("GEMINI_MODEL", "gemini-pro-preview")

    @tenacity.retry(wait=tenacity.wait_exponential(min=1, max=10), stop=tenacity.stop_after_attempt(3), reraise=True)
    def generate(self, prompt: str, stream: bool = False) -> str:
        # Build a conservative request body compatible with the Google Generative
        # Models REST surface. If the real endpoint used by the user differs,
        # they can adapt the adapter accordingly.
        url = f"https://generativelanguage.googleapis.com/v1beta2/models/{self.model}:generateMessage"
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        body = {"messages": [{"author": "user", "content": {"type": "text", "text": prompt}}], "temperature": 0.2}
        resp = requests.post(url, headers=headers, json=body, timeout=30)
        resp.raise_for_status()
        j = resp.json()
        # Attempt to extract a plain text candidate if present
        try:
            # Common response shapes: `candidates` -> `content` -> list of text parts
            cand = j.get("candidates") or j.get("messages") or []
            if cand and isinstance(cand, list) and len(cand) > 0:
                first = cand[0]
                # try a couple of likely keys
                if isinstance(first, dict):
                    # nested content list
                    content = first.get("content") or first.get("message") or {}
                    if isinstance(content, list) and content:
                        # try object with 'text'
                        maybe = content[0]
                        if isinstance(maybe, dict) and "text" in maybe:
                            return maybe.get("text") or json.dumps(j)
                    # fallback to 'text' or 'output'
                    return first.get("text") or first.get("output") or json.dumps(j)
        except Exception:
            pass
        # Last resort: return JSON string
        return json.dumps(j)


class TransformersAdapter:
    """Local Transformers adapter using a seq2seq/text2text model.

    This adapter is chosen when no cloud provider API key is present and
    the `transformers` package is installed. It uses the model named by
    the TRANSFORMERS_MODEL env var (default: google/flan-t5-small).
    """
    def __init__(self, model_name: Optional[str] = None, device: int | None = None):
        if pipeline is None:
            raise RuntimeError("transformers not installed")
        self.model_name = model_name or os.environ.get("TRANSFORMERS_MODEL", "google/flan-t5-small")
        self.device = device
        # Use the text2text-generation pipeline for seq2seq models
        try:
            self._pipe = pipeline("text2text-generation", model=self.model_name, device=self.device)
        except Exception:
            # fallback to text-generation
            self._pipe = pipeline("text-generation", model=self.model_name, device=self.device)

    @tenacity.retry(wait=tenacity.wait_exponential(min=1, max=8), stop=tenacity.stop_after_attempt(2), reraise=True)
    def generate(self, prompt: str, stream: bool = False) -> str:
        # Keep outputs short by restricting max_length
        try:
            out = self._pipe(prompt, max_length=512, num_return_sequences=1)
            if isinstance(out, list) and len(out) > 0:
                if isinstance(out[0], dict) and ("generated_text" in out[0] or "text" in out[0]):
                    return out[0].get("generated_text") or out[0].get("text") or ""
                # string-like fallback
                return str(out[0])
        except Exception:
            pass
        return ""
