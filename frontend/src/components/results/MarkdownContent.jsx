import { containsMarkdownTable, splitMarkdownTable } from "@/lib/rendering";

function isBlankLine(line) {
  return !String(line ?? "").trim();
}

function getTextAlignment(alignment) {
  if (alignment === "center") return "text-center";
  if (alignment === "right") return "text-right";
  return "text-left";
}

function renderLines(lines, keyPrefix) {
  return lines.map((line, index) => (
    <span key={`${keyPrefix}-${index}`}>
      {line}
      {index < lines.length - 1 ? <br /> : null}
    </span>
  ));
}

function MarkdownTable({ table }) {
  return (
    <div className="overflow-x-auto rounded-lg border border-border">
      <table className="min-w-full border-collapse text-sm">
        <thead>
          <tr>
            {table.headers.map((header, index) => (
              <th
                key={`${header}-${index}`}
                scope="col"
                className={`bg-muted/80 px-3 py-2 text-left font-semibold ${getTextAlignment(
                  table.alignments[index]
                )}`}
              >
                {header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {table.rows.map((row, rowIndex) => (
            <tr key={`row-${rowIndex}`}>
              {table.headers.map((_, cellIndex) => (
                <td
                  key={`cell-${rowIndex}-${cellIndex}`}
                  className={`border-t border-border px-3 py-2 ${getTextAlignment(
                    table.alignments[cellIndex]
                  )}`}
                >
                  {row[cellIndex] ?? ""}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function MarkdownContent({ content }) {
  const text = String(content ?? "");
  if (!text) return null;

  const lines = text.replace(/\r\n/g, "\n").split("\n");
  const hasTables = containsMarkdownTable(text);
  const blocks = [];
  let paragraphLines = [];

  function flushParagraph() {
    if (paragraphLines.length === 0) return;

    const key = `paragraph-${blocks.length}`;
    blocks.push(
      <p key={key} className="min-w-0 whitespace-normal break-words">
        {renderLines(paragraphLines, key)}
      </p>
    );
    paragraphLines = [];
  }

  let index = 0;
  while (index < lines.length) {
    if (hasTables) {
      const table = splitMarkdownTable(lines, index);
      if (table.headers.length > 0 && table.nextIndex > index) {
        flushParagraph();
        blocks.push(<MarkdownTable key={`table-${blocks.length}`} table={table} />);
        index = table.nextIndex;
        continue;
      }
    }

    if (isBlankLine(lines[index])) {
      flushParagraph();
      index += 1;
      continue;
    }

    paragraphLines.push(lines[index]);
    index += 1;
  }

  flushParagraph();

  return <div className="min-w-0 space-y-3">{blocks}</div>;
}
