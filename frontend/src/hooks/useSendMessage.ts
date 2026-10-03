"use client";

import { useState } from "react";

import { sendChatMessage } from "@/lib/api";
import type {
  ChatRequest,
  ChatResponse,
} from "@/types/chat";

export function useSendMessage() {
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(
    null,
  );

  async function sendMessage(
    request: ChatRequest,
  ): Promise<ChatResponse | null> {
    if (sending) {
      return null;
    }

    try {
      setSending(true);
      setError(null);

      return await sendChatMessage(request);
    } catch (error) {
      setError(
        error instanceof Error
          ? error.message
          : "Failed to send message",
      );

      return null;
    } finally {
      setSending(false);
    }
  }

  return {
    sendMessage,
    sending,
    error,
  };
}