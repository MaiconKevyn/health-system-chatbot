import { AppHeader } from "./AppHeader";
import { Sidebar } from "./Sidebar";
import { ChatWorkspace } from "../chat/ChatWorkspace";
import { SchemaExplorer } from "../schema/SchemaExplorer";

export function AppShell({ theme, debug, health, chat, schema }) {
  return (
    <div className="min-h-screen overflow-x-hidden bg-background text-foreground">
      <div className="mx-auto flex min-h-screen w-full max-w-[1440px] flex-col px-4 py-4 sm:px-6 lg:px-8">
        <AppHeader
          theme={theme}
          debug={debug}
          health={health}
          onOpenSchema={schema.openExplorer}
          onClearChat={chat.clearChat}
          hasMessages={chat.hasMessages}
        />

        <main className="grid flex-1 gap-4 pb-6 lg:grid-cols-[320px_minmax(0,1fr)] lg:gap-6">
          <Sidebar onQuestionSelect={chat.fillQuestion} onOpenSchema={schema.openExplorer} />
          <ChatWorkspace chat={chat} debugEnabled={debug.debugEnabled} />
        </main>
      </div>

      <SchemaExplorer schema={schema} />
    </div>
  );
}
