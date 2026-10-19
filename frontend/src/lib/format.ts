/** Dates and counts as the Japanese UI shows them (ux-guidelines § Language and copy). */

const numberFormat = new Intl.NumberFormat("ja-JP");
const startFormat = new Intl.DateTimeFormat("ja-JP", {
  month: "numeric",
  day: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  hourCycle: "h23",
});

/** A count with ja-JP grouping: 「1,000」. */
export function formatCount(value: number): string {
  return numberFormat.format(value);
}

/** The local start time as 「M/D HH:mm」. */
export function formatStart(iso: string): string {
  return startFormat.format(new Date(iso));
}
