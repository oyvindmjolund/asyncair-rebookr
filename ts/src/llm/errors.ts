// Normalised errors - the router never sees vendor exceptions.

export class LLMError extends Error {
  readonly retryable: boolean = false;
  constructor(public readonly provider: string, message: string) {
    super(`[${provider}] ${message}`);
    this.name = new.target.name;
  }
}
export class ProviderUnavailable extends LLMError { override readonly retryable = true; }
export class RateLimited extends LLMError { override readonly retryable = true; }
export class BadRequest extends LLMError {}
export class StreamInterrupted extends LLMError {}

export class AllProvidersFailed extends Error {
  constructor(route: string, public readonly attempts: string[]) {
    super(`Route '${route}': every provider failed -> ${attempts.join(" | ")}`);
    this.name = "AllProvidersFailed";
  }
}
