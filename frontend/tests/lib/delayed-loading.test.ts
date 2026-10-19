import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { settleAfterMinimum, useDelayedLoading } from "../../src/lib/delayed-loading";

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

describe("settleAfterMinimum", () => {
  function respondAfter(ms: number) {
    return () =>
      new Promise<string>((resolve) => {
        setTimeout(() => resolve("result"), ms);
      });
  }

  it.each([
    { respondsAt: 299, settlesAt: 299 },
    { respondsAt: 301, settlesAt: 800 },
    { respondsAt: 900, settlesAt: 900 },
  ])(
    "settles a response at $respondsAt ms at $settlesAt ms",
    async ({ respondsAt, settlesAt }) => {
      const start = Date.now();
      let settled: number | null = null;
      void settleAfterMinimum(respondAfter(respondsAt)).then(() => {
        settled = Date.now() - start;
      });

      await vi.advanceTimersByTimeAsync(settlesAt - 1);
      expect(settled).toBeNull();
      await vi.advanceTimersByTimeAsync(1);

      expect(settled).toBe(settlesAt);
    },
  );

  it("holds a failure the same way and rejects with it", async () => {
    const start = Date.now();
    let failed: { at: number; error: unknown } | null = null;
    void settleAfterMinimum(
      () =>
        new Promise((_, reject) => {
          setTimeout(() => reject(new Error("no response")), 400);
        }),
    ).catch((error: unknown) => {
      failed = { at: Date.now() - start, error };
    });

    await vi.advanceTimersByTimeAsync(799);
    expect(failed).toBeNull();
    await vi.advanceTimersByTimeAsync(1);

    expect(failed).toEqual({ at: 800, error: new Error("no response") });
  });
});
