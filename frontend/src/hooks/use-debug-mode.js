import { useCallback, useEffect, useState } from "react";

import { STORAGE_KEYS } from "../lib/constants";
import { readStorage, writeStorage } from "../lib/storage";

export function useDebugMode() {
  const [debugEnabled, setDebugEnabled] = useState(
    () => readStorage(STORAGE_KEYS.debugMode, "false") === "true"
  );

  useEffect(() => {
    writeStorage(STORAGE_KEYS.debugMode, String(debugEnabled));
  }, [debugEnabled]);

  const toggleDebugMode = useCallback(() => {
    setDebugEnabled((currentDebugEnabled) => !currentDebugEnabled);
  }, []);

  return { debugEnabled, setDebugEnabled, toggleDebugMode };
}
