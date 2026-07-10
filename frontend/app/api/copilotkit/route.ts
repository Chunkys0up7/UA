/**
 * CopilotKit runtime route — the bridge between the browser, the LLM,
 * and the Python backend that hosts server-side actions.
 *
 * Architecture:
 *   browser  ──►  /api/copilotkit  ──┬─►  service adapter  (the LLM call)
 *                                    └─►  Python /copilotkit_remote
 *                                         (actions, future CoAgents)
 *
 * The service adapter is selected at request time from `LLM_PROVIDER`,
 * mirroring the Python side. Same `.env` drives both processes.
 *
 *   LLM_PROVIDER=openai      → OpenAIAdapter      (needs OPENAI_API_KEY)
 *   LLM_PROVIDER=anthropic   → AnthropicAdapter   (needs ANTHROPIC_API_KEY)
 *   LLM_PROVIDER=mock|<unset> → ExperimentalEmptyAdapter
 *                              (page loads; chat won't return a model
 *                               response — set a real provider to enable
 *                               chat. Server-side actions still work.)
 *
 * Spec: docs/classes/RuntimeRoute.md
 */
import {
  AnthropicAdapter,
  CopilotRuntime,
  ExperimentalEmptyAdapter,
  OpenAIAdapter,
  copilotRuntimeNextJSAppRouterEndpoint,
  type CopilotServiceAdapter,
} from "@copilotkit/runtime";
import { NextRequest } from "next/server";

const BACKEND_URL =
  process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000";

const runtime = new CopilotRuntime({
  remoteEndpoints: [{ url: `${BACKEND_URL}/copilotkit_remote` }],
});

function buildServiceAdapter(): CopilotServiceAdapter {
  const provider = (process.env.LLM_PROVIDER || "mock").toLowerCase();
  const model = process.env.LLM_MODEL;

  if (provider === "openai") {
    if (!process.env.OPENAI_API_KEY) {
      console.warn(
        "[copilotkit] LLM_PROVIDER=openai but OPENAI_API_KEY is not set. " +
          "Falling back to ExperimentalEmptyAdapter; chat will not produce model responses.",
      );
      return new ExperimentalEmptyAdapter();
    }
    return new OpenAIAdapter({ model: model || "gpt-4o-mini" });
  }

  if (provider === "anthropic") {
    if (!process.env.ANTHROPIC_API_KEY) {
      console.warn(
        "[copilotkit] LLM_PROVIDER=anthropic but ANTHROPIC_API_KEY is not set. " +
          "Falling back to ExperimentalEmptyAdapter; chat will not produce model responses.",
      );
      return new ExperimentalEmptyAdapter();
    }
    return new AnthropicAdapter({ model: model || "claude-sonnet-4-6" });
  }

  // mock / unknown — page loads; chat is a no-op until a real provider is wired.
  return new ExperimentalEmptyAdapter();
}

export const POST = async (req: NextRequest) => {
  const { handleRequest } = copilotRuntimeNextJSAppRouterEndpoint({
    runtime,
    serviceAdapter: buildServiceAdapter(),
    endpoint: "/api/copilotkit",
  });
  return handleRequest(req);
};
