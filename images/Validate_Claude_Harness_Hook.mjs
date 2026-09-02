import {readFileSync} from "node:fs";
import {resolve} from "node:path";
import {spawnSync} from "node:child_process";

function fail(message) {
  process.stderr.write(`Claude Harness hook validation failed: ${message}\n`);
  process.exit(1);
}

const pluginRoot = resolve(process.argv[2] ?? "");
let configuration;
try {
  configuration = JSON.parse(
    readFileSync(resolve(pluginRoot, "hooks", "hooks.json"), "utf8"),
  );
} catch (error) {
  fail(`could not read hooks.json: ${error.message}`);
}

const handlers = (configuration?.hooks?.UserPromptSubmit ?? [])
  .flatMap((group) => group?.hooks ?? [])
  .filter((handler) => handler?.type === "command");
if (handlers.length !== 1) {
  fail(`expected one UserPromptSubmit command hook, found ${handlers.length}`);
}

const handler = handlers[0];
if (typeof handler.command !== "string" || !Array.isArray(handler.args)) {
  fail("command hook must declare a command and argument list");
}

const expandPluginRoot = (value) =>
  value.replaceAll("${CLAUDE_PLUGIN_ROOT}", pluginRoot);
const command = expandPluginRoot(handler.command);
const args = handler.args.map((argument) => {
  if (typeof argument !== "string") fail("hook arguments must be strings");
  return expandPluginRoot(argument);
});
const timeout =
  Number.isFinite(handler.timeout) && handler.timeout > 0
    ? handler.timeout * 1_000
    : 5_000;

function runHook(prompt) {
  const completed = spawnSync(command, args, {
    input: JSON.stringify({
      hook_event_name: "UserPromptSubmit",
      prompt,
    }),
    encoding: "utf8",
    env: {...process.env, CLAUDE_PLUGIN_ROOT: pluginRoot},
    timeout,
  });
  if (completed.error) {
    fail(`${command} could not start: ${completed.error.message}`);
  }
  if (completed.status !== 0) {
    fail(`${command} exited ${completed.status}: ${completed.stderr.trim()}`);
  }
  if (completed.stderr !== "") {
    fail(`${command} wrote to stderr: ${completed.stderr.trim()}`);
  }
  return completed.stdout;
}

if (runHook("Change this button color.") !== "") {
  fail("ordinary prompt unexpectedly activated Harness execute");
}

let payload;
try {
  payload = JSON.parse(
    runHook(
      "Read /app/Routing_Request.json and write a complete blocked " +
        "HarnessResult to /app/Harness_Result.json.",
    ),
  );
} catch (error) {
  fail(`explicit contract returned invalid JSON: ${error.message}`);
}

const output = payload?.hookSpecificOutput;
const context = output?.additionalContext;
if (output?.hookEventName !== "UserPromptSubmit" || typeof context !== "string") {
  fail("explicit contract returned no UserPromptSubmit additionalContext");
}
if (
  !context.includes("/harness:execute") ||
  !context.includes("`route.fallback_reason`") ||
  !context.includes("path:<absolute-path>")
) {
  fail("activation context omits required Harness contract guidance");
}
if (Buffer.byteLength(context) >= 4_000) {
  fail("activation context exceeds the 4,000-byte benchmark ceiling");
}
