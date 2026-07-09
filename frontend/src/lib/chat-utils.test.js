import { describe, expect, it } from "vitest";

import {
  buildPydanticDebug,
  buildUserFacingError,
  createMessage,
  createSessionId,
  normalizeQueryResponse,
  trimPersistedHistory
} from "./chat-utils";

describe("chat-utils", () => {
  it("creates a message with deterministic timestamp and id factory", () => {
    const now = new Date("2026-06-19T12:34:56.000Z");

    expect(
      createMessage("Resposta pronta", {
        type: "assistant",
        metadata: { executionTime: 1.25 },
        now,
        idFactory: () => "message-1"
      })
    ).toEqual({
      id: "message-1",
      content: "Resposta pronta",
      type: "assistant",
      timestamp: "2026-06-19T12:34:56.000Z",
      metadata: { executionTime: 1.25 }
    });
  });

  it("trims persisted history by removing errors and keeping the last 20 messages", () => {
    const messages = Array.from({ length: 25 }, (_, index) => ({
      id: `message-${index}`,
      type: index % 5 === 0 ? "error" : index % 2 === 0 ? "assistant" : "user",
      content: `Mensagem ${index}`
    }));

    const trimmed = trimPersistedHistory(messages);

    expect(trimmed).toHaveLength(20);
    expect(trimmed.every((message) => message.type !== "error")).toBe(true);
    expect(trimmed.map((message) => message.id)).toEqual(
      messages.filter((message) => message.type !== "error").slice(-20).map((message) => message.id)
    );
  });

  it("normalizes successful query responses with debug metadata when enabled", () => {
    const result = normalizeQueryResponse(
      {
        success: true,
        conversational_response: "Consulta concluida.",
        execution_time: 2.5,
        sql_query: "select 1",
        chart: { requested: true },
        debug: { route: "sql" },
        metadata: { tables_used: ["tb_cid"] }
      },
      true
    );

    expect(result).toEqual({
      type: "assistant",
      content: "Consulta concluida.",
      metadata: {
        executionTime: 2.5,
        sql: "select 1",
        chart: { requested: true },
        debug: { route: "sql" },
        agentMetadata: { tables_used: ["tb_cid"] }
      }
    });
  });

  it("normalizes failed query responses without debug metadata when disabled", () => {
    const result = normalizeQueryResponse(
      {
        success: false,
        answer: "Nao encontrei dados suficientes.",
        execution_time: Number.NaN,
        sql: "select * from missing",
        debug: { route: "sql" },
        metadata: { tables_used: [] }
      },
      false
    );

    expect(result).toEqual({
      type: "error",
      content: "Nao encontrei dados suficientes.",
      metadata: {
        sql: "select * from missing",
        chart: null
      }
    });
  });

  it("normalizes Pydantic AI chatbot answers and preserves chart payloads", () => {
    const chart = {
      requested: true,
      spec: { chartable: true, chart_type: "bar", x: "sexo", y: "internacoes" },
      echarts: { series: [{ type: "bar" }] }
    };
    const result = normalizeQueryResponse(
      {
        answer_pt: "Gerei o grafico por sexo.",
        sql: "SELECT sexo, COUNT(*) AS internacoes FROM internacoes GROUP BY 1",
        status: "answered",
        chart,
        evidence: { elapsed_seconds: 0.42, row_count: 2 },
        developer_context: {
          retrieved_tables: ["internacoes", "sexo"],
          chart_plan: { chart_type: "bar" }
        }
      },
      true
    );

    expect(result.type).toBe("assistant");
    expect(result.content).toBe("Gerei o grafico por sexo.");
    expect(result.metadata.chart).toBe(chart);
    expect(result.metadata.sql).toMatch(/SELECT sexo/);
    expect(result.metadata.executionTime).toBe(0.42);
    expect(result.metadata.debug.steps.map((step) => step.node)).toContain("chart");
    expect(result.metadata.agentMetadata.retrieved_tables).toEqual(["internacoes", "sexo"]);
  });

  it("builds structured debug steps from Pydantic AI developer context", () => {
    const debug = buildPydanticDebug({
      answer_pt: "Ha 10 internacoes.",
      sql: "SELECT 10 AS internacoes",
      result_summary: "internacoes=10",
      evidence: { row_count: 1 },
      developer_context: { metric_basis: ["COUNT"] }
    });

    expect(debug.steps).toHaveLength(4);
    expect(debug.steps[0].node).toBe("sql");
    expect(debug.steps[0].data.generated_sql).toBe("SELECT 10 AS internacoes");
    expect(debug.steps[2].node).toBe("developer_context");
  });

  it("builds user-facing errors for common connection and HTTP cases", () => {
    expect(buildUserFacingError(new Error("Failed to fetch"))).toBe(
      "Nao foi possivel conectar a API do Health System Chatbot. Confirme se o servico esta rodando e tente novamente."
    );
    expect(buildUserFacingError(new Error("NetworkError when attempting to fetch resource."))).toBe(
      "Nao foi possivel conectar a API do Health System Chatbot. Confirme se o servico esta rodando e tente novamente."
    );
    expect(buildUserFacingError(new Error("HTTP 429: Too Many Requests"))).toBe(
      "Muitas consultas em pouco tempo. Aguarde alguns segundos antes de tentar novamente."
    );
    expect(buildUserFacingError(new Error("HTTP 503: Service Unavailable"))).toBe(
      "O agente retornou erro interno. Tente novamente em alguns instantes ou refine o recorte da consulta."
    );
    expect(buildUserFacingError(new Error("HTTP 400: Bad Request"))).toBe(
      "Erro de conexao: HTTP 400: Bad Request"
    );
  });

  it("creates a session id with crypto.randomUUID when available", () => {
    expect(
      createSessionId({
        crypto: {
          randomUUID: () => "uuid-123"
        }
      })
    ).toBe("uuid-123");
  });
});
