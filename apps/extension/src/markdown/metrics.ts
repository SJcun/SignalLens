/**
 * 通过“表头行 + 分隔行”统计 Markdown 中的 GFM 管道表格。
 * 围栏代码块内的管道符不是表格，必须排除。
 */
export function countMarkdownTables(markdown: string): number {
  let tables = 0;
  let previousTableRow = false;
  let fenceCharacter = '';
  let fenceLength = 0;

  for (const line of markdown.split('\n')) {
    const fence = line.match(/^\s{0,3}(```+|~~~+)/)?.[1] ?? '';
    if (fence) {
      if (!fenceCharacter) {
        fenceCharacter = fence[0];
        fenceLength = fence.length;
      } else if (fence[0] === fenceCharacter && fence.length >= fenceLength) {
        fenceCharacter = '';
        fenceLength = 0;
      }
      previousTableRow = false;
      continue;
    }

    const isTableRow = !fenceCharacter && /^\s*\|.*\|\s*$/.test(line);
    const isDelimiterRow = isTableRow && /^\s*\|(?:\s*:?-{3,}:?\s*\|)+\s*$/.test(line);
    if (isDelimiterRow && previousTableRow) tables++;
    previousTableRow = isTableRow && !isDelimiterRow;
  }

  return tables;
}
