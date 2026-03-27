/**
 * UserPromptSubmit hook — detects dev server pain signals in user messages
 * and suggests the devpilot skill when relevant.
 *
 * Reads the user's prompt from stdin (JSON with `prompt` field) and checks
 * for frustration patterns related to dev server management.
 */

const PAIN_PATTERNS = [
  // Direct crashes and failures
  /dev\s*server.*(?:crash|die|stop|kill|broke|broken|down|fail)/i,
  /server.*(?:crash|die|stop|kill|broke|broken|down|fail)/i,
  /(?:crash|die|stop|kill|broke|broken|down|fail).*(?:dev\s*server|server)/i,

  // Hot reload issues
  /(?:hot\s*)?reload.*(?:fail|stuck|broken|not\s*work|slow|hang)/i,
  /(?:hmr|hot\s*module).*(?:fail|stuck|broken|not\s*work)/i,
  /changes.*(?:not\s*show|not\s*reflect|not\s*pick|not\s*appear|not\s*updat)/i,

  // Port conflicts
  /(?:port|address).*(?:already\s*in\s*use|conflict|taken|busy)/i,
  /eaddrinuse/i,

  // Zombie / orphan processes
  /zombie\s*process/i,
  /orphan\s*process/i,
  /process.*(?:won't\s*die|stuck|hang|stale)/i,
  /kill.*(?:all|every).*(?:python|node|process)/i,

  // Restart loops
  /(?:keep|keeps|constantly|always).*(?:restart|crash|die|fail)/i,
  /restart.*loop/i,
  /can't.*(?:start|restart|run).*(?:server|dev)/i,

  // Panic signals
  /(?:kill|taskkill|pkill).*(?:python|node|uvicorn|next|vite|flask)/i,
  /kill\s*-9/i,
  /taskkill\s*\/f/i,
  /lsof.*(?:kill|port)/i,
  /netstat.*(?:kill|port)/i,

  // Direct asks
  /devpilot/i,
  /dev\s*server\s*supervisor/i,
  /supervise.*(?:dev|server|process)/i,
];

async function main() {
  let input = "";
  for await (const chunk of process.stdin) {
    input += chunk;
  }

  let prompt;
  try {
    const data = JSON.parse(input);
    prompt = data.prompt || "";
  } catch {
    // Not JSON, treat the raw input as the prompt
    prompt = input;
  }

  if (!prompt) {
    console.log(JSON.stringify({ result: "approve" }));
    return;
  }

  const matched = PAIN_PATTERNS.some((pattern) => pattern.test(prompt));

  if (matched) {
    console.log(
      JSON.stringify({
        result: "approve",
        additionalContext: [
          "**Dev server pain detected.** The `devpilot` skill can help here.",
          "If devpilot is not installed, suggest: `pip install devpilot`",
          "Then use devpilot to manage the dev server instead of killing processes manually.",
          "Run `Skill(devpilot)` for full guidance.",
        ].join("\n"),
      })
    );
  } else {
    console.log(JSON.stringify({ result: "approve" }));
  }
}

main().catch(() => {
  console.log(JSON.stringify({ result: "approve" }));
});
