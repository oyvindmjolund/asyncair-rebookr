import { existsSync, readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { parse } from "smol-toml";
import { AnthropicProvider } from "./llm/anthropic.js";
import { AzureOpenAIProvider } from "./llm/azure.js";
import { OpenAIProvider } from "./llm/openai.js";
import type { RouterConfig } from "./llm/router.js";
import type { LLMProvider } from "./llm/types.js";

// Python and TypeScript share ONE config file: ../config.toml
export const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..");

export function loadConfig() {
  const cfg = parse(readFileSync(resolve(ROOT, "config.toml"), "utf8")) as any;
  // Written by `python -m rebookr join`. Precedence: environment > .asyncair.toml > config.toml
  const localPath = resolve(ROOT, ".asyncair.toml");
  const local = existsSync(localPath) ? (parse(readFileSync(localPath, "utf8")) as any) : {};
  cfg.mode = process.env.ASYNCAIR_MODE ?? cfg.mode;
  cfg.team = process.env.ASYNCAIR_TEAM ?? local.team ?? cfg.team;
  cfg.mock.url = (process.env.MOCK_URL ?? local.mock_url ?? cfg.mock.url).replace(/\/$/, "");
  return cfg as RouterConfig & { mode: string; team: string; system_prompt: string; mock: { url: string; timeout_seconds: number }; live: { timeout_seconds: number } };
}

export function buildProviders(cfg: ReturnType<typeof loadConfig>): Record<string, LLMProvider> {
  const team = cfg.team;
  const apiVersion = (cfg.providers.azure as any).api_version as string;
  if (cfg.mode === "mock") {
    const url = cfg.mock.url, timeoutMs = cfg.mock.timeout_seconds * 1000;
    return {
      anthropic: new AnthropicProvider({ apiKey: "mock-key", baseURL: `${url}/anthropic`, timeoutMs, team }),
      openai: new OpenAIProvider({ apiKey: "mock-key", baseURL: `${url}/openai/v1`, timeoutMs, team }),
      azure: new AzureOpenAIProvider({ apiKey: "mock-key", endpoint: `${url}/azure`, apiVersion, timeoutMs, team }),
    };
  }
  const timeoutMs = cfg.live.timeout_seconds * 1000;
  const out: Record<string, LLMProvider> = {};
  const env = process.env;
  if (env.ANTHROPIC_API_KEY) out.anthropic = new AnthropicProvider({ apiKey: env.ANTHROPIC_API_KEY, timeoutMs, team });
  if (env.OPENAI_API_KEY) out.openai = new OpenAIProvider({ apiKey: env.OPENAI_API_KEY, timeoutMs, team });
  if (env.AZURE_OPENAI_API_KEY && env.AZURE_OPENAI_ENDPOINT) {
    out.azure = new AzureOpenAIProvider({ apiKey: env.AZURE_OPENAI_API_KEY, endpoint: env.AZURE_OPENAI_ENDPOINT,
      apiVersion: env.AZURE_OPENAI_API_VERSION ?? apiVersion, timeoutMs, team, keyHeader: env.AZURE_OPENAI_KEY_HEADER || undefined });
  }
  return out;
}

export const readPrompt = (rel: string) => readFileSync(resolve(ROOT, rel), "utf8");
