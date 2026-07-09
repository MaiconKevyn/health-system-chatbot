import { BarChart3, MessageSquareText, ShieldCheck } from "lucide-react";

import { EXAMPLE_QUESTIONS } from "@/lib/constants";

const STEPS = [
  {
    title: "Pergunta",
    description: "Descreva o recorte ou indicador em linguagem natural.",
    icon: MessageSquareText
  },
  {
    title: "Validacao SQL",
    description: "O agente Pydantic AI monta e valida a consulta antes de executar.",
    icon: ShieldCheck
  },
  {
    title: "Resposta visual",
    description: "Receba sintese, SQL e graficos quando houver dados chartaveis.",
    icon: BarChart3
  }
];

export function WelcomePanel({ onQuestionSelect }) {
  return (
    <div className="flex min-h-full items-center justify-center p-5 sm:p-8">
      <div className="w-full max-w-3xl space-y-6">
        <div className="space-y-3">
          <h2 className="text-2xl leading-tight text-foreground sm:text-3xl">
            Como posso consultar seus dados?
          </h2>
          <p className="max-w-2xl text-sm leading-relaxed text-muted-foreground sm:text-base">
            Faca uma pergunta sobre o banco em linguagem natural. O workspace transforma a
            intencao em SQL validado e apresenta a resposta em um formato facil de revisar.
          </p>
        </div>

        <ol className="grid gap-3 sm:grid-cols-3">
          {STEPS.map(({ title, description, icon: Icon }) => (
            <li
              key={title}
              className="rounded-lg border border-border/80 bg-background/70 p-3 shadow-sm"
            >
              <div className="mb-2 flex items-center gap-2 text-sm font-semibold text-foreground">
                <Icon aria-hidden="true" className="h-4 w-4 text-primary" />
                <span>{title}</span>
              </div>
              <p className="text-sm leading-relaxed text-muted-foreground">{description}</p>
            </li>
          ))}
        </ol>

        <div className="grid gap-2 sm:grid-cols-2">
          {EXAMPLE_QUESTIONS.map((question) => (
            <button
              key={question}
              type="button"
              onClick={() => onQuestionSelect(question)}
              className="rounded-lg border border-border/80 bg-card/80 px-3 py-3 text-left text-sm font-medium leading-relaxed text-foreground shadow-sm transition-colors hover:border-primary/50 hover:bg-primary/5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
            >
              {question}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
