// Provider-neutral types - the TypeScript twin of rebookr/llm/types.py.
// Discriminated unions do the job that dataclasses do in Python.

export type Part =
  | { type: "text"; text: string }
  | { type: "image"; mediaType: string; dataB64: string }
  | { type: "tool_call"; id: string; name: string; arguments: Record<string, unknown> }
  | { type: "tool_result"; toolCallId: string; content: string; isError?: boolean };

export interface Message {
  role: "user" | "assistant";
  parts: Part[];
}

export interface ToolSpec {
  name: string;
  description: string;
  parameters: Record<string, unknown>; // JSON Schema
}

export interface ChatRequest {
  messages: Message[];
  system?: string;
  tools?: ToolSpec[];
  maxTokens?: number;
  temperature?: number;
}

export type ToolCall = Extract<Part, { type: "tool_call" }>;
export type StopReason = "end" | "tool_use" | "max_tokens" | "other";

export interface ChatResponse {
  text: string;
  toolCalls: ToolCall[];
  stopReason: StopReason;
  usage: { inputTokens: number; outputTokens: number };
  provider: string;
  model: string;
  latencyMs: number;
  attempts: string[];
}

export type StreamEvent = { type: "text"; text: string } | { type: "done"; response: ChatResponse };

export type Capability = "tools" | "vision" | "streaming";

export interface LLMProvider {
  readonly name: string;
  readonly capabilities: ReadonlySet<Capability>;
  chat(req: ChatRequest, model: string): Promise<ChatResponse>;
  stream(req: ChatRequest, model: string): AsyncGenerator<StreamEvent>;
}

export const userText = (text: string): Message => ({ role: "user", parts: [{ type: "text", text }] });
export const needsVision = (req: ChatRequest) => req.messages.some((m) => m.parts.some((p) => p.type === "image"));

export function asMessage(r: ChatResponse): Message {
  const parts: Part[] = r.text ? [{ type: "text", text: r.text }] : [];
  return { role: "assistant", parts: [...parts, ...r.toolCalls] };
}
