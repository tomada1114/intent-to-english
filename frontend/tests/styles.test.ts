import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const styles = readFileSync("src/styles.css", "utf8");
const direction = readFileSync("../docs/design/design-direction.md", "utf8");
const reference =
  direction
    .split("## Tokens (Tailwind CSS 4)")[1]
    ?.match(/```css\n([\s\S]*?)\n```/)?.[1] ?? "";
const colorNames =
  "canvas surface line line-strong field-edge ink ink-muted ink-subtle on-ink ink-edge partner partner-edge partner-ink coach coach-edge marker miss miss-tint improve improve-tint success success-tint danger danger-tint danger-edge badge badge-ink focus".split(
    " ",
  );

function normalize(value: string): string {
  return value
    .replace(/\s+/g, " ")
    .replace(/\s*([(),])\s*/g, "$1")
    .trim();
}

function themeTokens(source: string): Map<string, string> {
  const block = source.match(/@theme\s*\{([\s\S]*?)\}/)?.[1] ?? "";
  return new Map(
    Array.from(
      block.matchAll(/(--[\w-]+)\s*:\s*([^;]+);/g),
      (match): [string, string] => [match[1] ?? "", normalize(match[2] ?? "")],
    ),
  );
}

describe("the approved Tailwind tokens", () => {
  it("keeps the import, OS color scheme and theme in order without a probe", () => {
    expect(styles).toMatch(
      /^@import "tailwindcss";\s*:root\s*\{\s*color-scheme:\s*light dark;\s*\}\s*@theme\s*\{/,
    );
    expect(styles).not.toMatch(/@source\s+inline/);
    expect(styles).not.toMatch(/--color-\*:\s*initial/);
  });

  it("pins every name and value to the design direction after whitespace normalization", () => {
    const actual = themeTokens(styles);
    const expected = themeTokens(reference);
    const names = [
      ...colorNames.map((name) => `--color-${name}`),
      "--font-sans",
      "--font-en",
      "--radius-panel",
      "--radius-slot",
    ];
    expect(Array.from(expected.keys()).sort()).toEqual([...names].sort());
    expect(Array.from(actual.keys()).sort()).toEqual([...names].sort());
    for (const name of names) {
      expect(actual.get(name), name).toBe(expected.get(name));
    }
  });

  it("keeps all 28 colors as explicit light and dark pairs", () => {
    const colors = Array.from(themeTokens(styles)).filter(([name]) =>
      name.startsWith("--color-"),
    );
    expect(colors).toHaveLength(28);
    for (const [name, value] of colors) {
      expect(value, name).toMatch(/^light-dark\(#[\da-f]{6},#[\da-f]{6}\)$/);
    }
  });

  it("treats rewrapped font lists as equal while retaining their quoted family names", () => {
    const original = '@theme { --font-sans: "Hiragino Sans", system-ui, sans-serif; }';
    const wrapped =
      '@theme {\n --font-sans:\n "Hiragino Sans",\n system-ui,\n sans-serif;\n}';
    expect(themeTokens(wrapped)).toEqual(themeTokens(original));
  });
});
