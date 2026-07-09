import { useCallback, useMemo, useRef, useState } from "react";
import { toast } from "sonner";

import { getSchema } from "../lib/api";
import { getSchemaTables, normalizeSchemaText } from "../lib/schema-utils";

export function useSchemaExplorer() {
  const [open, setOpen] = useState(false);
  const [tables, setTables] = useState([]);
  const [selectedTable, setSelectedTable] = useState("");
  const [schema, setSchema] = useState("");
  const [status, setStatus] = useState("empty");
  const [error, setError] = useState("");
  const schemaRequestSequenceRef = useRef(0);

  const loadTables = useCallback(async () => {
    try {
      const payload = await getSchema();
      const nextTables = getSchemaTables(payload);
      setTables(nextTables);
      return nextTables;
    } catch {
      setTables([]);
      return [];
    }
  }, []);

  const openExplorer = useCallback(async () => {
    setOpen(true);
    setStatus("empty");
    setError("");

    return await loadTables();
  }, [loadTables]);

  const loadSelectedSchema = useCallback(async () => {
    const requestId = schemaRequestSequenceRef.current + 1;
    const tableSnapshot = selectedTable;
    schemaRequestSequenceRef.current = requestId;
    setStatus("loading");
    setError("");

    try {
      const payload = await getSchema(tableSnapshot);
      if (schemaRequestSequenceRef.current !== requestId) {
        return;
      }
      setSchema(normalizeSchemaText(payload?.schema));
      setStatus("loaded");
    } catch (loadError) {
      if (schemaRequestSequenceRef.current !== requestId) {
        return;
      }
      const message = loadError?.message || String(loadError);
      setError(`Erro ao carregar schema: ${message}`);
      setStatus("error");
      toast.error("Erro ao carregar o schema do banco de dados.");
    }
  }, [selectedTable]);

  return useMemo(
    () => ({
      open,
      setOpen,
      tables,
      setTables,
      selectedTable,
      setSelectedTable,
      schema,
      setSchema,
      status,
      setStatus,
      error,
      setError,
      loadTables,
      openExplorer,
      loadSelectedSchema
    }),
    [
      error,
      loadSelectedSchema,
      loadTables,
      open,
      openExplorer,
      schema,
      selectedTable,
      status,
      tables
    ]
  );
}
