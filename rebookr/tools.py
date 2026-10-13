"""AsyncAir's (fake) booking system, exposed to the LLM as tools.

The tool *definitions* are provider-neutral ToolSpecs. Each adapter turns
them into its own schema format - the app never has to care.
"""
from __future__ import annotations

import json
import random
import string

from rebookr.llm.types import ToolSpec

TOOLS = [
    ToolSpec(
        name="search_flights",
        description="Find alternative AsyncAir flights between two airports (IATA codes) for rebooking.",
        parameters={
            "type": "object",
            "properties": {
                "origin": {"type": "string", "description": "IATA code, e.g. KRS"},
                "destination": {"type": "string", "description": "IATA code, e.g. OSL"},
            },
            "required": ["origin", "destination"],
        },
    ),
    ToolSpec(
        name="rebook_passenger",
        description="Move a passenger's booking to a new flight. Only call after the passenger has chosen a flight.",
        parameters={
            "type": "object",
            "properties": {
                "booking_ref": {"type": "string", "description": "6-character booking reference"},
                "flight_number": {"type": "string", "description": "e.g. AX714"},
            },
            "required": ["booking_ref", "flight_number"],
        },
    ),
    ToolSpec(
        name="baggage_policy",
        description="Look up baggage allowance for a fare class.",
        parameters={
            "type": "object",
            "properties": {"fare_class": {"type": "string", "enum": ["light", "plus", "flex"]}},
            "required": ["fare_class"],
        },
    ),
]

BAGGAGE = {
    "light": "One small cabin bag (40x30x20 cm). Checked bags can be added for a fee.",
    "plus": "One cabin bag up to 8 kg plus one 23 kg checked bag.",
    "flex": "One cabin bag up to 8 kg plus two 23 kg checked bags, free changes.",
}

BOOKINGS: dict[str, str] = {}   # booking_ref -> flight; in-memory "database"


def search_flights(origin: str, destination: str) -> dict:
    rng = random.Random(f"{origin}-{destination}")      # deterministic per route
    times = sorted(rng.sample(["18:05", "19:40", "20:55", "06:30", "07:15", "09:50"], 3))
    flights = [
        {"flight": f"AX{rng.randint(100, 999)}", "origin": origin, "destination": destination,
         "departs": f"2026-10-{19 if t < '12' else 18} {t}", "seats_left": rng.randint(1, 9)}
        for t in times
    ]
    return {"flights": sorted(flights, key=lambda f: f["departs"])}


def rebook_passenger(booking_ref: str, flight_number: str) -> dict:
    BOOKINGS[booking_ref] = flight_number
    return {"status": "confirmed", "booking_ref": booking_ref, "flight": flight_number,
            "confirmation": "".join(random.choices(string.ascii_uppercase + string.digits, k=8))}


def baggage_policy(fare_class: str) -> dict:
    return {"fare_class": fare_class, "policy": BAGGAGE.get(fare_class, BAGGAGE["light"])}


def run_tool(name: str, arguments: dict) -> str:
    fn = {"search_flights": search_flights, "rebook_passenger": rebook_passenger, "baggage_policy": baggage_policy}.get(name)
    if fn is None:
        return json.dumps({"error": f"unknown tool {name}"})
    try:
        return json.dumps(fn(**arguments))
    except TypeError as e:
        return json.dumps({"error": f"bad arguments: {e}"})
