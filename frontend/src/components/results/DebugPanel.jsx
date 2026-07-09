import { Bug } from "lucide-react";

function isObject(value) {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function formatInlineValue(value) {
  if (Array.isArray(value)) return value.join(", ");
  if (isObject(value)) return safeStringify(value);
  return value;
}

function safeStringify(value) {
  const seen = new WeakSet();

  try {
    return JSON.stringify(
      value,
      (_key, nestedValue) => {
        if (nestedValue && typeof nestedValue === "object") {
          if (seen.has(nestedValue)) return "[Circular]";
          seen.add(nestedValue);
        }
        return nestedValue;
      },
      2
    );
  } catch (error) {
    return "[Unserializable debug data]";
  }
}

function getStepState(step) {
  if (isObject(step?.data)) return step.data;
  if (isObject(step?.state)) return step.state;
  return {};
}

function getStepValue(step, state, key) {
  return state[key] ?? step?.[key];
}

function buildRemainingState(step, state) {
  const remaining = { ...state };
  delete remaining.generated_sql;
  delete remaining.validated_sql;
  delete remaining.final_response;

  if (Object.keys(remaining).length > 0) return remaining;

  if (!isObject(step)) return {};

  const ignored = new Set([
    "data",
    "final_response",
    "generated_sql",
    "index",
    "node",
    "state",
    "status",
    "title",
    "validated_sql"
  ]);

  return Object.fromEntries(Object.entries(step).filter(([key]) => !ignored.has(key)));
}

function CodeSection({ title, value, json = false }) {
  if (value === null || value === undefined || value === "") return null;

  const content = json ? safeStringify(value) : String(value);

  return (
    <section className="min-w-0 space-y-1.5">
      <h4 className="text-[0.7rem] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
        {title}
      </h4>
      <pre className="thin-scrollbar max-h-80 overflow-auto rounded-md bg-background p-3 text-xs leading-relaxed">
        <code className="font-mono">{content}</code>
      </pre>
    </section>
  );
}

function TextSection({ title, value }) {
  if (value === null || value === undefined || value === "") return null;

  return (
    <section className="min-w-0 space-y-1.5">
      <h4 className="text-[0.7rem] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
        {title}
      </h4>
      <p className="rounded-md bg-background p-3 text-sm leading-relaxed text-muted-foreground">
        {String(value)}
      </p>
    </section>
  );
}

function DebugFacts({ agentMetadata }) {
  const facts = [
    ["Modelo", agentMetadata?.current_model?.model_name],
    ["Rota", agentMetadata?.query_route],
    ["Tabelas", formatInlineValue(agentMetadata?.tables_used)],
    ["Retries", agentMetadata?.retry_count],
    ["Erros", agentMetadata?.error_count]
  ].filter(([, value]) => value !== null && value !== undefined && value !== "");

  if (facts.length === 0) return null;

  return (
    <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
      {facts.map(([label, value]) => (
        <div key={label} className="min-w-0 rounded-md border border-border bg-muted/30 p-3">
          <span className="block text-[0.7rem] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
            {label}
          </span>
          <strong className="mt-1 block break-words text-sm font-semibold text-foreground">
            {String(value)}
          </strong>
        </div>
      ))}
    </div>
  );
}

function DebugStep({ step, position }) {
  const state = getStepState(step);
  const index = step?.index ?? position + 1;
  const title = step?.title || step?.node || "Node";
  const node = step?.node;
  const generatedSql = getStepValue(step, state, "generated_sql");
  const validatedSql = getStepValue(step, state, "validated_sql");
  const finalResponse = getStepValue(step, state, "final_response");
  const remainingState = buildRemainingState(step, state);
  const hasRemainingState = Object.keys(remainingState).length > 0;

  return (
    <details className="overflow-hidden rounded-md border border-border bg-muted/20">
      <summary className="flex min-h-10 cursor-pointer list-none items-center justify-between gap-3 px-3 py-2 marker:hidden [&::-webkit-details-marker]:hidden">
        <span className="min-w-0 truncate text-sm font-semibold">
          {index}. {title}
        </span>
        {node ? (
          <code className="shrink-0 rounded bg-background px-2 py-1 font-mono text-[0.7rem] text-muted-foreground">
            {node}
          </code>
        ) : null}
      </summary>
      <div className="space-y-3 border-t border-border p-3">
        <CodeSection title="SQL gerada" value={generatedSql} />
        {validatedSql && validatedSql !== generatedSql ? (
          <CodeSection title="SQL validada" value={validatedSql} />
        ) : null}
        <TextSection title="Resposta final" value={finalResponse} />
        {hasRemainingState ? <CodeSection title="Estado" value={remainingState} json /> : null}
      </div>
    </details>
  );
}

export function DebugPanel({ debug, sql, agentMetadata, metadata }) {
  const resolvedDebug = debug ?? metadata?.debug;
  const resolvedSql = sql ?? metadata?.sql;
  const resolvedAgentMetadata = agentMetadata ?? metadata?.agentMetadata ?? {};

  if (!Array.isArray(resolvedDebug?.steps)) return null;

  return (
    <details open className="overflow-hidden rounded-lg border border-border bg-card">
      <summary className="flex min-h-11 cursor-pointer list-none items-center gap-2 border-b border-border px-3 py-2 marker:hidden [&::-webkit-details-marker]:hidden">
        <Bug aria-hidden="true" className="h-4 w-4 text-primary" />
        <span className="text-sm font-semibold">Debug</span>
        <span className="ml-auto text-xs font-semibold text-muted-foreground">
          {resolvedDebug.steps.length} nodes
        </span>
      </summary>
      <div className="space-y-3 p-3">
        <CodeSection title="SQL final" value={resolvedSql} />
        <DebugFacts agentMetadata={resolvedAgentMetadata} />
        <div className="space-y-2">
          {resolvedDebug.steps.map((step, index) => (
            <DebugStep key={`${step?.node || "step"}-${step?.index ?? index}`} step={step} position={index} />
          ))}
        </div>
      </div>
    </details>
  );
}
