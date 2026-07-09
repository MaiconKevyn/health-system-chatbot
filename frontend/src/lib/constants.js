export const API_BASE_URL = "/api";

export const STORAGE_KEYS = {
  sessionId: "chatSessionId",
  chatHistory: "chatHistory",
  theme: "theme",
  debugMode: "debugModeEnabled"
};

export const MAX_CONVERSATION_TURNS = 10;
export const MAX_HISTORY_MESSAGES = MAX_CONVERSATION_TURNS * 2;
export const MAX_MESSAGE_LENGTH = 1000;

export const EXAMPLE_QUESTIONS = [
  "Quantas internacoes existem?",
  "Quantos partos aconteceram?",
  "Qual a distribuicao de internacoes por sexo?",
  "Gere um grafico de barras com a distribuicao de internacoes por sexo."
];

export const SERVER_STATUS_LABELS = {
  checking: "Verificando...",
  online: "Online",
  offline: "API offline"
};
