import { useEffect, useRef } from "react";
import { Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import {
  FULL_SCHEMA_SELECT_VALUE,
  getSchemaTableNameFromSelectValue,
  getSchemaTableSelectValue,
  isHtmlSchema
} from "@/lib/schema-utils";

const EMPTY_SCHEMA_MESSAGE = "Selecione uma tabela e clique em Carregar schema.";
const LEGACY_HTML_PANEL_CLASS_NAME = [
  "thin-scrollbar max-h-[62vh] overflow-auto rounded-lg border border-border bg-background p-3 text-sm text-foreground",
  "[&_.clear-filters-btn]:grid [&_.clear-filters-btn]:h-9 [&_.clear-filters-btn]:w-9 [&_.clear-filters-btn]:place-items-center [&_.clear-filters-btn]:rounded-md [&_.clear-filters-btn]:border [&_.clear-filters-btn]:border-border [&_.clear-filters-btn]:bg-background [&_.clear-filters-btn]:text-primary",
  "[&_.clear-filters-wrapper]:shrink-0",
  "[&_.column-filter]:h-9 [&_.column-filter]:rounded-md [&_.column-filter]:border [&_.column-filter]:border-input [&_.column-filter]:bg-background [&_.column-filter]:px-2 [&_.column-filter]:text-xs [&_.column-filter]:text-foreground",
  "[&_.filter-bar]:flex [&_.filter-bar]:items-end [&_.filter-bar]:gap-3 [&_.filter-bar]:overflow-x-auto [&_.filter-bar]:border-b [&_.filter-bar]:border-border [&_.filter-bar]:bg-muted/40 [&_.filter-bar]:p-3",
  "[&_.filter-column]:flex [&_.filter-column]:min-w-36 [&_.filter-column]:flex-col [&_.filter-column]:gap-1.5",
  "[&_.filter-label]:text-[0.68rem] [&_.filter-label]:font-semibold [&_.filter-label]:uppercase [&_.filter-label]:tracking-[0.08em] [&_.filter-label]:text-muted-foreground",
  "[&_.filtered-records]:hidden [&_.filtered-records]:items-center [&_.filtered-records]:gap-1.5 [&_.filtered-records]:rounded-full [&_.filtered-records]:bg-primary/10 [&_.filtered-records]:px-2 [&_.filtered-records]:py-1 [&_.filtered-records]:text-primary",
  "[&_.hidden-row]:hidden",
  "[&_.records-counter]:flex [&_.records-counter]:items-center [&_.records-counter]:justify-between [&_.records-counter]:gap-3 [&_.records-counter]:border-b [&_.records-counter]:border-border [&_.records-counter]:bg-muted/40 [&_.records-counter]:p-3",
  "[&_.schema-table-container]:overflow-hidden [&_.schema-table-container]:rounded-lg [&_.schema-table-container]:border [&_.schema-table-container]:border-border [&_.schema-table-container]:bg-background",
  "[&_.schema-table]:w-full [&_.schema-table]:min-w-max [&_.schema-table]:border-collapse [&_.schema-table]:text-xs",
  "[&_.schema-table_td]:max-w-80 [&_.schema-table_td]:overflow-hidden [&_.schema-table_td]:text-ellipsis [&_.schema-table_td]:whitespace-nowrap [&_.schema-table_td]:border-b [&_.schema-table_td]:border-border [&_.schema-table_td]:px-3 [&_.schema-table_td]:py-2 [&_.schema-table_td]:font-mono",
  "[&_.schema-table_th]:sticky [&_.schema-table_th]:top-0 [&_.schema-table_th]:z-10 [&_.schema-table_th]:whitespace-nowrap [&_.schema-table_th]:border-b [&_.schema-table_th]:border-border [&_.schema-table_th]:bg-muted [&_.schema-table_th]:px-3 [&_.schema-table_th]:py-2 [&_.schema-table_th]:text-left [&_.schema-table_th]:text-[0.7rem] [&_.schema-table_th]:font-semibold [&_.schema-table_th]:uppercase [&_.schema-table_th]:tracking-[0.08em] [&_.schema-table_th]:text-muted-foreground",
  "[&_.sample-data-table]:overflow-hidden [&_.sample-data-table]:rounded-lg [&_.sample-data-table]:border [&_.sample-data-table]:border-border [&_.sample-data-table]:bg-background",
  "[&_.table-scroll-wrapper]:max-h-[48vh] [&_.table-scroll-wrapper]:overflow-auto",
  "[&_mark]:rounded [&_mark]:bg-yellow-300/40 [&_mark]:px-1 [&_tbody_tr:nth-child(even)]:bg-muted/30 [&_tbody_tr:hover]:bg-primary/5"
].join(" ");

function getTableValue(table, index) {
  if (typeof table === "string") return table;
  return table?.name || table?.table || table?.table_name || `table-${index}`;
}

function getTableLabel(table, index) {
  if (typeof table === "string") return table;
  return table?.label || table?.description || getTableValue(table, index);
}

function updateFilterCount(root, visible, total) {
  const filteredRecords = root.querySelector(".filtered-records");
  const filteredCount = root.querySelector(".filtered-count");

  if (filteredRecords) {
    filteredRecords.style.display = visible !== total ? "flex" : "none";
  }

  if (filteredCount) {
    filteredCount.textContent = visible.toLocaleString("pt-BR");
  }
}

function attachLegacyTableFilters(root) {
  const table = root.querySelector("#schema-data-table");
  const tbody = table?.querySelector("tbody");
  const rows = tbody ? Array.from(tbody.querySelectorAll("tr")) : [];
  const filterInputs = Array.from(root.querySelectorAll(".column-filter"));

  if (!table || rows.length === 0 || filterInputs.length === 0) {
    return () => {};
  }

  const filterRows = () => {
    let visibleCount = 0;

    rows.forEach((row) => {
      const shouldShow = filterInputs.every((input, columnIndex) => {
        const term = input.value.toLowerCase().trim();
        if (!term) return true;

        const cell = row.cells[columnIndex];
        return Boolean(cell?.textContent.toLowerCase().includes(term));
      });

      row.hidden = !shouldShow;
      row.classList.toggle("hidden-row", !shouldShow);
      if (shouldShow) visibleCount += 1;
    });

    updateFilterCount(root, visibleCount, rows.length);
  };

  const listenerEntries = filterInputs.flatMap((input, index) => {
    const handleInput = () => filterRows();
    const handleKeyDown = (event) => {
      if (event.key === "Escape") {
        input.value = "";
        filterRows();
        return;
      }

      if (!event.ctrlKey) return;

      if (event.key === "ArrowRight") {
        event.preventDefault();
        filterInputs[index + 1]?.focus();
      }

      if (event.key === "ArrowLeft") {
        event.preventDefault();
        filterInputs[index - 1]?.focus();
      }
    };

    input.addEventListener("input", handleInput);
    input.addEventListener("keydown", handleKeyDown);

    return [
      [input, "input", handleInput],
      [input, "keydown", handleKeyDown]
    ];
  });

  filterRows();

  return () => {
    listenerEntries.forEach(([input, eventName, handler]) => {
      input.removeEventListener(eventName, handler);
    });
  };
}

function SchemaBody({ schema, htmlPanelRef }) {
  const hasSchema = Boolean(schema.schema);
  const hasHtmlSchema = hasSchema && isHtmlSchema(schema.schema);

  if (schema.status === "loading") {
    return (
      <div
        role="status"
        aria-live="polite"
        className="flex min-h-40 items-center justify-center rounded-lg border border-dashed border-border bg-muted/30 text-sm text-muted-foreground"
      >
        Carregando schema...
      </div>
    );
  }

  if (schema.status === "error") {
    return (
      <div
        role="alert"
        className="rounded-lg border border-destructive/30 bg-destructive/10 p-4 text-sm font-medium text-destructive"
      >
        {schema.error}
      </div>
    );
  }

  if (schema.status !== "loaded" || !hasSchema) {
    return (
      <div className="flex min-h-40 items-center justify-center rounded-lg border border-dashed border-border bg-muted/30 px-4 text-center text-sm text-muted-foreground">
        {EMPTY_SCHEMA_MESSAGE}
      </div>
    );
  }

  if (hasHtmlSchema) {
    return (
      <>
        {/* Schema HTML is generated by the local backend schema endpoint and is constrained to this scrollable panel for legacy parity. */}
        <div
          dangerouslySetInnerHTML={{ __html: schema.schema }}
          ref={htmlPanelRef}
          className={LEGACY_HTML_PANEL_CLASS_NAME}
        />
      </>
    );
  }

  return (
    <pre className="thin-scrollbar max-h-[62vh] overflow-auto rounded-lg border border-border bg-background p-4 text-sm leading-relaxed text-foreground whitespace-pre-wrap break-words">
      <code className="font-mono">{schema.schema}</code>
    </pre>
  );
}

export function SchemaExplorer({ schema }) {
  const htmlPanelRef = useRef(null);
  const loading = schema.status === "loading";
  const tables = Array.isArray(schema.tables) ? schema.tables : [];
  const selectedTable = schema.selectedTable ?? "";

  useEffect(() => {
    if (!schema.open || schema.status !== "loaded" || !isHtmlSchema(schema.schema)) {
      return undefined;
    }

    const root = htmlPanelRef.current;
    if (!root) return undefined;

    return attachLegacyTableFilters(root);
  }, [schema.open, schema.status, schema.schema]);

  return (
    <Dialog open={schema.open} onOpenChange={schema.setOpen}>
      <DialogContent className="max-h-[92vh] max-w-5xl overflow-hidden p-0">
        <DialogHeader className="border-b border-border px-6 pb-4 pt-6">
          <DialogTitle>Esquema do Banco</DialogTitle>
          <DialogDescription>
            Inspecione tabelas, colunas e amostras disponiveis para formular perguntas mais precisas.
          </DialogDescription>
        </DialogHeader>

        <div className="grid gap-4 overflow-hidden px-6 pb-6">
          <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-end">
            <div className="space-y-1.5">
              <label className="text-sm font-medium text-foreground" htmlFor="schema-table-select">
                Tabela
              </label>
              <Select
                value={getSchemaTableSelectValue(selectedTable)}
                onValueChange={(value) => schema.setSelectedTable(getSchemaTableNameFromSelectValue(value))}
                disabled={loading}
              >
                <SelectTrigger id="schema-table-select">
                  <SelectValue placeholder="Esquema completo" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={FULL_SCHEMA_SELECT_VALUE}>Esquema completo</SelectItem>
                  {tables.map((table, index) => {
                    const value = getTableValue(table, index);
                    return (
                      <SelectItem key={value} value={value}>
                        {getTableLabel(table, index)}
                      </SelectItem>
                    );
                  })}
                </SelectContent>
              </Select>
            </div>

            <Button
              type="button"
              onClick={schema.loadSelectedSchema}
              disabled={loading}
              className="w-full sm:w-auto"
            >
              {loading ? <Loader2 aria-hidden="true" className="h-4 w-4 animate-spin" /> : null}
              <span>{loading ? "Carregando..." : "Carregar schema"}</span>
            </Button>
          </div>

          <SchemaBody schema={schema} htmlPanelRef={htmlPanelRef} />
        </div>
      </DialogContent>
    </Dialog>
  );
}
