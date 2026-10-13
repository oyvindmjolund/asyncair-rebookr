import type { ToolSpec } from "./llm/types.js";

// Same fake booking system as rebookr/tools.py (simplified).
export const TOOLS: ToolSpec[] = [
  { name: "search_flights", description: "Find alternative AsyncAir flights between two airports (IATA codes) for rebooking.",
    parameters: { type: "object", properties: { origin: { type: "string" }, destination: { type: "string" } }, required: ["origin", "destination"] } },
  { name: "rebook_passenger", description: "Move a booking to a new flight. Only after the passenger has chosen.",
    parameters: { type: "object", properties: { booking_ref: { type: "string" }, flight_number: { type: "string" } }, required: ["booking_ref", "flight_number"] } },
  { name: "baggage_policy", description: "Look up baggage allowance for a fare class.",
    parameters: { type: "object", properties: { fare_class: { type: "string", enum: ["light", "plus", "flex"] } }, required: ["fare_class"] } },
];

const BAGGAGE: Record<string, string> = {
  light: "One small cabin bag (40x30x20 cm). Checked bags can be added for a fee.",
  plus: "One cabin bag up to 8 kg plus one 23 kg checked bag.",
  flex: "One cabin bag up to 8 kg plus two 23 kg checked bags, free changes.",
};

export function runTool(name: string, args: Record<string, any>): string {
  switch (name) {
    case "search_flights":
      return JSON.stringify({ flights: ["18:05", "19:40", "20:55"].map((t, i) => ({
        flight: `AX${300 + i * 111}`, origin: args.origin, destination: args.destination, departs: `2026-10-18 ${t}`, seats_left: 3 + i * 2 })) });
    case "rebook_passenger":
      return JSON.stringify({ status: "confirmed", booking_ref: args.booking_ref, flight: args.flight_number });
    case "baggage_policy":
      return JSON.stringify({ fare_class: args.fare_class, policy: BAGGAGE[args.fare_class] ?? BAGGAGE.light });
    default:
      return JSON.stringify({ error: `unknown tool ${name}` });
  }
}
