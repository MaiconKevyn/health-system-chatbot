import { useEffect, useMemo, useRef, useState } from "react";
import * as echarts from "echarts";

import { buildChartAriaLabel, chartTypeLabel, shortChartTypeLabel } from "@/lib/rendering";

function isObject(value) {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function getChartOptions(chart, spec) {
  return chart?.echarts || chart?.options || spec?.echarts || spec?.options || null;
}

function getFallbackRows(spec) {
  const rows = Array.isArray(spec?.data) ? spec.data : Array.isArray(spec?.rows) ? spec.rows : [];
  return rows.filter((row) => row !== null && row !== undefined).slice(0, 12);
}

function getColumns(rows, spec) {
  if (Array.isArray(spec?.columns) && spec.columns.length > 0) {
    return spec.columns.map((column, index) => {
      if (isObject(column)) {
        return {
          key: column.key ?? column.field ?? column.name ?? String(index),
          label: column.label ?? column.title ?? column.name ?? column.key ?? column.field ?? String(index + 1)
        };
      }

      return { key: column, label: column };
    });
  }

  const firstObject = rows.find(isObject);
  if (firstObject) {
    return Object.keys(firstObject).map((key) => ({ key, label: key }));
  }

  const firstArray = rows.find(Array.isArray);
  if (firstArray) {
    return firstArray.map((_, index) => ({ key: index, label: `Coluna ${index + 1}` }));
  }

  return [];
}

function formatFieldLabel(field) {
  return String(field ?? "")
    .replace(/_/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

function formatCell(value) {
  if (value === null || value === undefined) return "-";
  if (typeof value === "number" && Number.isFinite(value)) return value.toLocaleString("pt-BR");
  if (isObject(value) || Array.isArray(value)) return JSON.stringify(value);
  return String(value);
}

function formatWarning(warning) {
  if (typeof warning === "string") return warning;
  if (isObject(warning)) return warning.message || warning.reason || JSON.stringify(warning);
  return "";
}

function ChartFallbackTable({ rows, columns }) {
  if (rows.length === 0 || columns.length === 0) {
    return (
      <p className="rounded-md bg-muted/30 p-3 text-sm text-muted-foreground">
        Nao foi possivel renderizar o grafico e nao ha dados tabulares para exibir.
      </p>
    );
  }

  return (
    <div className="overflow-x-auto rounded-lg border border-border">
      <table className="min-w-full border-collapse text-sm">
        <thead>
          <tr>
            {columns.map((column) => (
              <th key={String(column.key)} scope="col" className="bg-muted/80 px-3 py-2 text-left font-semibold">
                {formatFieldLabel(column.label)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, rowIndex) => (
            <tr key={`fallback-row-${rowIndex}`}>
              {columns.map((column) => (
                <td key={`${rowIndex}-${String(column.key)}`} className="border-t border-border px-3 py-2">
                  {formatCell(Array.isArray(row) ? row[column.key] : row?.[column.key])}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function ChartPanel({ chart }) {
  const targetRef = useRef(null);
  const [renderError, setRenderError] = useState(null);
  const spec = chart?.spec;
  const chartOptions = getChartOptions(chart, spec);
  const fallbackRows = useMemo(() => getFallbackRows(spec), [spec]);
  const fallbackColumns = useMemo(() => getColumns(fallbackRows, spec), [fallbackRows, spec]);
  const warnings = Array.isArray(spec?.warnings)
    ? spec.warnings.map(formatWarning).filter(Boolean).join(" ")
    : "";

  useEffect(() => {
    if (!spec?.chartable || !chartOptions) {
      setRenderError(null);
      return undefined;
    }

    if (!targetRef.current) return undefined;

    let active = true;
    let chartInstance = null;
    let resizeObserver = null;
    const target = targetRef.current;

    function resizeChart() {
      chartInstance?.resize();
    }

    try {
      setRenderError(null);
      chartInstance = echarts.init(target, null, { renderer: "svg" });
      chartInstance.setOption(chartOptions, true);

      if (typeof ResizeObserver === "function") {
        resizeObserver = new ResizeObserver(resizeChart);
        resizeObserver.observe(target);
      } else if (typeof window !== "undefined") {
        window.addEventListener("resize", resizeChart, { passive: true });
      }
    } catch (error) {
      if (chartInstance) {
        chartInstance.dispose();
        chartInstance = null;
      }
      if (active) setRenderError(error);
    }

    return () => {
      active = false;
      if (resizeObserver) {
        resizeObserver.disconnect();
      } else if (typeof window !== "undefined") {
        window.removeEventListener("resize", resizeChart);
      }
      chartInstance?.dispose();
    };
  }, [chartOptions, spec?.chartable]);

  if (!chart?.requested || !spec) return null;

  const title = spec.title || chartTypeLabel(spec.chart_type);
  const hasChartTarget = Boolean(spec.chartable && chartOptions);
  const showFallback = spec.chartable && (!chartOptions || renderError);

  return (
    <section className="overflow-hidden rounded-lg border border-border bg-card p-3">
      <div className="mb-3 flex min-h-8 items-start justify-between gap-3">
        <h3 className="min-w-0 break-words text-sm font-semibold leading-snug">{title}</h3>
        <span className="shrink-0 rounded-full border border-border bg-muted/50 px-2 py-1 text-[0.68rem] font-bold uppercase tracking-[0.08em] text-muted-foreground">
          {shortChartTypeLabel(spec.chart_type)}
        </span>
      </div>

      {!spec.chartable ? (
        <p className="rounded-md bg-muted/30 p-3 text-sm text-muted-foreground">
          {spec.reason || "Nao foi possivel gerar um grafico validado para esse resultado."}
        </p>
      ) : null}

      {hasChartTarget ? (
        <div
          ref={targetRef}
          role="img"
          aria-label={buildChartAriaLabel(spec)}
          className={renderError ? "hidden" : "min-h-[360px] w-full min-w-0"}
        />
      ) : null}

      {showFallback ? <ChartFallbackTable rows={fallbackRows} columns={fallbackColumns} /> : null}

      {warnings ? (
        <p className="mt-3 text-xs leading-relaxed text-amber-700 dark:text-amber-300">{warnings}</p>
      ) : null}
    </section>
  );
}
