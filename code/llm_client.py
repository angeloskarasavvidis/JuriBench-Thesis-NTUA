#!/usr/bin/env python3
"""
llm_client.py — κοινός βοηθός για κλήσεις σε OpenAI-compatible chat API (π.χ. OpenRouter).
Ρυθμίζεται από .env: LLM_API_KEY, LLM_BASE_URL, LLM_MODEL.
Χρησιμοποιείται από eval_judge.py και eval_ideology.py.
"""
import json, os, time
import requests

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass


def cfg():
    return (
        os.environ.get("LLM_MODEL", "openai/gpt-4o-mini"),
        os.environ.get("LLM_BASE_URL", "https://openrouter.ai/api/v1"),
        os.environ.get("LLM_API_KEY", ""),
    )


def chat_json(messages, model=None, base_url=None, api_key=None, timeout=90, temperature=0):
    """Στέλνει chat completion, ζητά JSON, επιστρέφει dict (ή {} σε αποτυχία)."""
    m, b, k = cfg()
    model, base_url, api_key = model or m, base_url or b, api_key or k
    url = base_url.rstrip("/") + "/chat/completions"
    payload = {"model": model, "messages": messages, "temperature": temperature,
               "response_format": {"type": "json_object"}}
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    for attempt in range(1, 5):
        try:
            r = requests.post(url, headers=headers, json=payload, timeout=timeout)
            if r.status_code in (429, 500, 502, 503, 504):
                print(f"    HTTP {r.status_code} — wait {attempt*10}s ({attempt}/4)")
                time.sleep(attempt * 10)
                continue
            r.raise_for_status()
            content = r.json()["choices"][0]["message"]["content"]
            try:
                return json.loads(content)
            except json.JSONDecodeError:
                s = content[content.index("{"): content.rindex("}") + 1]
                return json.loads(s)
        except (requests.RequestException, ValueError) as e:
            print(f"    {type(e).__name__} — wait {attempt*5}s ({attempt}/4)")
            time.sleep(attempt * 5)
    return {}
