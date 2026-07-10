/**
 * <ExampleActions /> — registers client-side actions the LLM can call.
 *
 * Each `useCopilotAction` describes one operation the LLM may invoke
 * by name. Parameters are validated against the declared schema before
 * the handler runs.
 *
 * Pattern: keep handlers thin — push business logic into hooks/services.
 *
 * Spec: docs/classes/ExampleActions.md
 */
"use client";

import { useCopilotAction } from "@copilotkit/react-core";
import type { Todo } from "../ChatPanel";

interface Props {
  todos: Todo[];
  addTodo: (text: string) => void;
  removeTodo: (id: string) => void;
}

export function ExampleActions({ todos, addTodo, removeTodo }: Props) {
  useCopilotAction({
    name: "addTodo",
    description: "Add a new todo to the user's list.",
    parameters: [
      {
        name: "text",
        type: "string",
        description: "What needs to be done.",
        required: true,
      },
    ],
    handler: async ({ text }: { text: string }) => {
      addTodo(text);
      return { ok: true, message: `Added "${text}".` };
    },
  });

  useCopilotAction({
    name: "removeTodo",
    description: "Remove a todo by its id.",
    parameters: [
      {
        name: "id",
        type: "string",
        description: "The id of the todo to remove.",
        required: true,
      },
    ],
    handler: async ({ id }: { id: string }) => {
      const todo = todos.find((t) => t.id === id);
      if (!todo) return { ok: false, message: `No todo with id ${id}.` };
      removeTodo(id);
      return { ok: true, message: `Removed "${todo.text}".` };
    },
  });

  return null; // pure registration component
}
