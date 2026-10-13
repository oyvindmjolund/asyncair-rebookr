// npm run demo -- "My flight KRS to OSL was cancelled"     one question
// npm run demo -- --stream "..."                            streamed
// npm run storm                                             storm mode (red-button demo)
import { buildProviders, loadConfig, readPrompt } from "./config.js";
import { AllProvidersFailed, StreamInterrupted } from "./llm/errors.js";
import { ModelRouter } from "./llm/router.js";
import { asMessage, userText, type ChatResponse, type Message } from "./llm/types.js";
import { runTool, TOOLS } from "./tools.js";

const dim = (s: string) => `\x1b[2m${s}\x1b[0m`;
const cfg = loadConfig();
const router = new ModelRouter(buildProviders(cfg), cfg, (m) => console.log(dim(`   ${m}`)));
const system = readPrompt(cfg.system_prompt);

async function ask(text: string, stream: boolean): Promise<void> {
  const history: Message[] = [userText(text)];
  for (let round = 0; round < 5; round++) {
    const req = { messages: history, system, tools: TOOLS, maxTokens: 800 };
    let resp: ChatResponse | undefined;
    if (stream) {
      let printed = false;
      for await (const ev of router.stream(req, "rebooking")) {
        if (ev.type === "text") { if (!printed) process.stdout.write("\x1b[1mRebookr:\x1b[0m "); printed = true; process.stdout.write(ev.text); }
        else resp = ev.response;
      }
      if (printed) console.log();
    } else {
      resp = await router.chat(req, "rebooking");
    }
    console.log(dim(`   ↳ ${resp!.provider}/${resp!.model} ${resp!.latencyMs}ms [${resp!.attempts.join(" → ")}]`));
    history.push(asMessage(resp!));
    if (!resp!.toolCalls.length) {
      if (!stream) console.log(`\x1b[1mRebookr:\x1b[0m ${resp!.text}`);
      return;
    }
    history.push({ role: "user", parts: resp!.toolCalls.map((c) => {
      console.log(dim(`   🔧 ${c.name}(${JSON.stringify(c.arguments)})`));
      return { type: "tool_result" as const, toolCallId: c.id, content: runTool(c.name, c.arguments as Record<string, any>) };
    }) });
  }
}

async function safeAsk(text: string, stream: boolean): Promise<boolean> {
  try { await ask(text, stream); return true; }
  catch (e) {
    if (e instanceof AllProvidersFailed || e instanceof StreamInterrupted) { console.log(`\n\x1b[31m💥 ${e.message}\x1b[0m`); return false; }
    throw e;
  }
}

const args = process.argv.slice(2);
console.log(dim(`mode=${cfg.mode} team=${cfg.team} (TypeScript)`));
if (args.includes("--storm")) {
  const passengers = ["My flight KRS to OSL tonight was cancelled. Can you rebook me?", "How many bags on a plus fare?",
    "I need to get home to BGO from OSL, my flight was cancelled."];
  let ok = 0, failed = 0;
  for (let n = 1; ; n++) {
    const text = passengers[(n - 1) % passengers.length];
    console.log(`\n\x1b[1mPassenger #${n}:\x1b[0m ${text}`);
    (await safeAsk(text, false)) ? ok++ : failed++;
    console.log(dim(`   score: ${ok} helped / ${failed} stranded`));
    await new Promise((r) => setTimeout(r, 2000));
  }
} else {
  const stream = args.includes("--stream");
  const text = args.filter((a) => a !== "--stream").join(" ") || "My flight KRS to OSL tonight was cancelled. Can you rebook me?";
  process.exitCode = (await safeAsk(text, stream)) ? 0 : 1;
}
