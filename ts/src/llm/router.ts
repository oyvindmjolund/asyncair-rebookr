import { AllProvidersFailed, LLMError, StreamInterrupted } from "./errors.js";
import { needsVision, type ChatRequest, type ChatResponse, type LLMProvider, type StreamEvent } from "./types.js";

export interface RouterConfig {
  providers: Record<string, Record<string, string>>;      // provider -> alias -> model
  routes: Record<string, { chain: string[] }>;
  resilience?: { breaker_failures?: number; breaker_cooldown_seconds?: number };
}

class CircuitBreaker {
  private failures = 0;
  private openedAt: number | null = null;
  constructor(private readonly threshold: number, private readonly cooldownMs: number) {}
  isOpen(): boolean {
    if (this.openedAt === null) return false;
    if (Date.now() - this.openedAt >= this.cooldownMs) {
      this.openedAt = null; // half-open
      this.failures = this.threshold - 1;
      return false;
    }
    return true;
  }
  success() { this.failures = 0; this.openedAt = null; }
  failure() { if (++this.failures >= this.threshold) this.openedAt = Date.now(); }
}

export class ModelRouter {
  private breakers = new Map<string, CircuitBreaker>();

  constructor(
    private readonly providers: Record<string, LLMProvider>,
    private readonly cfg: RouterConfig,
    private readonly log: (msg: string) => void = () => {},
  ) {
    const r = cfg.resilience ?? {};
    for (const name of Object.keys(providers)) {
      this.breakers.set(name, new CircuitBreaker(r.breaker_failures ?? 3, (r.breaker_cooldown_seconds ?? 30) * 1000));
    }
  }

  private *candidates(route: string, req: ChatRequest, attempts: string[]) {
    const chain = this.cfg.routes[route]?.chain;
    if (!chain) throw new Error(`Unknown route '${route}'`);
    for (const entry of chain) {
      const [name, alias] = entry.split(":");
      const provider = this.providers[name];
      if (!provider) { attempts.push(`${name}: not configured`); continue; }
      if (this.breakers.get(name)!.isOpen()) { attempts.push(`${name}: circuit open`); this.log(`⏭  ${name} skipped (circuit open)`); continue; }
      if (needsVision(req) && !provider.capabilities.has("vision")) { attempts.push(`${name}: no vision`); continue; }
      yield { name, provider, model: this.cfg.providers[name][alias] };
    }
  }

  private fail(name: string, e: unknown, attempts: string[]) {
    if (e instanceof LLMError && !e.retryable) throw e; // our bug: falling back won't help
    if (!(e instanceof LLMError)) throw e;
    this.breakers.get(name)!.failure();
    attempts.push(`${name}: ${e.name}`);
    this.log(`✗  ${name} failed: ${e.name} -> falling back`);
  }

  async chat(req: ChatRequest, route = "rebooking"): Promise<ChatResponse> {
    const attempts: string[] = [];
    for (const { name, provider, model } of this.candidates(route, req, attempts)) {
      try {
        const r = await provider.chat(req, model);
        this.breakers.get(name)!.success();
        attempts.push(`${name}: ok`);
        return { ...r, attempts };
      } catch (e) {
        this.fail(name, e, attempts);
      }
    }
    throw new AllProvidersFailed(route, attempts);
  }

  /** Fallback only before the first token reaches the user. */
  async *stream(req: ChatRequest, route = "rebooking"): AsyncGenerator<StreamEvent> {
    const attempts: string[] = [];
    for (const { name, provider, model } of this.candidates(route, req, attempts)) {
      let emitted = false;
      try {
        for await (const ev of provider.stream(req, model)) {
          if (ev.type === "text") emitted = true;
          if (ev.type === "done") {
            this.breakers.get(name)!.success();
            attempts.push(`${name}: ok`);
            yield { type: "done", response: { ...ev.response, attempts } };
          } else yield ev;
        }
        return;
      } catch (e) {
        if (emitted) throw new StreamInterrupted(name, `died mid-stream: ${String(e)}`);
        this.fail(name, e, attempts);
      }
    }
    throw new AllProvidersFailed(route, attempts);
  }
}
