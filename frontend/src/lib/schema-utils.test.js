import { describe, expect, it } from "vitest";

import {
  FULL_SCHEMA_SELECT_VALUE,
  getSchemaTableNameFromSelectValue,
  getSchemaTables,
  getSchemaTableSelectValue,
  isHtmlSchema,
  normalizeSchemaText
} from "./schema-utils";

describe("schema-utils", () => {
  it("returns schema table names from common response shapes", () => {
    expect(getSchemaTables({ tables: ["tb_cid", "tb_municipio"] })).toEqual(["tb_cid", "tb_municipio"]);
    expect(getSchemaTables({ schema: { tables: ["tb_procedimento"] } })).toEqual(["tb_procedimento"]);
    expect(getSchemaTables({})).toEqual([]);
  });

  it("detects HTML schemas with explicit legacy table/filter markers", () => {
    expect(isHtmlSchema('<table id="schema-data-table"></table>')).toBe(true);
    expect(isHtmlSchema('<input class="column-filter" />')).toBe(true);
    expect(isHtmlSchema('<table class="schema-table"></table>')).toBe(false);
    expect(isHtmlSchema("CREATE TABLE tb_cid (id text);")).toBe(false);
  });

  it("normalizes empty schema text to the unavailable message", () => {
    expect(normalizeSchemaText("")).toBe("Schema indisponivel para esta selecao.");
    expect(normalizeSchemaText(null)).toBe("Schema indisponivel para esta selecao.");
    expect(normalizeSchemaText("  CREATE TABLE tb_cid (id text);  ")).toBe("CREATE TABLE tb_cid (id text);");
  });

  it("uses a non-empty select value while preserving empty API table names for the full schema", () => {
    expect(FULL_SCHEMA_SELECT_VALUE).not.toBe("");
    expect(getSchemaTableSelectValue("")).toBe(FULL_SCHEMA_SELECT_VALUE);
    expect(getSchemaTableSelectValue("tb_cid")).toBe("tb_cid");
    expect(getSchemaTableNameFromSelectValue(FULL_SCHEMA_SELECT_VALUE)).toBe("");
    expect(getSchemaTableNameFromSelectValue("tb_cid")).toBe("tb_cid");
  });
});
