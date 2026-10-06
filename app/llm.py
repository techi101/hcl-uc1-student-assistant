"""One function to call the LLM. Provider chosen in .env: ollama (default, local) | groq (cloud fallback) | mock.
HCL rule: cloud LLM only as a fallback behind a config switch -> LLM_PROVIDER + automatic fallback on Ollama failure."""
import logging
import os
import time

import httpx

from app import config

log = logging.getLogger(__name__)


def _ollama(system: str, user: str, json_mode: bool) -> dict:
    body = {"model": config.OLLAMA_MODEL, "stream": False, "options": {"temperature": 0, "num_predict": 350, "num_ctx": 4096}, "keep_alive": "30m",
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
    if json_mode:
        body["format"] = "json"
    r = httpx.post(f"{config.OLLAMA_URL}/api/chat", json=body, timeout=120)
    r.raise_for_status()
    d = r.json()
    return {"text": d["message"]["content"], "model": f"ollama:{config.OLLAMA_MODEL}",
            "tokens": d.get("prompt_eval_count", 0) + d.get("eval_count", 0)}


def _groq(system: str, user: str, json_mode: bool) -> dict:
    from groq import Groq
    kw = {"response_format": {"type": "json_object"}} if json_mode else {}
    r = Groq(api_key=os.getenv("GROQ_API_KEY"), timeout=30).chat.completions.create(
        model=config.GROQ_MODEL, temperature=0, max_tokens=600,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}], **kw)
    return {"text": r.choices[0].message.content, "model": f"groq:{config.GROQ_MODEL}",
            "tokens": r.usage.total_tokens}


def _mock(system: str, user: str, json_mode: bool) -> dict:
    text = ('{"category": "policy", "course_hint": null, "target_student_id_in_text": null}'
            if json_mode else "MOCK answer based only on the provided sources.")
    return {"text": text, "model": "mock", "tokens": 0}


PROVIDERS = {"ollama": _ollama, "groq": _groq, "mock": _mock}


def chat(system: str, user: str, json_mode: bool = False) -> dict:
    """Returns {text, model, tokens, ms}. Falls back ollama -> groq if the local model fails."""
    order = [config.LLM_PROVIDER]
    if config.LLM_PROVIDER == "ollama" and os.getenv("GROQ_API_KEY"):
        order.append("groq")
    t0 = time.perf_counter()
    last_err = None
    for name in order:
        for attempt in range(4):
            try:
                out = PROVIDERS[name](system, user, json_mode)
                out["ms"] = round((time.perf_counter() - t0) * 1000)
                return out
            except Exception as e:  # network down, model missing, 429 ...
                last_err = e
                if "429" in str(e) or "rate limit" in str(e).lower():
                    # rate limit (Groq free tier: 8K tokens/min) -> back off and retry instead of failing the answer;
                    # found in the eval: a 429 during compose turned a correct answer into not_found
                    wait = 2 ** attempt * 2
                    log.warning("LLM %s rate-limited, retry in %ss (attempt %d)", name, wait, attempt + 1)
                    time.sleep(wait)
                    continue
                log.warning("LLM provider %s failed: %s", name, e)
                break
    raise RuntimeError(f"all LLM providers failed: {last_err}")


def health() -> str:
    if config.LLM_PROVIDER == "mock":
        return "mock"
    if config.LLM_PROVIDER == "groq":
        return f"ok (groq:{config.GROQ_MODEL} — cloud fallback mode)" if os.getenv("GROQ_API_KEY") else "down (no GROQ_API_KEY)"
    try:
        httpx.get(f"{config.OLLAMA_URL}/api/tags", timeout=3).raise_for_status()
        return f"ok (ollama:{config.OLLAMA_MODEL})"
    except Exception:
        return "ollama down (groq fallback)" if os.getenv("GROQ_API_KEY") else "down"
