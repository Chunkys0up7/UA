/**
 * Unit tests for the useTodos hook. Tested in isolation from CopilotKit
 * — the hook is pure local state and shouldn't depend on the runtime.
 */
import { describe, it, expect } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useTodos } from "@/lib/readables";

describe("useTodos", () => {
  it("starts empty", () => {
    const { result } = renderHook(() => useTodos());
    expect(result.current.todos).toEqual([]);
  });

  it("adds a todo", () => {
    const { result } = renderHook(() => useTodos());
    act(() => result.current.addTodo("ship it"));
    expect(result.current.todos).toHaveLength(1);
    expect(result.current.todos[0].text).toBe("ship it");
    expect(result.current.todos[0].done).toBe(false);
  });

  it("removes a todo by id", () => {
    const { result } = renderHook(() => useTodos());
    act(() => result.current.addTodo("first"));
    const id = result.current.todos[0].id;
    act(() => result.current.removeTodo(id));
    expect(result.current.todos).toEqual([]);
  });

  it("toggles done state", () => {
    const { result } = renderHook(() => useTodos());
    act(() => result.current.addTodo("toggle me"));
    const id = result.current.todos[0].id;
    act(() => result.current.toggleTodo(id));
    expect(result.current.todos[0].done).toBe(true);
    act(() => result.current.toggleTodo(id));
    expect(result.current.todos[0].done).toBe(false);
  });
});
