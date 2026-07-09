import { ChatComposer } from "./ChatComposer";
import { MessageList } from "./MessageList";
import { WelcomePanel } from "./WelcomePanel";

export function ChatWorkspace({ chat, debugEnabled }) {
  return (
    <section
      aria-label="Workspace de chat"
      className="workspace-panel order-1 flex h-[calc(100vh-14rem)] min-h-[560px] min-w-0 flex-col overflow-hidden border-l border-t lg:order-2 lg:h-auto lg:min-h-[calc(100vh-9rem)]"
    >
      <div className="thin-scrollbar min-h-0 flex-1 overflow-y-auto">
        {chat.hasMessages ? (
          <MessageList
            messages={chat.messages}
            isLoading={chat.isLoading}
            debugEnabled={debugEnabled}
          />
        ) : (
          <WelcomePanel onQuestionSelect={chat.fillQuestion} />
        )}
      </div>

      <ChatComposer
        value={chat.input}
        onChange={chat.setInput}
        onSubmit={chat.submitMessage}
        canSend={chat.canSend}
        isLoading={chat.isLoading}
      />
    </section>
  );
}
