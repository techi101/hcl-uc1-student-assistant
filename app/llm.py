"""One function to call the LLM. Provider chosen in .env: ollama (default, local) | groq (cloud fallback) | mock.
HCL rule: cloud LLM only as a fallback behind a config switch -> LLM_PROVIDER + automatic fallback on Ollama failure."""
# WHAT THIS FILE IS: the only place in the project that talks to a language model (LLM).
# The rest of the code calls chat(system, user) and does not care WHICH model answered.
# A PROVIDER is a service that runs a model: Ollama (on our own laptop), Groq (in the cloud), or mock (fake, for tests).
# Real example: chat(CLASSIFY_SYSTEM, "What is my CGPA?", json_mode=True)
#  -> {"text": '{"category": "personal", ...}', "model": "ollama:qwen2.5:7b-instruct", "tokens": 412, "ms": 1830}
# If Ollama is down and a GROQ_API_KEY exists, the same call is answered by Groq instead (automatic fallback).
# os = read environment variables (GROQ_API_KEY). time = measure milliseconds and wait between retries.
import logging
import os
import time

# httpx = a library for sending HTTP requests (we use it to call Ollama's local web API).
import httpx

from app import config

# A logger named after this module ("app.llm"), so log lines show where they came from.
log = logging.getLogger(__name__)


# IN: system prompt + user message + json_mode flag  ->  OUT: {"text", "model", "tokens"} from local Ollama.
# WHY: Ollama is the default (HCL wants a local model first). It listens on http://localhost:11434.
# temperature 0 = always pick the most likely word, so the same question gives the same answer (repeatable).
# num_predict 350 = at most 350 output tokens. num_ctx 4096 = how much text the model can read at once.
# keep_alive "4h" = keep the model loaded in memory for 4 hours, so later calls (and a long demo) stay fast.
def _ollama(system: str, user: str, json_mode: bool) -> dict:
    body = {"model": config.OLLAMA_MODEL, "stream": False, "options": {"temperature": 0, "num_predict": 350, "num_ctx": 4096}, "keep_alive": "4h",
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
    # json_mode: ask Ollama to force the reply to be valid JSON (used by the classifier and composer).
    if json_mode:
        body["format"] = "json"
    # Send the request. timeout=120 seconds because a 7B model on CPU can be slow.
    # raise_for_status() turns an HTTP error (like 404 "model not found") into a Python exception.
    r = httpx.post(f"{config.OLLAMA_URL}/api/chat", json=body, timeout=120)
    r.raise_for_status()
    d = r.json()
    # Tokens used = tokens read (prompt_eval_count) + tokens written (eval_count). Logged in the audit record.
    return {"text": d["message"]["content"], "model": f"ollama:{config.OLLAMA_MODEL}",
            "tokens": d.get("prompt_eval_count", 0) + d.get("eval_count", 0)}


# IN: system prompt + user message + json_mode flag  ->  OUT: {"text", "model", "tokens"} from Groq (cloud).
# WHY: the cloud fallback, used only if LLM_PROVIDER=groq or if Ollama fails and a key exists.
# The groq library is imported inside the function, so the app still starts even if it is not installed.
def _groq(system: str, user: str, json_mode: bool) -> dict:
    from groq import Groq
    # json_mode for Groq: response_format json_object forces a JSON reply. Otherwise no extra option.
    kw = {"response_format": {"type": "json_object"}} if json_mode else {}
    # Same messages as Ollama, temperature 0 for repeatable answers, max 600 output tokens, 30 second timeout.
    r = Groq(api_key=os.getenv("GROQ_API_KEY"), timeout=30).chat.completions.create(
        model=config.GROQ_MODEL, temperature=0, max_tokens=600,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}], **kw)
    return {"text": r.choices[0].message.content, "model": f"groq:{config.GROQ_MODEL}",
            "tokens": r.usage.total_tokens}


# IN: same arguments  ->  OUT: a fixed fake reply, no model at all.
# WHY: tests and quick demos run without Ollama or internet (set LLM_PROVIDER=mock in .env).
# Example: json_mode=True always returns category "policy"; json_mode=False returns a fixed sentence.
def _mock(system: str, user: str, json_mode: bool) -> dict:
    text = ('{"category": "policy", "course_hint": null, "target_student_id_in_text": null}'
            if json_mode else "MOCK answer based only on the provided sources.")
    return {"text": text, "model": "mock", "tokens": 0}


# Name -> function lookup table, so LLM_PROVIDER="groq" in .env picks _groq without any if/else chain.
PROVIDERS = {"ollama": _ollama, "groq": _groq, "mock": _mock}


# IN: system prompt, user message, json_mode  ->  OUT: {"text", "model", "tokens", "ms"} from the first provider that works.
# WHY: one entry point with fallback and retry, so a slow or broken model does not break the whole answer.
# flow: build the order list -> try each provider -> on 429 wait and retry -> on other errors move to the next provider.
# Example: LLM_PROVIDER=ollama + GROQ_API_KEY set -> order ["ollama", "groq"]. Ollama off -> Groq answers.
def chat(system: str, user: str, json_mode: bool = False) -> dict:
    """Returns {text, model, tokens, ms}. Falls back ollama -> groq if the local model fails."""
    # Start with the provider named in .env. Add Groq as a backup only when the main one is Ollama
    # and a Groq key exists (HCL rule: cloud only as a fallback behind a switch).
    order = [config.LLM_PROVIDER]
    if config.LLM_PROVIDER == "ollama" and os.getenv("GROQ_API_KEY"):
        order.append("groq")
    # Start the stopwatch. "ms" covers the whole call, including any retries.
    t0 = time.perf_counter()
    last_err = None
    # Try each provider in order. Each provider gets up to 4 attempts (attempt = 0, 1, 2, 3).
    for name in order:
        for attempt in range(4):
            # Success: add the time taken in milliseconds and return straight away.
            try:
                out = PROVIDERS[name](system, user, json_mode)
                out["ms"] = round((time.perf_counter() - t0) * 1000)
                return out
            except Exception as e:  # network down, model missing, 429 ...
                last_err = e
                # HTTP status 429 = "too many requests" (rate limit). Waits grow: 2s, 4s, 8s, 16s.
                if "429" in str(e) or "rate limit" in str(e).lower():
                    # rate limit (Groq free tier: 8K tokens/min) -> back off and retry instead of failing the answer;
                    # found in the eval: a 429 during compose turned a correct answer into not_found
                    wait = 2 ** attempt * 2
                    log.warning("LLM %s rate-limited, retry in %ss (attempt %d)", name, wait, attempt + 1)
                    time.sleep(wait)
                    continue
                # Any other error (Ollama not running, model missing): retrying will not help,
                # so log it and move on to the next provider in the order list.
                log.warning("LLM provider %s failed: %s", name, e)
                break
    # Every provider failed. Raise an error; graph.py / main.py turn this into an honest not_found answer.
    raise RuntimeError(f"all LLM providers failed: {last_err}")


# IN: nothing  ->  OUT: a short text saying which LLM is really available, shown by GET /health.
# WHY: judges can see if the local model or the cloud fallback is answering right now.
# Example: "ok (ollama:qwen2.5:7b-instruct)", or "ollama down (groq fallback)" when Ollama is off but a key exists.
def health() -> str:
    # Mock mode: no real model to check.
    if config.LLM_PROVIDER == "mock":
        return "mock"
    # Groq mode: we only check that the API key is set (no network call, so /health stays fast).
    if config.LLM_PROVIDER == "groq":
        return f"ok (groq:{config.GROQ_MODEL} — cloud fallback mode)" if os.getenv("GROQ_API_KEY") else "down (no GROQ_API_KEY)"
    # Ollama mode: ask Ollama for its model list (/api/tags), with a 3 second timeout. Reply means it is alive.
    try:
        r = httpx.get(f"{config.OLLAMA_URL}/api/tags", timeout=3)
        r.raise_for_status()
        # Ollama answering is not enough: a missing model 404s on every chat call, so check it is pulled
        names = {m.get("name") for m in r.json().get("models", [])}
        if config.OLLAMA_MODEL not in names and f"{config.OLLAMA_MODEL}:latest" not in names:
            return f"down (model {config.OLLAMA_MODEL} not pulled: ollama pull {config.OLLAMA_MODEL})"
        return f"ok (ollama:{config.OLLAMA_MODEL})"
    # Ollama did not reply: say whether Groq will take over or nothing can answer.
    except Exception:
        return "ollama down (groq fallback)" if os.getenv("GROQ_API_KEY") else "down"
