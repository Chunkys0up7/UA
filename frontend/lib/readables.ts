/**
 * useTodos — local in-memory todo store.
 *
 * Trivial state hook used by the demo page. Lives separately from the
 * Copilot wiring so swapping for a real persistent store (Zustand,
 * Redux, server actions) is one drop-in change.
 *
 * Spec: docs/classes/useTodos.md
 */
"use client";

import { useState, useCallback } from "react";
import type { Todo } from "@/components/ChatPanel";

export function useTodos(initial: Todo[] = []) {
  const [todos, setTodos] = useState<Todo[]>(initial);

  const addTodo = useCallback((text: string) => {
    setTodos((curr) => [
      ...curr,
      {
        id: crypto.randomUUID(),
        text,
        done: false,
      },
    ]);
  }, []);

  const removeTodo = useCallback((id: string) => {
    setTodos((curr) => curr.filter((t) => t.id !== id));
  }, []);

  const toggleTodo = useCallback((id: string) => {
    setTodos((curr) =>
      curr.map((t) => (t.id === id ? { ...t, done: !t.done } : t)),
    );
  }, []);

  return { todos, addTodo, removeTodo, toggleTodo };
}
