import { Loader2, SendHorizontal } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { MAX_MESSAGE_LENGTH } from "@/lib/constants";
import { cn } from "@/lib/utils";

export function ChatComposer({ value, onChange, onSubmit, canSend, isLoading }) {
  const currentLength = value.length;
  const isOverLimit = currentLength > MAX_MESSAGE_LENGTH;

  function handleSubmit(event) {
    event.preventDefault();
    if (canSend) onSubmit();
  }

  function handleKeyDown(event) {
    if ((event.key === "Enter" && !event.shiftKey) || ((event.ctrlKey || event.metaKey) && event.key === "Enter")) {
      event.preventDefault();
      if (canSend) onSubmit();
    }
  }

  return (
    <form
      onSubmit={handleSubmit}
      className="sticky bottom-0 z-10 border-t border-border/80 bg-card/95 p-3 shadow-[0_-18px_48px_-32px_hsl(var(--foreground)/0.55)] backdrop-blur-xl sm:p-4"
    >
      <div className="flex items-end gap-3">
        <div className="min-w-0 flex-1">
          <Textarea
            value={value}
            onChange={(event) => onChange(event.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Pergunte em linguagem natural sobre os dados..."
            disabled={isLoading}
            aria-label="Mensagem para o agente"
            aria-invalid={isOverLimit}
            className="max-h-44 min-h-24 resize-none bg-background/85 pr-4 leading-relaxed"
          />
          <div className="mt-2 flex justify-end">
            <span
              className={cn(
                "text-xs font-medium text-muted-foreground",
                isOverLimit && "text-destructive"
              )}
            >
              {currentLength}/{MAX_MESSAGE_LENGTH}
            </span>
          </div>
        </div>

        <Button
          type="submit"
          disabled={!canSend}
          className="h-11 shrink-0 px-4"
          aria-label="Enviar consulta"
        >
          {isLoading ? (
            <Loader2 aria-hidden="true" className="h-4 w-4 animate-spin" />
          ) : (
            <SendHorizontal aria-hidden="true" className="h-4 w-4" />
          )}
          <span className="hidden sm:inline">Enviar</span>
        </Button>
      </div>
    </form>
  );
}
