import { AzureOpenAI } from "openai";
import { OpenAIProvider } from "./openai.js";

// Same punchline as in Python: once you have the OpenAI adapter, Azure is a constructor.
// `model` is your DEPLOYMENT name.
export class AzureOpenAIProvider extends OpenAIProvider {
  override readonly name = "azure";

  constructor(opts: { apiKey: string; endpoint: string; apiVersion: string; timeoutMs?: number; team?: string; keyHeader?: string }) {
    super({
      apiKey: opts.apiKey,
      client: new AzureOpenAI({
        apiKey: opts.apiKey,
        endpoint: opts.endpoint,
        apiVersion: opts.apiVersion,
        timeout: opts.timeoutMs ?? 30_000,
        maxRetries: 0,
        defaultHeaders: {
          "x-asyncair-team": opts.team ?? "anonymous",
          // an AI gateway in front of Foundry may want the key under another header name
          ...(opts.keyHeader ? { [opts.keyHeader]: opts.apiKey } : {}),
        },
      }),
    });
  }
}
