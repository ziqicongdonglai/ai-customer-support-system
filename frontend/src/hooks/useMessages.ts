"use client";

import {
  useEffect,
  useRef,
  useState,
} from "react";

import { getMessages } from "@/lib/api";

import type { ChatMessage } from "@/types/chat";

interface MessagesState {
  /**
   * 当前 state 中保存的是哪个
   * Conversation 的数据。
   */
  conversationId: string | null;

  messages: ChatMessage[];

  error: string | null;
}

export function useMessages(
  conversationId: string | null,
) {
  const [state, setState] =
    useState<MessagesState>({
      conversationId: null,
      messages: [],
      error: null,
    });

  /**
   * Message Request 的版本号。
   *
   * 用于解决：
   *
   * Request A 发出
   * ↓
   * 用户切到 B
   * ↓
   * Request B 发出
   * ↓
   * B 先返回
   * ↓
   * A 后返回
   *
   * 如果没有版本保护，
   * 旧的 A Response 可能重新覆盖 B。
   *
   * 只有最后一次 Request
   * 才允许更新 Messages State。
   */
  const requestVersionRef = useRef(0);

  /**
   * selectedConversationId 改变时，
   * 自动加载对应 Conversation History。
   */
  useEffect(() => {
    if (!conversationId) {
      /**
       * 当前进入 New Chat。
       *
       * 同时让之前还没有完成的
       * Message Request 失效。
       */
      requestVersionRef.current += 1;

      return;
    }

    /**
     * 当前 Conversation 的 History
     * 已经存在于 state 中。
     *
     * 不需要因为 selection render
     * 再重复请求一次。
     */
    if (
      state.conversationId === conversationId
    ) {
      return;
    }

    const currentConversationId =
      conversationId;

    /**
     * 当前请求获得一个新的版本号。
     */
    const requestVersion =
      ++requestVersionRef.current;

    let cancelled = false;

    async function load() {
      try {
        const data =
          await getMessages(
            currentConversationId,
          );

        /**
         * 两种情况下丢弃 Response：
         *
         * 1. Effect 已经 cleanup；
         * 2. 后面已经出现了更新的 Request。
         */
        if (
          cancelled ||
          requestVersion !==
            requestVersionRef.current
        ) {
          return;
        }

        setState({
          conversationId:
            currentConversationId,
          messages: data.messages,
          error: null,
        });
      } catch (error) {
        if (
          cancelled ||
          requestVersion !==
            requestVersionRef.current
        ) {
          return;
        }

        setState({
          conversationId:
            currentConversationId,
          messages: [],
          error:
            error instanceof Error
              ? error.message
              : "Failed to load messages",
        });
      }
    }

    void load();

    return () => {
      cancelled = true;
    };
  }, [
    conversationId,
    state.conversationId,
  ]);

  /**
   * 主动重新同步某个 Conversation History。
   *
   * 与以前 refreshKey 最大的区别：
   *
   * 以前：
   * refetchMessages()
   * 只是通知 Effect “之后重新加载一下”。
   *
   * 现在：
   * await refetchMessages(id)
   * 会真正等待 GET /messages 完成。
   *
   * ChatPanel 因此可以做到：
   *
   * Temporary Messages
   * ↓
   * await Persistent History
   * ↓
   * clear Temporary Messages
   */
  async function refetchMessages(
    targetConversationId: string,
  ): Promise<void> {
    const requestVersion =
      ++requestVersionRef.current;

    try {
      const data =
        await getMessages(
          targetConversationId,
        );

      /**
       * 如果等待过程中用户已经触发
       * 另一条更新的 Message Request，
       * 当前 Response 不再有资格更新 state。
       */
      if (
        requestVersion !==
        requestVersionRef.current
      ) {
        return;
      }

      setState({
        conversationId:
          targetConversationId,
        messages: data.messages,
        error: null,
      });
    } catch (error) {
      if (
        requestVersion !==
        requestVersionRef.current
      ) {
        return;
      }

      setState({
        conversationId:
          targetConversationId,
        messages: [],
        error:
          error instanceof Error
            ? error.message
            : "Failed to load messages",
      });

      /**
       * 主动 refetch 的调用方需要知道
       * History hand-off 是否失败，
       * 因此这里继续向上抛出异常。
       */
      throw error;
    }
  }

  /**
   * state 中的数据只有属于当前
   * selectedConversationId 时才允许展示。
   *
   * 避免切换 Conversation 的瞬间，
   * 短暂显示上一个 Conversation 的内容。
   */
  const hasCurrentData =
    state.conversationId === conversationId;

  return {
    messages:
      conversationId && hasCurrentData
        ? state.messages
        : [],

    loading:
      conversationId !== null &&
      !hasCurrentData,

    error:
      conversationId && hasCurrentData
        ? state.error
        : null,

    refetchMessages,
  };
}