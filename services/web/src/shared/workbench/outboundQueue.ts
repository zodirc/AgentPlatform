/**
 * 出站消息队列：回合进行中暂存用户输入，空闲后合并发送。
 * @see docs/10 follow-up
 */

/**
 * 将排队中的多条 composer 消息合并为一条回合输入。
 * @param items 待发送的原始消息列表
 * @returns 去空白后以双换行拼接的合并文本
 */
export function mergeOutboundQueue(items: string[]): string {
  return items
    .map((item) => item.trim())
    .filter(Boolean)
    .join("\n\n");
}
