import Anthropic from "@anthropic-ai/sdk";
import { BadRequest, ProviderUnavailable, RateLimited } from "./errors.js";
import type { Capability, ChatRequest, ChatResponse, LLMProvider, StopReason, StreamEvent, ToolCall } from "./types.js";

const STOP: Record<string, StopReason> = { end_turn: "end", tool_use: "tool_use", max_tokens: "max_tokens", stop_sequence: "end" };

export class AnthropicProvider implements LLMProvider {
  readonly name = "anthropic";
  readonly capabilities: ReadonlySet<Capability> = new Set(["tools", "vision", "streaming"]);
  private client: Anthropic;

  constructor(opts: { apiKey: string; baseURL?: string; timeoutMs?: number; team?: string }) {
    this.client = new Anthropic({
      apiKey: opts.apiKey,
      baseURL: opts.baseURL,
      timeout: opts.timeoutMs ?? 30_000,
      maxRetries: 0, // the router owns retries
      defaultHeaders: { "x-asyncair-team": opts.team ?? "anonymous" },
    });
  }

  private params(req: ChatRequest, model: string): Anthropic.MessageCreateParamsNonStreaming {
    const messages: Anthropic.MessageParam[] = req.messages.map((m) => ({
      role: m.role,
      content: m.parts.map((p): Anthropic.ContentBlockParam => {
        switch (p.type) {
          case "text": return { type: "text", text: p.text };
          case "image": return { type: "image", source: { type: "base64", media_type: p.mediaType as "image/png", data: p.dataB64 } };
          case "tool_call": return { type: "tool_use", id: p.id, name: p.name, input: p.arguments };
          case "tool_result": return { type: "tool_result", tool_use_id: p.toolCallId, content: p.content, is_error: p.isError };
        }
      }),
    }));
    return {
      model,
      max_tokens: req.maxTokens ?? 1024, // required by Anthropic
      messages,
      ...(req.system ? { system: req.system } : {}),
      ...(req.tools?.length
        ? { tools: req.tools.map((t) => ({ name: t.name, description: t.description, input_schema: t.parameters as Anthropic.Tool.InputSchema })) }
        : {}),
      ...(req.temperature !== undefined ? { temperature: req.temperature } : {}),
    };
  }

  private toNeutral(msg: Anthropic.Message, model: string, latencyMs: number): ChatResponse {
    const text = msg.content.flatMap((b) => (b.type === "text" ? [b.text] : [])).join("");
    const toolCalls: ToolCall[] = msg.content.flatMap((b) =>
      b.type === "tool_use" ? [{ type: "tool_call" as const, id: b.id, name: b.name, arguments: b.input as Record<string, unknown> }] : [],
    );
    return {
      text, toolCalls, stopReason: STOP[msg.stop_reason ?? ""] ?? "other",
      usage: { inputTokens: msg.usage.input_tokens, outputTokens: msg.usage.output_tokens },
      provider: this.name, model, latencyMs, attempts: [],
    };
  }

  private mapError(e: unknown): unknown {
    if (e instanceof Anthropic.RateLimitError) return new RateLimited(this.name, e.message);
    if (e instanceof Anthropic.APIConnectionError) return new ProviderUnavailable(this.name, `connection/timeout: ${e.message}`);
    if (e instanceof Anthropic.APIError) {
      const status = e.status ?? 0; // mid-stream errors have no (or a 200) status
      return status >= 400 && status < 500 ? new BadRequest(this.name, e.message) : new ProviderUnavailable(this.name, e.message);
    }
    return e;
  }

  async chat(req: ChatRequest, model: string): Promise<ChatResponse> {
    const t0 = performance.now();
    try {
      const msg = await this.client.messages.create(this.params(req, model));
      return this.toNeutral(msg, model, Math.round(performance.now() - t0));
    } catch (e) {
      throw this.mapError(e);
    }
  }

  async *stream(req: ChatRequest, model: string): AsyncGenerator<StreamEvent> {
    const t0 = performance.now();
    try {
      const s = this.client.messages.stream(this.params(req, model));
      for await (const ev of s) {
        if (ev.type === "content_block_delta" && ev.delta.type === "text_delta") yield { type: "text", text: ev.delta.text };
      }
      yield { type: "done", response: this.toNeutral(await s.finalMessage(), model, Math.round(performance.now() - t0)) };
    } catch (e) {
      throw this.mapError(e);
    }
  }
}
