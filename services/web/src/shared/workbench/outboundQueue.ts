/** Merge queued composer messages into one turn input (docs/10 follow-up). */
export function mergeOutboundQueue(items: string[]): string {
  return items
    .map((item) => item.trim())
    .filter(Boolean)
    .join("\n\n");
}
