import { AppShell } from "./components/layout/AppShell";
import { useChat } from "./hooks/use-chat";
import { useDebugMode } from "./hooks/use-debug-mode";
import { useSchemaExplorer } from "./hooks/use-schema-explorer";
import { useServerHealth } from "./hooks/use-server-health";
import { useTheme } from "./hooks/use-theme";

export default function App() {
  const theme = useTheme();
  const debug = useDebugMode();
  const health = useServerHealth();
  const chat = useChat({
    debugEnabled: debug.debugEnabled,
    onServerStatusChange: health.setStatus
  });
  const schema = useSchemaExplorer();

  return (
    <AppShell
      theme={theme}
      debug={debug}
      health={health}
      chat={chat}
      schema={schema}
    />
  );
}
