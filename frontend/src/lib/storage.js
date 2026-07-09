function getDefaultStorage() {
  try {
    if (typeof globalThis !== "undefined" && "localStorage" in globalThis) {
      return globalThis.localStorage;
    }
  } catch {
    return null;
  }

  return null;
}

export function readStorage(key, fallback = null, storage = getDefaultStorage()) {
  try {
    if (!storage) return fallback;

    const value = storage.getItem(key);
    return value ?? fallback;
  } catch {
    return fallback;
  }
}

export function writeStorage(key, value, storage = getDefaultStorage()) {
  try {
    if (!storage) return false;

    storage.setItem(key, value);
    return true;
  } catch {
    return false;
  }
}

export function readJsonStorage(key, fallback = null, storage = getDefaultStorage()) {
  try {
    const value = readStorage(key, null, storage);
    if (value == null) return fallback;

    return JSON.parse(value);
  } catch {
    return fallback;
  }
}

export function writeJsonStorage(key, value, storage = getDefaultStorage()) {
  try {
    return writeStorage(key, JSON.stringify(value), storage);
  } catch {
    return false;
  }
}

export function removeStorage(key, storage = getDefaultStorage()) {
  try {
    if (!storage) return false;

    storage.removeItem(key);
    return true;
  } catch {
    return false;
  }
}
