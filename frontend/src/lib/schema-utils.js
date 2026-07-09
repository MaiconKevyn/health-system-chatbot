export const SCHEMA_UNAVAILABLE_MESSAGE = "Schema indisponivel para esta selecao.";
export const FULL_SCHEMA_SELECT_VALUE = "__datavissus_full_schema__";

export function getSchemaTables(data) {
  if (Array.isArray(data)) return data;
  if (Array.isArray(data?.tables)) return data.tables;
  if (Array.isArray(data?.schema?.tables)) return data.schema.tables;
  if (Array.isArray(data?.data?.tables)) return data.data.tables;

  return [];
}

export function isHtmlSchema(schema) {
  const text = String(schema == null ? "" : schema);
  return (
    /\bid=["']schema-data-table["']/.test(text) ||
    /\bclass=["'][^"']*\bcolumn-filter\b/.test(text)
  );
}

export function normalizeSchemaText(schema, fallback = SCHEMA_UNAVAILABLE_MESSAGE) {
  const text = String(schema == null ? "" : schema).trim();
  return text || fallback;
}

export function getSchemaTableSelectValue(tableName = "") {
  return tableName ? tableName : FULL_SCHEMA_SELECT_VALUE;
}

export function getSchemaTableNameFromSelectValue(selectValue = "") {
  return selectValue === FULL_SCHEMA_SELECT_VALUE ? "" : selectValue;
}
