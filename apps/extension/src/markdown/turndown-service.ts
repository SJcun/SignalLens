/**
 * Turndown 封装：统一配置 + 代码块语言规则 + GFM 表格处理。
 */
import { codeLanguageOf } from '../normalize/code';
import { tables } from 'turndown-plugin-gfm';

export interface TurndownLike {
  turndown(input: Node | string): string;
}

/** 将单元格内的多行 Markdown 收敛为 GFM 表格允许的单行内容。 */
function normalizeTableCell(markdown: string): string {
  return markdown
    .replace(/\r?\n+/g, ' ')
    .replace(/\s{2,}/g, ' ')
    .replace(/(?<!\\)\|/g, '\\|')
    .trim();
}

/** 读取当前表格的直接行，避免嵌套表格的行混入外层。 */
function tableRows(table: HTMLTableElement): HTMLTableRowElement[] {
  return Array.from(table.rows).filter((row) => row.closest('table') === table);
}

/** 计算连续的表头行数：优先使用 thead，否则识别顶部全 th 行。 */
function headerRowCount(table: HTMLTableElement, rows: HTMLTableRowElement[]): number {
  const theadRows = table.tHead
    ? Array.from(table.tHead.rows).filter((row) => row.closest('table') === table)
    : [];
  if (theadRows.length) return theadRows.length;

  let count = 0;
  for (const row of rows) {
    const cells = Array.from(row.cells);
    if (!cells.length || cells.some((cell) => cell.tagName !== 'TH')) break;
    count++;
  }
  return count;
}

/** 判断表格是否超出官方 GFM 规则的单表头矩形表格范围。 */
function isComplexTable(table: HTMLTableElement): boolean {
  const rows = tableRows(table);
  if (!rows.length || headerRowCount(table, rows) !== 1) return true;
  if (
    Array.from(table.querySelectorAll('th[rowspan], th[colspan], td[rowspan], td[colspan]'))
      .some((cell) => cell.closest('table') === table)
  ) {
    return true;
  }
  return new Set(rows.map((row) => row.cells.length)).size > 1;
}

/**
 * 将 rowspan / colspan 展开为矩形网格。
 * 合并单元格的内容传播到被覆盖的逻辑单元格，以保留每行的列语义。
 */
function expandTableGrid(
  table: HTMLTableElement,
  cellService: TurndownService
): { rows: string[][]; headerRows: number } {
  const sourceRows = tableRows(table);
  const grid: Array<Array<string | undefined>> = [];

  sourceRows.forEach((row, rowIndex) => {
    grid[rowIndex] ??= [];
    let columnIndex = 0;
    for (const cell of Array.from(row.cells)) {
      while (grid[rowIndex][columnIndex] !== undefined) columnIndex++;
      const value = normalizeTableCell(cellService.turndown(cell.innerHTML));
      const rowSpan = cell.rowSpan === 0 ? sourceRows.length - rowIndex : Math.max(1, cell.rowSpan);
      const columnSpan = Math.max(1, cell.colSpan);

      for (let rowOffset = 0; rowOffset < rowSpan; rowOffset++) {
        const targetRow = rowIndex + rowOffset;
        grid[targetRow] ??= [];
        for (let columnOffset = 0; columnOffset < columnSpan; columnOffset++) {
          grid[targetRow][columnIndex + columnOffset] ??= value;
        }
      }
      columnIndex += columnSpan;
    }
  });

  const width = Math.max(0, ...grid.map((row) => row.length));
  return {
    rows: grid.map((row) => Array.from({ length: width }, (_, index) => row[index] ?? '')),
    headerRows: headerRowCount(table, sourceRows),
  };
}

/** 把展开后的网格输出为单表头 GFM 表格。 */
function renderComplexTable(table: HTMLTableElement, cellService: TurndownService): string {
  const expanded = expandTableGrid(table, cellService);
  if (!expanded.rows.length || !expanded.rows[0].length) return '';

  const width = expanded.rows[0].length;
  const headers = Array.from({ length: width }, (_, columnIndex) => {
    if (!expanded.headerRows) return `列 ${columnIndex + 1}`;
    const labels = expanded.rows
      .slice(0, expanded.headerRows)
      .map((row) => row[columnIndex])
      .filter((label, index, all) => label && all.indexOf(label) === index);
    return labels.join(' / ') || `列 ${columnIndex + 1}`;
  });
  const bodyRows = expanded.rows.slice(expanded.headerRows);
  const formatRow = (cells: string[]): string => `| ${cells.join(' | ')} |`;
  const lines = [formatRow(headers), formatRow(Array(width).fill('---')), ...bodyRows.map(formatRow)];
  return `\n\n${lines.join('\n')}\n\n`;
}

export function makeTurndown(): TurndownLike {
  const service = new TurndownService({
    headingStyle: 'atx',
    codeBlockStyle: 'fenced',
    bulletListMarker: '-',
    hr: '---',
  });

  // 语义化 HTML 表格转为 GFM 管道表格，保留单元格的行列对应关系。
  tables(service);

  // 表格单元格中的管道符必须转义，多行内容需收敛为单行。
  service.addRule('safeTableCell', {
    filter: (node: Node) => node.nodeName === 'TH' || node.nodeName === 'TD',
    replacement: (content: string, node: Node) => {
      const cell = node as HTMLTableCellElement;
      const row = cell.parentElement as HTMLTableRowElement | null;
      const rowCells = row?.tagName === 'TR' ? Array.from(row.cells) : [];
      const prefix = rowCells[0] === cell ? '| ' : ' ';
      return `${prefix}${normalizeTableCell(content)} |`;
    },
  });

  // GFM 不表达合并单元格；仅对超出官方规则范围的表格做确定性矩形展开。
  const cellService = new TurndownService({ bulletListMarker: '-' });
  service.addRule('complexTable', {
    filter: (node: Node) => node.nodeName === 'TABLE' && isComplexTable(node as HTMLTableElement),
    replacement: (_content: string, node: Node) => renderComplexTable(node as HTMLTableElement, cellService),
  });

  // 代码块：输出带语言的围栏 ```lang
  service.addRule('fencedCodeBlock', {
    filter: (node: Node) =>
      node.nodeName === 'PRE' &&
      (node as HTMLElement).textContent?.includes('\n') !== false,
    replacement: (_content: string, node: Node) => {
      const pre = node as HTMLElement;
      const code = pre.querySelector('code');
      const lang = code ? codeLanguageOf(code) : '';
      const text = pre.textContent?.replace(/\n$/, '') ?? '';
      return `\n\n\`\`\`${lang}\n${text}\n\`\`\`\n\n`;
    },
  });

  return service;
}
