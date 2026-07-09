import { useState } from "react";
import { AlertTriangle, Check, Clock3, Copy, Sparkles } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { ChartPanel, DebugPanel, MarkdownContent, SqlBlock } from "@/components/results";
import { cn } from "@/lib/utils";

function normalizeErrorContent(content) {
  const text = String(content ?? "").trim() || "Nao foi possivel processar a consulta.";
  return /^erro:/i.test(text) ? text.replace(/^erro:/i, "Erro:") : `Erro: ${text}`;
}

function formatExecutionTime(value) {
  if (!Number.isFinite(value)) return null;
  return `${value.toFixed(2)}s`;
}

export function MessageItem({ message, debugEnabled }) {
  const [copied, setCopied] = useState(false);
  const metadata = message.metadata && typeof message.metadata === "object" ? message.metadata : {};
  const isUser = message.type === "user";
  const isError = message.type === "error";
  const isAssistant = !isUser && !isError;
  const executionTime = formatExecutionTime(metadata.executionTime);
  const showSql = !isUser && Boolean(metadata.sql);
  const showChart = !isUser && Boolean(metadata.chart);
  const showDebug = !isUser && debugEnabled && Boolean(metadata.debug);

  async function handleCopy() {
    try {
      if (typeof navigator === "undefined" || !navigator.clipboard?.writeText) {
        throw new Error("Clipboard API indisponivel.");
      }

      await navigator.clipboard.writeText(message.content);
      setCopied(true);
      toast.success("Resposta copiada para a area de transferencia.");
      window.setTimeout(() => setCopied(false), 1400);
    } catch (error) {
      toast.error("Nao foi possivel copiar a resposta.");
    }
  }

  return (
    <article className={cn("flex w-full", isUser ? "justify-end" : "justify-start")}>
      <div
        className={cn(
          "min-w-0",
          isUser ? "max-w-[82%] sm:max-w-[68%]" : "w-full max-w-[min(100%,920px)]"
        )}
      >
        <div
          className={cn(
            "rounded-lg border text-sm leading-relaxed shadow-sm",
            isUser &&
              "border-primary bg-primary px-4 py-3 text-primary-foreground shadow-inset",
            isAssistant &&
              "border-border/80 bg-card/95 p-4 text-card-foreground shadow-premium sm:p-5",
            isError &&
              "border-destructive/30 bg-destructive/10 px-4 py-3 text-destructive"
          )}
        >
          {isAssistant ? (
            <div className="mb-3 flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.12em] text-muted-foreground">
              <Sparkles aria-hidden="true" className="h-4 w-4 text-primary" />
              <span>Resposta</span>
            </div>
          ) : null}

          {isError ? (
            <div className="flex gap-2">
              <AlertTriangle aria-hidden="true" className="mt-0.5 h-4 w-4 shrink-0" />
              <p className="break-words whitespace-pre-wrap font-medium">{normalizeErrorContent(message.content)}</p>
            </div>
          ) : isAssistant ? (
            <MarkdownContent content={message.content} />
          ) : (
            <p className="break-words whitespace-pre-wrap font-medium">{message.content}</p>
          )}

          {showSql || showChart || showDebug ? (
            <div className="mt-4 space-y-3">
              {showSql ? <SqlBlock sql={metadata.sql} /> : null}
              {showChart ? <ChartPanel chart={metadata.chart} /> : null}
              {showDebug ? <DebugPanel metadata={metadata} /> : null}
            </div>
          ) : null}

          {!isUser && (executionTime || isAssistant) ? (
            <div className="mt-4 flex flex-wrap items-center gap-2 border-t border-border/70 pt-3 text-xs text-muted-foreground">
              {executionTime ? (
                <span className="inline-flex items-center gap-1 font-medium">
                  <Clock3 aria-hidden="true" className="h-3.5 w-3.5" />
                  {executionTime}
                </span>
              ) : null}

              {isAssistant ? (
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  onClick={handleCopy}
                  className="ml-auto h-8 px-2 text-xs"
                >
                  {copied ? (
                    <Check aria-hidden="true" className="h-3.5 w-3.5" />
                  ) : (
                    <Copy aria-hidden="true" className="h-3.5 w-3.5" />
                  )}
                  <span>{copied ? "Copiado" : "Copiar"}</span>
                </Button>
              ) : null}
            </div>
          ) : null}
        </div>
      </div>
    </article>
  );
}
