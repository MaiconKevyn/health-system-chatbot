import { useCallback, useEffect, useState } from "react";

import { getAgentHealth, getWebHealth } from "../lib/api";

export function useServerHealth() {
  const [status, setStatus] = useState("checking");

  const checkServerStatus = useCallback(async () => {
    setStatus("checking");

    try {
      await getWebHealth();
      const agentHealth = await getAgentHealth();

      setStatus(agentHealth?.agent_status === "online" ? "online" : "offline");
    } catch {
      setStatus("offline");
    }
  }, []);

  useEffect(() => {
    checkServerStatus();
  }, [checkServerStatus]);

  return { status, setStatus, checkServerStatus };
}
