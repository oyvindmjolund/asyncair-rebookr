"""The mock 'brain': deterministic fake LLM behaviour.

Every provider endpoint in server.py normalises its request into a simple
list of turns, asks the brain what to do, and then renders the answer in
its own wire format. The brain never needs the internet or an API key.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field

REBOOK_WORDS = ("rebook", "cancel", "flight", "get home", "alternative", "next departure", "ombook", "kansellert")

AIRPORTS = {"KRS", "OSL", "BGO", "TRD", "SVG", "TOS", "CPH", "ARN", "LHR", "CDG", "AMS", "FRA"}

# Small stylistic differences so you can see *which* provider answered.
FLAVOUR = {
    "anthropic": {
        "open": "I'm sorry your trip has been disrupted.",
        "close": "Let me know if you'd like me to go ahead.",
    },
    "openai": {
        "open": "Sorry about the disruption!",
        "close": "Want me to book one of these for you?",
    },
    "azure": {
        "open": "We apologise for the disruption to your journey.",
        "close": "Please confirm which option you prefer.",
    },
}


@dataclass
class Turn:
    role: str  # "user" | "assistant"
    text: str = ""
    has_image: bool = False
    tool_results: list[str] = field(default_factory=list)
    tool_calls: list[str] = field(default_factory=list)


@dataclass
class Decision:
    kind: str  # "text" | "tool"
    text: str = ""
    tool_name: str = ""
    tool_args: dict = field(default_factory=dict)


def _stable(n: int, *parts: str) -> int:
    h = hashlib.sha256("|".join(parts).encode()).hexdigest()
    return int(h[:8], 16) % n


def decide(provider: str, system: str, turns: list[Turn], tool_names: list[str]) -> Decision:
    f = FLAVOUR.get(provider, FLAVOUR["anthropic"])
    last = turns[-1] if turns else Turn("user", "")
    all_text = " ".join(t.text for t in turns)

    # 1. LLM-as-judge requests (used by evals/run.py in mock mode).
    if "ROLE: IMPARTIAL JUDGE" in system or "ROLE: IMPARTIAL JUDGE" in last.text:
        score = 2 + _stable(4, provider, last.text)  # 2..5
        return Decision("text", json.dumps({"score": score, "reasoning": f"Mock judge ({provider}) gave {score}/5."}))

    norwegian = bool(re.search(r"[æøå]|\b(hei|hallo|flyet|reisen|kansellert)\b", all_text.lower()))
    if norwegian:
        f = {"open": "Beklager at reisen din ble forstyrret.", "close": "Si fra hvilken avgang du vil ha, så ordner jeg det."}

    # 2. We just got tool results back -> summarise them.
    if last.tool_results:
        payload = last.tool_results[-1]
        try:
            data = json.loads(payload)
        except (json.JSONDecodeError, TypeError):
            data = None
        if isinstance(data, dict) and "flights" in data:
            opts = data["flights"]
            if not opts:
                return Decision("text", f"{f['open']} I couldn't find any alternative flights on that route today.")
            if norwegian:
                lines = [f"- {o['flight']} avgang {o['departs']} ({o['seats_left']} ledige seter)" for o in opts[:3]]
                return Decision("text", f"{f['open']} Jeg fant disse alternativene:\n" + "\n".join(lines) + f"\n{f['close']}")
            lines = [f"- {o['flight']} departing {o['departs']} ({o['seats_left']} seats left)" for o in opts[:3]]
            return Decision("text", f"{f['open']} I found these alternatives:\n" + "\n".join(lines) + f"\n{f['close']}")
        if isinstance(data, dict) and data.get("status") == "confirmed":
            return Decision("text", f"Done! You're now booked on {data['flight']} (booking {data['booking_ref']}). A new boarding pass is on its way to your email.")
        if isinstance(data, dict) and "policy" in data:
            return Decision("text", f"Here's the baggage policy for your fare: {data['policy']}")
        return Decision("text", f"Thanks, I've checked that for you: {payload[:200]}")

    # 3. Images (vision).
    if last.has_image:
        return Decision("text", "I can see a boarding pass for AsyncAir flight AX 512 from Kristiansand (KRS) to Oslo (OSL), seat 14C. That flight was cancelled due to the storm; shall I look for alternatives?")

    text = last.text.lower()

    # 4. Tool use when tools are on offer.
    if tool_names:
        m = re.search(r"\b(ax\s?\d{2,4})\b", text)
        ref = re.search(r"\b([A-Z0-9]{6})\b", last.text)
        if "rebook_passenger" in tool_names and m and ("book" in text or "take" in text or "yes" in text):
            return Decision("tool", tool_name="rebook_passenger", tool_args={
                "booking_ref": ref.group(1) if ref else "ASYNC1",
                "flight_number": m.group(1).upper().replace(" ", ""),
            })
        if "baggage_policy" in tool_names and any(w in text for w in ("bag", "luggage", "suitcase", "bagasje")):
            fare = "flex" if "flex" in text else ("plus" if "plus" in text else "light")
            return Decision("tool", tool_name="baggage_policy", tool_args={"fare_class": fare})
        if "search_flights" in tool_names and any(w in text for w in REBOOK_WORDS):
            codes = [c for c in re.findall(r"\b([A-Z]{3})\b", last.text) if c in AIRPORTS]
            origin = codes[0] if codes else "KRS"
            dest = codes[1] if len(codes) > 1 else ("OSL" if origin != "OSL" else "KRS")
            return Decision("tool", tool_name="search_flights", tool_args={"origin": origin, "destination": dest})

    # 5. Plain text answers.
    if any(w in text for w in ("ignore", "free upgrade", "system prompt")):
        return Decision("text", "I'm not able to do that, but I'm happy to help you rebook or answer questions about your trip.")
    if any(w in text for w in ("compensation", "refund", "erstatning")):
        return Decision("text", f"{f['open']} Under EU rules you may be entitled to assistance and, in some cases, compensation, but storms are usually treated as extraordinary circumstances. You can submit a claim through the AsyncAir website and our team will assess it.")
    if any(w in text for w in ("bag", "luggage", "bagasje")):
        return Decision("text", "On AsyncAir Light fares you can bring one small cabin bag. Plus and Flex fares include a 23 kg checked bag.")
    if re.search(r"[æøå]", last.text.lower()) or re.search(r"\b(hei|hallo|reisen|flyet)\b", text):
        return Decision("text", "Beklager at reisen din ble forstyrret av stormen. Jeg kan hjelpe deg med å finne en ny avgang – hvor skal du reise?")
    return Decision("text", f"{f['open']} I'm Rebookr, AsyncAir's assistant. I can help you rebook cancelled flights, check baggage rules, or explain what happens next. {f['close']}")


def estimate_tokens(s: str) -> int:
    return max(1, len(s) // 4)
