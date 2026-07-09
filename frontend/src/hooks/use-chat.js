import { useCallback, useMemo, useRef, useState } from "react";
import { toast } from "sonner";

import { sendQuery } from "../lib/api";
import { MAX_MESSAGE_LENGTH, STORAGE_KEYS } from "../lib/constants";
import {
  buildUserFacingError,
  createMessage,
  createSessionId,
  normalizeQueryResponse,
  trimPersistedHistory
} from "../lib/chat-utils";
import {
  readJsonStorage,
  readStorage,
  removeStorage,
  writeJsonStorage,
  writeStorage
} from "../lib/storage";

function ensureSessionId() {
  const storedSessionId = readStorage(STORAGE_KEYS.sessionId, "");
  if (storedSessionId) return storedSessionId;

  const nextSessionId = createSessionId();
  writeStorage(STORAGE_KEYS.sessionId, nextSessionId);
  return nextSessionId;
}

function readInitialMessages() {
  const storedMessages = readJsonStorage(STORAGE_KEYS.chatHistory, []);
  return Array.isArray(storedMessages) ? storedMessages : [];
}

export function useChat({ debugEnabled = false, onServerStatusChange } = {}) {
  const [input, setInput] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [sessionId, setSessionId] = useState(ensureSessionId);
  const [messages, setMessages] = useState(readInitialMessages);
  const messagesRef = useRef(messages);
  const requestSequenceRef = useRef(0);
  const submittingRef = useRef(false);

  const hasMessages = messages.length > 0;
  const canSend = input.trim().length > 0 && input.length <= MAX_MESSAGE_LENGTH && !isLoading;

  const persistMessages = useCallback((nextMessages) => {
    writeJsonStorage(STORAGE_KEYS.chatHistory, trimPersistedHistory(nextMessages));
  }, []);

  const replaceMessages = useCallback((nextMessages) => {
    messagesRef.current = nextMessages;
    setMessages(nextMessages);
  }, []);

  const addMessage = useCallback(
    (message) => {
      const nextMessages = [...messagesRef.current, message];
      messagesRef.current = nextMessages;
      persistMessages(nextMessages);
      setMessages(nextMessages);
    },
    [persistMessages]
  );

  const fillQuestion = useCallback((question) => {
    setInput(question);
  }, []);

  const clearChat = useCallback(() => {
    const nextSessionId = createSessionId();

    requestSequenceRef.current += 1;
    submittingRef.current = false;
    setIsLoading(false);
    replaceMessages([]);
    setSessionId(nextSessionId);
    writeStorage(STORAGE_KEYS.sessionId, nextSessionId);
    removeStorage(STORAGE_KEYS.chatHistory);
  }, [replaceMessages]);

  const submitMessage = useCallback(async () => {
    const question = input.trim();

    if (!question || submittingRef.current || input.length > MAX_MESSAGE_LENGTH) {
      return;
    }

    const requestId = requestSequenceRef.current + 1;
    requestSequenceRef.current = requestId;
    submittingRef.current = true;
    setIsLoading(true);
    setInput("");
    addMessage(createMessage(question, { type: "user" }));

    try {
      const response = await sendQuery({ question, sessionId, debug: debugEnabled });

      if (requestSequenceRef.current !== requestId) {
        return;
      }

      if (response?.session_id) {
        setSessionId(response.session_id);
        writeStorage(STORAGE_KEYS.sessionId, response.session_id);
      }

      const normalizedResponse = normalizeQueryResponse(response, debugEnabled);
      addMessage(
        createMessage(normalizedResponse.content, {
          type: normalizedResponse.type,
          metadata: normalizedResponse.metadata
        })
      );
      onServerStatusChange?.("online");
    } catch (error) {
      if (requestSequenceRef.current !== requestId) {
        return;
      }

      onServerStatusChange?.("offline");
      addMessage(createMessage(buildUserFacingError(error), { type: "error" }));
      toast.error("Nao foi possivel concluir a consulta. Verifique a API e tente novamente.");
    } finally {
      if (requestSequenceRef.current === requestId) {
        submittingRef.current = false;
        setIsLoading(false);
      }
    }
  }, [addMessage, debugEnabled, input, onServerStatusChange, sessionId]);

  return useMemo(
    () => ({
      input,
      setInput,
      isLoading,
      sessionId,
      messages,
      hasMessages,
      canSend,
      fillQuestion,
      clearChat,
      submitMessage
    }),
    [
      canSend,
      clearChat,
      fillQuestion,
      hasMessages,
      input,
      isLoading,
      messages,
      sessionId,
      submitMessage
    ]
  );
}
