import { useCallback, useEffect, useState } from "react";

import { STORAGE_KEYS } from "../lib/constants";
import { readStorage, writeStorage } from "../lib/storage";

export function useTheme() {
  const [theme, setTheme] = useState(() => readStorage(STORAGE_KEYS.theme, "light"));

  useEffect(() => {
    if (typeof document !== "undefined") {
      document.documentElement.classList.toggle("dark", theme === "dark");
      document.documentElement.setAttribute("data-theme", theme);
    }

    writeStorage(STORAGE_KEYS.theme, theme);
  }, [theme]);

  const toggleTheme = useCallback(() => {
    setTheme((currentTheme) => (currentTheme === "dark" ? "light" : "dark"));
  }, []);

  return { theme, setTheme, toggleTheme };
}
