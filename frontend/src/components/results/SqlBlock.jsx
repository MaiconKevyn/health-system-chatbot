import { useState } from "react";
import { Check, Copy } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";

export function SqlBlock({ sql }) {
  const text = String(sql ?? "").trim();
  const [copied, setCopied] = useState(false);

  if (!text) return null;

  async function handleCopy() {
    try {
      if (typeof navigator === "undefined" || !navigator.clipboard?.writeText) {
        throw new Error("Clipboard API indisponivel.");
      }

      await navigator.clipboard.writeText(text);
      setCopied(true);
      toast.success("SQL copiada.");
      window.setTimeout(() => setCopied(false), 1400);
    } catch (error) {
      toast.error("Nao foi possivel copiar a SQL.");
    }
  }

  return (
    <section className="overflow-hidden rounded-lg border border-border bg-muted/30">
      <div className="flex min-h-10 items-center justify-between gap-3 border-b border-border px-3 py-2">
        <h3 className="text-xs font-semibold uppercase tracking-[0.12em] text-muted-foreground">SQL</h3>
        <Button type="button" variant="ghost" size="sm" onClick={handleCopy} className="h-8 px-2 text-xs">
          {copied ? (
            <Check aria-hidden="true" className="h-3.5 w-3.5" />
          ) : (
            <Copy aria-hidden="true" className="h-3.5 w-3.5" />
          )}
          <span>{copied ? "Copiado" : "Copiar"}</span>
        </Button>
      </div>
      <pre className="thin-scrollbar overflow-x-auto p-3 text-xs leading-relaxed">
        <code className="font-mono">{text}</code>
      </pre>
    </section>
  );
}
