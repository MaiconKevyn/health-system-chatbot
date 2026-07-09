import {
  Bug,
  Database,
  DatabaseZap,
  Moon,
  RefreshCw,
  Sun,
  Trash2
} from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger
} from "@/components/ui/tooltip";
import { SERVER_STATUS_LABELS } from "@/lib/constants";
import { cn } from "@/lib/utils";

const STATUS_STYLES = {
  checking: "border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-300",
  online: "border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300",
  offline: "border-destructive/30 bg-destructive/10 text-destructive"
};

function IconButton({ label, children, ...props }) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Button aria-label={label} size="icon" variant="outline" {...props}>
          {children}
        </Button>
      </TooltipTrigger>
      <TooltipContent>{label}</TooltipContent>
    </Tooltip>
  );
}

export function AppHeader({
  theme,
  debug,
  health,
  onOpenSchema,
  onClearChat,
  hasMessages
}) {
  const statusLabel = SERVER_STATUS_LABELS[health.status] || SERVER_STATUS_LABELS.offline;
  const isDark = theme.theme === "dark";

  const handleClearChat = () => {
    if (window.confirm("Limpar toda a conversa e iniciar uma nova sessao?")) {
      onClearChat();
    }
  };

  return (
    <TooltipProvider delayDuration={150}>
      <header className="mb-4 flex flex-col gap-4 rounded-lg border border-border/70 bg-card/90 px-4 py-4 shadow-premium backdrop-blur-xl sm:px-5 lg:flex-row lg:items-center lg:justify-between">
        <div className="flex min-w-0 items-center gap-3">
          <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg bg-primary text-primary-foreground shadow-inset">
            <DatabaseZap aria-hidden="true" className="h-5 w-5" />
          </div>
          <div className="min-w-0">
            <h1 className="truncate text-xl leading-tight text-foreground sm:text-2xl">
              Health System Chatbot
            </h1>
            <p className="text-sm font-medium text-muted-foreground">
              Pydantic AI Text-to-SQL workspace
            </p>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={health.checkServerStatus}
            className={cn(
              "inline-flex h-10 items-center gap-2 rounded-lg border px-3 text-sm font-semibold transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background",
              STATUS_STYLES[health.status] || STATUS_STYLES.offline
            )}
            aria-label="Atualizar status do servidor"
          >
            <RefreshCw
              aria-hidden="true"
              className={cn("h-4 w-4", health.status === "checking" && "animate-spin")}
            />
            <span>{statusLabel}</span>
          </button>

          <Button
            type="button"
            variant={debug.debugEnabled ? "secondary" : "outline"}
            onClick={debug.toggleDebugMode}
            aria-pressed={debug.debugEnabled}
            className="h-10 px-3"
          >
            <Bug aria-hidden="true" className="h-4 w-4" />
            <span>Debug</span>
          </Button>

          <Button type="button" variant="outline" onClick={onOpenSchema} className="h-10 px-3">
            <Database aria-hidden="true" className="h-4 w-4" />
            <span>Schema</span>
          </Button>

          <IconButton
            label={isDark ? "Usar tema claro" : "Usar tema escuro"}
            type="button"
            onClick={theme.toggleTheme}
          >
            {isDark ? (
              <Sun aria-hidden="true" className="h-4 w-4" />
            ) : (
              <Moon aria-hidden="true" className="h-4 w-4" />
            )}
          </IconButton>

          <IconButton
            label="Limpar conversa"
            type="button"
            onClick={handleClearChat}
            disabled={!hasMessages}
          >
            <Trash2 aria-hidden="true" className="h-4 w-4" />
          </IconButton>
        </div>
      </header>
    </TooltipProvider>
  );
}
