"""llama-swap (OpenAI-compatible) only. No other model provider is used anywhere in mandos."""
import json
import time

import config
import sources


def headers():
    return {"Authorization": "Bearer " + config.LLM_KEY} if config.LLM_KEY else {}


def models():
    """Model ids from /v1/models, or {'error': ...}."""
    try:
        r = sources.client().get(config.LLM_URL + "/v1/models", headers=headers(), timeout=6)
        if r.status_code >= 400:
            return {"error": f"HTTP {r.status_code}"}
        return sorted(m["id"] for m in r.json().get("data", []) if m.get("id"))
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)[:200]}


def chat_body(system, user, schema=None, name="out", temperature=0.2):
    body = {"model": config.LLM_MODEL, "stream": False, "temperature": temperature, "top_p": 0.8, "top_k": 20,
            "chat_template_kwargs": {"enable_thinking": False},
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
    if schema:
        body["response_format"] = {"type": "json_schema", "json_schema": {"name": name, "schema": schema}}
    return body


def post_chat(body, timeout=240):
    """Raw /v1/chat/completions answer, or {'error': ...}."""
    try:
        r = sources.client().post(config.LLM_URL + "/v1/chat/completions", json=body, timeout=timeout, headers=headers())
        if r.status_code >= 400:
            return {"error": f"HTTP {r.status_code}: {r.text[:200]}"}
        return r.json()
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)[:300]}


def parse_json_answer(r):
    """(obj, why). why is '' when obj is usable. Checks: request error, JSON, finish_reason."""
    if r.get("error"):
        return None, "request failed: " + str(r["error"])[:200]
    ch = (r.get("choices") or [{}])[0] or {}
    try:
        obj = json.loads((ch.get("message") or {}).get("content") or "")
    except ValueError:
        return None, "invalid JSON"
    if ch.get("finish_reason") and ch.get("finish_reason") != "stop":
        return None, "cut off: " + str(ch.get("finish_reason"))
    return obj, ""


def chat_json(system, user, schema, name="out", temperature=0.2, retries=2, check=None):
    """One json_schema call; retried (at temp 0) when the answer does not parse or fails check."""
    why = ""
    for attempt in range(retries + 1):
        r = post_chat(chat_body(system, user, schema, name, temperature if attempt == 0 else 0))
        obj, why = parse_json_answer(r)
        if obj is not None and check:
            why = check(obj) or ""
            if why:
                obj = None
        if obj is not None:
            return obj, attempt > 0, ""
        time.sleep(1 if attempt < retries else 0)
    return None, True, why


def chat_text(system, user, temperature=0.2, retries=2):
    for attempt in range(retries + 1):
        r = post_chat(chat_body(system, user, None, temperature=temperature), timeout=300)
        if not r.get("error"):
            ch = (r.get("choices") or [{}])[0] or {}
            txt = ((ch.get("message") or {}).get("content") or "").strip()
            if txt:
                return txt
        time.sleep(5 if attempt < retries else 0)
    raise RuntimeError("llama-swap gave no text answer: " + str(r.get("error", ""))[:200])


def embed(texts):
    if not texts:
        return []
    r = sources.client().post(config.LLM_URL + "/v1/embeddings", json={"model": config.EMBED_MODEL, "input": texts}, timeout=120, headers=headers())
    r.raise_for_status()
    data = sorted(r.json()["data"], key=lambda d: d["index"])
    return [d["embedding"] for d in data]


def cos(a, b):
    d = x = y = 0.0
    for i in range(len(a)):
        d += a[i] * b[i]
        x += a[i] * a[i]
        y += b[i] * b[i]
    return d / ((x * y) ** 0.5)
