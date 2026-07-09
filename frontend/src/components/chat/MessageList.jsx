import { useEffect, useRef } from "react";
import { Brain, Loader2 } from "lucide-react";

import { MAX_HISTORY_MESSAGES } from "@/lib/constants";

import { MessageItem } from "./MessageItem";

export function MessageList({ messages, isLoading, debugEnabled }) {
  const bottomRef = useRef(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, isLoading]);

  return (
    <div className="space-y-5 p-4 sm:p-6">
      {messages.length >= MAX_HISTORY_MESSAGES ? (
        <div className="mx-auto flex w-fit max-w-full items-center gap-2 rounded-full border border-border/80 bg-muted/70 px-3 py-2 text-xs font-semibold text-muted-foreground">
          <Brain aria-hidden="true" className="h-4 w-4 text-primary" />
          <span>Exibindo as ultimas {MAX_HISTORY_MESSAGES} mensagens do contexto.</span>
        </div>
      ) : null}

      {messages.map((message) => (
        <MessageItem key={message.id} message={message} debugEnabled={debugEnabled} />
      ))}

      {isLoading ? (
        <div className="flex justify-start">
          <div className="flex max-w-[min(100%,680px)] items-center gap-3 rounded-lg border border-border/80 bg-card/95 px-4 py-3 text-sm font-medium text-muted-foreground shadow-sm">
            <Loader2 aria-hidden="true" className="h-4 w-4 animate-spin text-primary" />
            <span>Processando consulta</span>
          </div>
        </div>
      ) : null}

      <div ref={bottomRef} />
    </div>
  );
}
