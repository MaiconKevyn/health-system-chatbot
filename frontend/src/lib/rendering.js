function splitMarkdownTableRow(line) {
  if (typeof line !== "string" || !line.includes("|")) return [];

  let trimmed = line.trim();
  if (!trimmed.includes("|")) return [];
  if (trimmed.startsWith("|")) trimmed = trimmed.slice(1);
  if (trimmed.endsWith("|")) trimmed = trimmed.slice(0, -1);

  return trimmed.split("|").map((cell) => cell.trim());
}

function isMarkdownTableSeparatorCell(cell) {
  return /^:?-{3,}:?$/.test(cell.trim());
}

function getMarkdownTableAlignment(separator) {
  const trimmed = separator.trim();
  if (trimmed.startsWith(":") && trimmed.endsWith(":")) return "center";
  if (trimmed.endsWith(":")) return "right";
  return "left";
}

function isMarkdownTableStart(lines, index) {
  if (index + 1 >= lines.length) return false;

  const headers = splitMarkdownTableRow(lines[index]);
  const separators = splitMarkdownTableRow(lines[index + 1]);

  return (
    headers.length >= 2 &&
    separators.length === headers.length &&
    separators.every(isMarkdownTableSeparatorCell)
  );
}

export function containsMarkdownTable(content) {
  const lines = String(content == null ? "" : content).split("\n");
  return lines.some((_, index) => isMarkdownTableStart(lines, index));
}

export function splitMarkdownTable(lines, startIndex = 0) {
  const sourceLines = Array.isArray(lines) ? lines : String(lines == null ? "" : lines).split("\n");

  if (!isMarkdownTableStart(sourceLines, startIndex)) {
    return {
      headers: [],
      alignments: [],
      rows: [],
      nextIndex: startIndex
    };
  }

  const headers = splitMarkdownTableRow(sourceLines[startIndex]);
  const alignments = splitMarkdownTableRow(sourceLines[startIndex + 1]).map(getMarkdownTableAlignment);
  const rows = [];
  let index = startIndex + 2;

  while (index < sourceLines.length) {
    const row = splitMarkdownTableRow(sourceLines[index]);
    if (row.length !== headers.length) break;
    rows.push(row);
    index += 1;
  }

  return {
    headers,
    alignments,
    rows,
    nextIndex: index
  };
}

export function chartTypeLabel(type) {
  const labels = {
    bar: "Grafico de barras",
    line: "Grafico de linha",
    area: "Grafico de area",
    scatter: "Grafico de dispersao",
    pie: "Grafico de proporcao",
    donut: "Grafico de proporcao",
    kpi: "Indicador",
    table: "Tabela"
  };

  return labels[type] || "Grafico";
}

export function shortChartTypeLabel(type) {
  const labels = {
    bar: "Barras",
    line: "Linha",
    area: "Area",
    scatter: "Dispersao",
    pie: "Pizza",
    donut: "Donut",
    kpi: "KPI",
    table: "Tabela"
  };

  return labels[type] || "Grafico";
}

function formatFieldLabel(field) {
  if (!field) return "";

  return String(field)
    .replace(/_/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

export function buildChartAriaLabel(spec = {}) {
  const title = spec.title || chartTypeLabel(spec.chart_type);
  const x = formatFieldLabel(spec.x);
  const y = formatFieldLabel(spec.y);
  return `${title}. Eixo X: ${x}. Eixo Y: ${y}.`;
}
