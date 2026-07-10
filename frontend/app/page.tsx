/**
 * Home page — demo surface.
 *
 * Demonstrates:
 *   - <CopilotSidebar />     (the chat UI)
 *   - useCopilotReadable     (exposes app state to the LLM)
 *   - useCopilotAction       (lets the LLM call into client-side code)
 *
 * Spec: docs/classes/HomePage.md
 */
"use client";

import { CopilotSidebar } from "@copilotkit/react-ui";
import { ChatPanel } from "@/components/ChatPanel";
import { ExampleActions } from "@/components/actions/ExampleActions";
import { useTodos } from "@/lib/readables";

export default function HomePage() {
  const { todos, addTodo, removeTodo } = useTodos();

  // ExampleActions registers `addTodo` & `removeTodo` as client-side
  // actions the LLM can call. Splitting them into their own component
  // keeps this page focused on layout.
  return (
    <>
      <main>
        <h1>CopilotKit Kickstarter</h1>
        <p>
          A spec-driven, provider-agnostic scaffold. Open the sidebar
          (right) and try: <code>add &quot;ship the kickstarter&quot;</code>{" "}
          or <code>get_weather London</code>.
        </p>

        <ChatPanel todos={todos} />
        <ExampleActions
          todos={todos}
          addTodo={addTodo}
          removeTodo={removeTodo}
        />
      </main>

      <CopilotSidebar
        labels={{
          title: "Kickstarter Copilot",
          initial: "Hi! Try asking me to add a todo or fetch weather.",
        }}
        defaultOpen
      />
    </>
  );
}
