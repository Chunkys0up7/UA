/**
 * <ChatPanel /> — small surface that exposes app state to the LLM and
 * lists today's todos for the human.
 *
 * Uses `useCopilotReadable` to give the LLM a description + the live
 * value of `todos`. The LLM can read it on every turn; the user never
 * sees this — it's pure context.
 *
 * Spec: docs/classes/ChatPanel.md
 */
"use client";

import { useCopilotReadable } from "@copilotkit/react-core";

export interface Todo {
  id: string;
  text: string;
  done: boolean;
}

export function ChatPanel({ todos }: { todos: Todo[] }) {
  useCopilotReadable({
    description:
      "The user's current todo list. Each item has an id, text, and done flag.",
    value: todos,
  });

  return (
    <section className="panel">
      <h2 style={{ margin: "0 0 12px", fontSize: 18 }}>Todos</h2>
      {todos.length === 0 ? (
        <p style={{ margin: 0 }}>None yet — ask the copilot to add one.</p>
      ) : (
        <ul style={{ paddingLeft: 18, margin: 0 }}>
          {todos.map((t) => (
            <li
              key={t.id}
              style={{
                opacity: t.done ? 0.5 : 1,
                textDecoration: t.done ? "line-through" : "none",
              }}
            >
              {t.text}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
