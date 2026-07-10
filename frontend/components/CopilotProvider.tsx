/**
 * <CopilotProvider /> — wraps the app in <CopilotKit /> context.
 *
 * Configuration:
 *   - runtimeUrl points at /api/copilotkit (Next route → Python actions).
 *   - agents__unsafe_dev_only registers a "default" HttpAgent that POSTs
 *     directly to the Python backend's /agent/default endpoint, which
 *     hosts our LangGraph CoAgent over the AG-UI protocol.
 *
 * Why HttpAgent + agents__unsafe_dev_only instead of letting CopilotKit
 * discover the agent via the runtime's /info endpoint?
 *
 *   The copilotkit Python SDK 0.1.88's LangGraphAGUIAgent bridge is
 *   broken (missing super().dict_repr() and agent.execute() methods).
 *   Bypassing it with a direct AG-UI HttpAgent is the cleanest path
 *   until that's fixed upstream. The actions runtime still flows
 *   through /api/copilotkit normally.
 *
 * Spec: docs/classes/CopilotProvider.md
 */
"use client";

import { CopilotKit } from "@copilotkit/react-core";
import { type ReactNode } from "react";
import { agentRegistry } from "@/lib/agents";

const RUNTIME_URL = "/api/copilotkit";

export function CopilotProvider({ children }: { children: ReactNode }) {
  // Module-level singletons (lib/agents.ts) so pages can call
  // agent.runAgent() bound — see DEVIATION D-P0-1.
  const agents = agentRegistry;

  return (
    <CopilotKit
      runtimeUrl={RUNTIME_URL}
      agents__unsafe_dev_only={agents}
    >
      {children}
    </CopilotKit>
  );
}
