import { Database, ShieldCheck } from "lucide-react";

import { Button } from "@/components/ui/button";
import { EXAMPLE_QUESTIONS } from "@/lib/constants";

export function Sidebar({ onQuestionSelect, onOpenSchema }) {
  return (
    <aside className="workspace-panel order-2 h-fit p-4 lg:sticky lg:top-4 lg:order-1">
      <div className="space-y-5">
        <section aria-labelledby="starter-questions-title" className="space-y-3">
          <div>
            <h2 id="starter-questions-title" className="text-base leading-tight text-foreground">
              Perguntas iniciais
            </h2>
            <p className="mt-1 text-sm text-muted-foreground">
              Escolha uma consulta para preencher o chat.
            </p>
          </div>

          <div className="grid gap-2">
            {EXAMPLE_QUESTIONS.map((question) => (
              <button
                key={question}
                type="button"
                onClick={() => onQuestionSelect(question)}
                className="rounded-lg border border-border/80 bg-background/70 px-3 py-3 text-left text-sm font-medium leading-relaxed text-foreground shadow-sm transition-colors hover:border-primary/50 hover:bg-primary/5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
              >
                {question}
              </button>
            ))}
          </div>
        </section>

        <Button type="button" variant="secondary" onClick={onOpenSchema} className="w-full">
          <Database aria-hidden="true" className="h-4 w-4" />
          Explorar schema
        </Button>

        <section className="rounded-lg border border-border/80 bg-muted/60 p-4">
          <div className="mb-2 flex items-center gap-2 text-sm font-semibold text-foreground">
            <ShieldCheck aria-hidden="true" className="h-4 w-4 text-primary" />
            Contexto da sessao
          </div>
          <p className="text-sm leading-relaxed text-muted-foreground">
            As mensagens ficam neste navegador e mantem o identificador da conversa para o
            chatbot responder com continuidade.
          </p>
        </section>
      </div>
    </aside>
  );
}
