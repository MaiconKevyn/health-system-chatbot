import { describe, expect, it } from "vitest";

import {
  buildChartAriaLabel,
  chartTypeLabel,
  containsMarkdownTable,
  shortChartTypeLabel,
  splitMarkdownTable
} from "./rendering";

describe("rendering", () => {
  it("detects markdown tables", () => {
    expect(
      containsMarkdownTable(`Texto antes
| Ano | Casos |
| --- | ---: |
| 2024 | 10 |`)
    ).toBe(true);
    expect(containsMarkdownTable("Texto sem tabela | apenas pipe")).toBe(false);
  });

  it("splits a markdown table into headers, alignments, rows, and bounds", () => {
    expect(
      splitMarkdownTable([
        "Resumo",
        "| Ano | Casos | Taxa |",
        "| :--- | ---: | :---: |",
        "| 2024 | 10 | 1.5 |",
        "| 2025 | 12 | 1.7 |",
        "Depois"
      ], 1)
    ).toEqual({
      headers: ["Ano", "Casos", "Taxa"],
      alignments: ["left", "right", "center"],
      rows: [
        ["2024", "10", "1.5"],
        ["2025", "12", "1.7"]
      ],
      nextIndex: 5
    });
  });

  it("returns chart labels for bar, line, and unknown chart types", () => {
    expect(chartTypeLabel("bar")).toBe("Grafico de barras");
    expect(chartTypeLabel("line")).toBe("Grafico de linha");
    expect(chartTypeLabel("unknown")).toBe("Grafico");
    expect(shortChartTypeLabel("bar")).toBe("Barras");
    expect(shortChartTypeLabel("line")).toBe("Linha");
    expect(shortChartTypeLabel("unknown")).toBe("Grafico");
  });

  it("builds a chart aria label from chart spec fields", () => {
    expect(
      buildChartAriaLabel({
        title: "Casos por ano",
        chart_type: "bar",
        x: "ano_diagnostico",
        y: "total_casos"
      })
    ).toBe("Casos por ano. Eixo X: Ano Diagnostico. Eixo Y: Total Casos.");
  });
});
