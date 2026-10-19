import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useDelayedLoading } from "../../../src/features/sessions/hooks";

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

function render(loading: boolean) {
  return renderHook(({ pending }) => useDelayedLoading(pending), {
    initialProps: { pending: loading },
  });
}

describe("useDelayedLoading", () => {
  it("shows nothing when loading ends within 300 ms", () => {
    const hook = render(true);

    act(() => vi.advanceTimersByTime(299));
    hook.rerender({ pending: false });
    act(() => vi.advanceTimersByTime(1000));

    expect(hook.result.current).toBe(false);
  });

  it("shows the indicator once loading passes 300 ms", () => {
    const hook = render(true);

    act(() => vi.advanceTimersByTime(299));
    expect(hook.result.current).toBe(false);
    act(() => vi.advanceTimersByTime(1));

    expect(hook.result.current).toBe(true);
  });

  it("keeps a shown indicator for at least 500 ms", () => {
    const hook = render(true);
    act(() => vi.advanceTimersByTime(300));

    act(() => vi.advanceTimersByTime(100));
    hook.rerender({ pending: false });
    act(() => vi.advanceTimersByTime(399));
    expect(hook.result.current).toBe(true);
    act(() => vi.advanceTimersByTime(1));

    expect(hook.result.current).toBe(false);
  });

  it("hides an indicator shown longer than 500 ms as soon as loading ends", () => {
    const hook = render(true);
    act(() => vi.advanceTimersByTime(1000));

    hook.rerender({ pending: false });
    act(() => vi.advanceTimersByTime(0));

    expect(hook.result.current).toBe(false);
  });

  it("never shows anything when nothing is loading", () => {
    const hook = render(false);

    act(() => vi.advanceTimersByTime(1000));

    expect(hook.result.current).toBe(false);
  });
});
