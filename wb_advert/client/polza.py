from __future__ import annotations

import json
from typing import Any

import httpx

from wb_advert.config import settings


class PolzaError(RuntimeError):
    pass


def chat_completion(
    messages: list[dict[str, str]],
    *,
    model: str | None = None,
    temperature: float = 0.2,
    response_format: dict[str, Any] | None = None,
    timeout: float = 180.0,
) -> str:
    api_key = (settings.polza_ai_api_key or "").strip()
    if not api_key:
        raise PolzaError("POLZA_AI_API_KEY not set")

    payload: dict[str, Any] = {
        "model": model or settings.polza_ai_model,
        "messages": messages,
        "temperature": temperature,
    }
    if response_format:
        payload["response_format"] = response_format

    url = f"{settings.polza_ai_base_url.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    with httpx.Client(timeout=timeout) as client:
        resp = client.post(url, headers=headers, json=payload)

    if resp.status_code == 401:
        raise PolzaError("Polza auth failed (401) — check POLZA_AI_API_KEY")
    if resp.status_code == 402:
        raise PolzaError("Polza balance insufficient (402)")
    if resp.status_code >= 400:
        raise PolzaError(f"Polza HTTP {resp.status_code}: {resp.text[:500]}")

    data = resp.json()
    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise PolzaError(f"Unexpected Polza response: {json.dumps(data, ensure_ascii=False)[:500]}") from exc


def get_balance() -> dict[str, Any]:
    api_key = (settings.polza_ai_api_key or "").strip()
    if not api_key:
        raise PolzaError("POLZA_AI_API_KEY not set")

    url = f"{settings.polza_ai_base_url.rstrip('/')}/balance"
    headers = {"Authorization": f"Bearer {api_key}"}
    with httpx.Client(timeout=30.0) as client:
        resp = client.get(url, headers=headers)
    if resp.status_code >= 400:
        raise PolzaError(f"Balance HTTP {resp.status_code}: {resp.text[:300]}")
    return resp.json()
