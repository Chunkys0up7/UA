/**
 * Module-level AG-UI agent instances.
 *
 * Why module-level singletons instead of useMemo inside the provider:
 * 1. The same instances are registered with <CopilotKit> (hooks subscribe to
 *    them for state/interrupt events) AND imported by pages that need to
 *    start runs directly.
 * 2. DEVIATION D-P0-1 (see DEVIATIONS.md): @copilotkit/react-core 1.57–1.62
 *    returns `run`/`start` from useCoAgent as UNBOUND method references
 *    (`start: agent.runAgent`), which crashes HttpAgent with
 *    "Cannot set properties of undefined (setting 'abortController')".
 *    Pages therefore call `underwriterAgent.runAgent(...)` (bound) directly.
 *    The resume payload schema is unchanged (specs/schemas/interrupt-resume).
 */
import { HttpAgent } from "@ag-ui/client";

const BACKEND_URL =
  process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000";

export const defaultAgent = new HttpAgent({
  url: `${BACKEND_URL}/agent/default`,
});

export const underwriterAgent = new HttpAgent({
  url: `${BACKEND_URL}/agent/underwriter`,
});

export const agentRegistry = {
  default: defaultAgent,
  underwriter: underwriterAgent,
} as const;
