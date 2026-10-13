import OpenAI from "openai";
import { BadRequest, ProviderUnavailable, RateLimited } from "./errors.js";
import type { Capability, ChatRequest, ChatResponse, LLMProvider, StopReason, StreamEvent, ToolCall } from "./types.js";

type ChatMsg = OpenAI.Chat.Completions.ChatCompletionMessageParam;
const FINISH: Record<string, StopReason> = { stop: "end", tool_calls: "tool_use", length: "max_tokens" };

export class OpenAIProvider implements LLMProvider {
  readonly name: string = "openai";
  readonly capabilities: ReadonlySet<Capability> = new Set(["tools", "vision", "streaming"]);
  protected client: OpenAI;

  constructor(opts: { apiKey: string; baseURL?: string; timeoutMs?: number; team?: string; client?: OpenAI }) {
    this.client = opts.client ?? new OpenAI({
      apiKey: opts.apiKey,
      baseURL: opts.baseURL,
      timeout: opts.timeoutMs ?? 30_000,
      maxRetries: 0,
      defaultHeaders: { "x-asyncair-team": opts.team ?? "anonymous" },
    });
  }

  static toOpenAIMessages(req: ChatRequest): ChatMsg[] {
    const out: ChatMsg[] = req.system ? [{ role: "system", content: req.system }] : []; // system = first message
    for (const m of req.messages) {
      if (m.role === "assistant") {
        const text = m.parts.flatMap((p) => (p.type === "text" ? [p.text] : [])).join("");
        const calls = m.parts.filter((p): p is ToolCall => p.type === "tool_call");
        out.push({
          role: "assistant",
          content: text || null,
          ...(calls.length
            ? { tool_calls: calls.map((c) => ({ id: c.id, type: "function" as const, function: { name: c.name, arguments: JSON.stringify(c.arguments) } })) }
            : {}),
        });
        continue;
      }
      for (const p of m.parts) {
        if (p.type === "tool_result") out.push({ role: "tool", tool_call_id: p.toolCallId, content: p.content }); // one message per result
      }
      const content: OpenAI.Chat.Completions.ChatCompletionContentPart[] = [];
      for (const p of m.parts) {
        if (p.type === "text") content.push({ type: "text", text: p.text });
        if (p.type === "image") content.push({ type: "image_url", image_url: { url: `data:${p.mediaType};base64,${p.dataB64}` } });
      }
      if (content.length) out.push({ role: "user", content });
    }
    return out;
  }

  private params(req: ChatRequest, model: string) {
    return {
      model,
      messages: OpenAIProvider.toOpenAIMessages(req),
      max_completion_tokens: req.maxTokens ?? 1024,
      ...(req.tools?.length
        ? { tools: req.tools.map((t) => ({ type: "function" as const, function: { name: t.name, description: t.description, parameters: t.parameters } })) }
        : {}),
      ...(req.temperature !== undefined ? { temperature: req.temperature } : {}),
    };
  }

  protected mapError(e: unknown): unknown {
    if (e instanceof OpenAI.RateLimitError) return new RateLimited(this.name, e.message);
    if (e instanceof OpenAI.APIConnectionError) return new ProviderUnavailable(this.name, `connection/timeout: ${e.message}`);
    if (e instanceof OpenAI.APIError) {
      const status = e.status ?? 0; // mid-stream errors have no (or a 200) status
      return status >= 400 && status < 500 ? new BadRequest(this.name, e.message) : new ProviderUnavailable(this.name, e.message);
    }
    return e;
  }

  async chat(req: ChatRequest, model: string): Promise<ChatResponse> {
    const t0 = performance.now();
    try {
      const r = await this.client.chat.completions.create(this.params(req, model));
      const choice = r.choices[0];
      const toolCalls: ToolCall[] = (choice.message.tool_calls ?? []).flatMap((tc) =>
        tc.type === "function"
          ? [{ type: "tool_call" as const, id: tc.id, name: tc.function.name, arguments: JSON.parse(tc.function.arguments || "{}") }]
          : [],
      );
      return {
        text: choice.message.content ?? "", toolCalls, stopReason: FINISH[choice.finish_reason] ?? "other",
        usage: { inputTokens: r.usage?.prompt_tokens ?? 0, outputTokens: r.usage?.completion_tokens ?? 0 },
        provider: this.name, model, latencyMs: Math.round(performance.now() - t0), attempts: [],
      };
    } catch (e) {
      throw this.mapError(e);
    }
  }

  async *stream(req: ChatRequest, model: string): AsyncGenerator<StreamEvent> {
    const t0 = performance.now();
    let text = "";
    let finish = "";
    let usage = { inputTokens: 0, outputTokens: 0 };
    const calls = new Map<number, { id: string; name: string; args: string }>();
    try {
      const s = await this.client.chat.completions.create({ ...this.params(req, model), stream: true, stream_options: { include_usage: true } });
      for await (const chunk of s) {
        if (chunk.usage) usage = { inputTokens: chunk.usage.prompt_tokens, outputTokens: chunk.usage.completion_tokens };
        const choice = chunk.choices[0];
        if (!choice) continue;
        if (choice.delta.content) {
          text += choice.delta.content;
          yield { type: "text", text: choice.delta.content };
        }
        for (const tc of choice.delta.tool_calls ?? []) { // tool calls arrive in fragments
          const slot = calls.get(tc.index) ?? { id: "", name: "", args: "" };
          slot.id = tc.id ?? slot.id;
          slot.name = tc.function?.name ?? slot.name;
          slot.args += tc.function?.arguments ?? "";
          calls.set(tc.index, slot);
        }
        finish = choice.finish_reason ?? finish;
      }
    } catch (e) {
      throw this.mapError(e);
    }
    yield {
      type: "done",
      response: {
        text,
        toolCalls: [...calls.values()].map((c) => ({ type: "tool_call" as const, id: c.id, name: c.name, arguments: JSON.parse(c.args || "{}") })),
        stopReason: FINISH[finish] ?? "other", usage, provider: this.name, model,
        latencyMs: Math.round(performance.now() - t0), attempts: [],
      },
    };
  }
}
