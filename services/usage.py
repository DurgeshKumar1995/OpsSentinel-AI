"""Token usage aggregation and configurable cost estimation."""

from collections.abc import Iterable


def summarize_usage(
    messages: Iterable[object], model: str, input_price_per_million: float,
    output_price_per_million: float,
) -> dict:
    input_tokens = 0
    output_tokens = 0
    ai_calls = 0
    for message in messages:
        if getattr(message, "type", None) != "ai":
            continue
        ai_calls += 1
        usage = getattr(message, "usage_metadata", None) or {}
        if not usage:
            metadata = getattr(message, "response_metadata", None) or {}
            usage = metadata.get("token_usage", {})
        input_tokens += int(usage.get("input_tokens", usage.get("prompt_tokens", 0)) or 0)
        output_tokens += int(usage.get("output_tokens", usage.get("completion_tokens", 0)) or 0)
    cost = (
        input_tokens * input_price_per_million
        + output_tokens * output_price_per_million
    ) / 1_000_000
    return {
        "model": model if ai_calls else None,
        "ai_calls": ai_calls,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
        "estimated_cost_usd": round(cost, 8),
        "currency": "USD",
        "is_estimate": True,
    }


def zero_usage() -> dict:
    return {
        "model": None,
        "ai_calls": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "estimated_cost_usd": 0.0,
        "currency": "USD",
        "is_estimate": True,
    }
