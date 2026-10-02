"""Gemini pricing and cost accounting, with calls made through LiteLLM.

LiteLLM keeps the door open to other providers: a call is a model string
and a message list, whatever the model. Only Gemini is priced here so far.

Cost is exact because LiteLLM's usage.total_tokens is Gemini's own
totalTokenCount, which is prompt + visible output + thinking. Billed output,
which is visible output plus thinking at the same rate, is therefore
total - prompt, without depending on whether completion_tokens happens to
include the thinking in a given response shape.

The API key is read from GEMINI_API_KEY in the environment, or failing that
from a .env file at the repo root (gitignored).

LiteLLM is imported only when a call is made, so the rest of merge.py
runs without it installed.
"""

import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

ENV_FILE = Path(__file__).resolve().parent.parent / ".env"

MILLION = 1_000_000
LONG_CONTEXT = 200_000  # Pro-tier prompts above this are billed at the long rate
MAX_OUTPUT_CAP = 65_536  # the most output tokens a current Gemini model will emit


@dataclass(frozen=True)
class ModelPrice:
    """Per-million-token prices in USD.

    `output_per_1m` applies to ALL generated tokens, thinking included: on the
    Gemini API, billed output = visible output + thinking tokens, at the same
    rate.

    The `*_long_per_1m` rates apply when the prompt exceeds 200K tokens, on the
    tiered (Pro) models only; None means flat pricing.

    `cached_per_1m` is the rate for prompt tokens served from Google's context
    cache. None means the rate has not been verified, and those tokens are
    then charged at the full input rate, so the reported cost is an upper
    bound and is labelled as one.
    """
    input_per_1m: float
    output_per_1m: float
    input_long_per_1m: Optional[float] = None
    output_long_per_1m: Optional[float] = None
    cached_per_1m: Optional[float] = None


# Update these to match the rates Google publishes for each model. Keys are
# short names without the "gemini-" prefix.
#
# Pricing sourced from https://ai.google.dev/gemini-api/docs/pricing
# as of 2026-09-15. All prices in USD per 1M tokens.
#
# NOTE: 3.6/3.7/3.8-flash are on PROMOTIONAL pricing that expires
# 2026-12-31. On 2027-01-01 they go to $1.50/$7.50 — double the rates
# below. Revisit this dict at the turn of the year. Costs already in a run's
# ledger keep the price that was charged at the time.
#
# Audio input is priced higher than text/image/video on several Flash models
# (e.g. 2.5-flash is $0.30 text but $1.00 audio). Only text is sent here, so
# the text rate is what's encoded.
PRICES: dict[str, ModelPrice] = {
    # --- Gemini 3.x Flash (promotional pricing through 2026-12-31) ---
    "3.8-flash":       ModelPrice(0.75, 3.75),   # -> 1.50/7.50 on 2027-01-01
    "3.7-flash":       ModelPrice(0.75, 3.75),   # -> 1.50/7.50 on 2027-01-01
    "3.6-flash":       ModelPrice(0.75, 3.75),   # -> 1.50/7.50 on 2027-01-01
    # --- Gemini 3.x (stable rates) ---
    "3.5-flash":       ModelPrice(1.50, 9.00),   # released 2026-05-19
    "3.5-flash-lite":  ModelPrice(0.30, 2.50),
    "3.1-pro":         ModelPrice(2.00, 12.00, input_long_per_1m=4.00, output_long_per_1m=18.00),
    "3.1-flash-lite":  ModelPrice(0.25, 1.50),
    "3-flash":         ModelPrice(0.50, 3.00),
    # Preview-suffixed aliases. 3-flash and 3.1-pro are themselves still
    # labelled Preview by Google.
    "3-flash-preview": ModelPrice(0.50, 3.00),
    "3.1-pro-preview": ModelPrice(2.00, 12.00, input_long_per_1m=4.00, output_long_per_1m=18.00),
    # --- Gemini 2.5 (legacy, paid tier only as of 2026-04-01) ---
    "2.5-pro":         ModelPrice(1.25, 10.00, input_long_per_1m=2.50, output_long_per_1m=15.00),
    "2.5-flash":       ModelPrice(0.30, 2.50),
    "2.5-flash-lite":  ModelPrice(0.10, 0.40),   # relisted; cheapest option
    # "3-pro" was dropped: Google no longer publishes a standalone Gemini 3 Pro
    # rate. Re-add only with a verified price; an unpriced model is refused
    # rather than silently recorded at $0.00.
}


def short_name(model):
    """'models/gemini-2.5-flash' or 'gemini-2.5-flash' -> '2.5-flash'."""
    name = model.split("/")[-1]
    return name[len("gemini-"):] if name.startswith("gemini-") else name


def model_id(model):
    """'2.5-flash' -> 'gemini-2.5-flash', the name the API wants."""
    return f"gemini-{short_name(model)}"


def price_for(model):
    return PRICES.get(short_name(model))


@dataclass(frozen=True)
class Usage:
    """Token counts from one response.

    `prompt` includes `cached`; cached tokens are a discounted subset of the
    prompt, not an addition to it. `candidates` is the visible output and
    `thoughts` the thinking, which together make the billed output.
    """
    prompt: int
    cached: int
    candidates: int
    thoughts: int
    total: int

    @classmethod
    def from_litellm(cls, u):
        def get(obj, name):
            return int(getattr(obj, name, 0) or 0) if obj is not None else 0
        prompt = get(u, "prompt_tokens")
        total = get(u, "total_tokens")
        thoughts = get(getattr(u, "completion_tokens_details", None), "reasoning_tokens")
        cached = get(getattr(u, "prompt_tokens_details", None), "cached_tokens")
        if total and prompt:
            billed = total - prompt
        else:
            # No total to go by: sum the pieces. This overcounts if
            # completion_tokens already includes the thinking, which errs on
            # the safe side for a budget.
            billed = get(u, "completion_tokens") + thoughts
            total = prompt + billed
        return cls(prompt=prompt, cached=cached, candidates=billed - thoughts,
                   thoughts=thoughts, total=total)

    @property
    def output(self):
        """Billed output: visible text plus thinking."""
        return self.candidates + self.thoughts


def cost(usage, price):
    """Return (usd, is_upper_bound) for one response."""
    long = usage.prompt > LONG_CONTEXT and price.input_long_per_1m is not None
    in_rate = price.input_long_per_1m if long else price.input_per_1m
    out_rate = price.output_long_per_1m if long else price.output_per_1m
    if price.cached_per_1m is None:
        cached_rate, upper = in_rate, usage.cached > 0
    else:
        cached_rate, upper = price.cached_per_1m, False
    usd = ((usage.prompt - usage.cached) * in_rate
           + usage.cached * cached_rate
           + usage.output * out_rate) / MILLION
    return usd, upper


def price_dict(price):
    return {k: v for k, v in asdict(price).items() if v is not None}


@dataclass(frozen=True)
class Response:
    text: str
    finish_reason: str
    usage: Usage
    usage_raw: dict       # LiteLLM's usage object as reported, for the ledger
    model_version: str


class GeminiError(Exception):
    """A request that returned no response to bill. `retryable` says whether
    trying again could help (rate limits, overload, network trouble)."""

    def __init__(self, message, retryable):
        super().__init__(message)
        self.retryable = retryable


def api_key():
    key = os.environ.get("GEMINI_API_KEY")
    if key:
        return key
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("export "):
                line = line[len("export "):]
            name, sep, value = line.partition("=")
            if sep and name.strip() == "GEMINI_API_KEY":
                return value.strip().strip("'\"")
    return None


def litellm_model(model):
    """'2.5-flash' -> 'gemini/gemini-2.5-flash', LiteLLM's name for it."""
    return f"gemini/{model_id(model)}"


def _retryable_errors(litellm):
    names = ("RateLimitError", "InternalServerError", "ServiceUnavailableError",
             "BadGatewayError", "Timeout", "APIConnectionError")
    return tuple(getattr(litellm, n) for n in names if hasattr(litellm, n))


def generate(model, prompt, *, key, temperature, max_output_tokens, timeout=600):
    """One completion call. Returns a Response or raises GeminiError.

    finish_reason is LiteLLM's: "stop" when the answer is complete, "length"
    when it ran out of output budget, anything else when it was cut off.
    """
    import litellm
    litellm.suppress_debug_info = True

    try:
        r = litellm.completion(
            model=litellm_model(model),
            messages=[{"role": "user", "content": [{"type": "text", "text": prompt}]}],
            max_tokens=max_output_tokens,
            temperature=temperature,
            api_key=key,
            timeout=timeout,
        )
    except _retryable_errors(litellm) as exc:
        raise GeminiError(f"{type(exc).__name__}: {exc}", retryable=True) from exc
    except Exception as exc:  # bad request, auth, unknown model: retrying won't help
        raise GeminiError(f"{type(exc).__name__}: {exc}", retryable=False) from exc

    choice = r.choices[0]
    usage = getattr(r, "usage", None)
    raw = usage.model_dump() if hasattr(usage, "model_dump") else {}
    return Response(text=choice.message.content or "",
                    finish_reason=choice.finish_reason or "unknown",
                    usage=Usage.from_litellm(usage),
                    usage_raw=raw,
                    model_version=getattr(r, "model", "") or "")
