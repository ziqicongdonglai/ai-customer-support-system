"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import { useChatContext } from "@/context/ChatContext";
import { useMessages } from "@/hooks/useMessages";
import { useStreamingChat } from "@/hooks/useStreamingChat";

import ReturnEligibilityWorkflow from "@/components/workflow/ReturnEligibilityWorkflow";

import MessageInput from "./MessageInput";
import MessageList from "./MessageList";

import type { ChatMessage, ChatRequest } from "@/types/chat";

export default function ChatPanel() {
  const { newChatResetKey } = useChatContext();
  // RAG toggle 是跨 New Chat 保留的用户偏好，不属于失败请求留下的 session 临时状态。
  const [useRag, setUseRag] = useState(false);

  // ChatPanel 保留跨 session 状态；ChatPanelSession 拥有单次前端 Chat session 的临时状态。
  // key 变化时整体 remount，可一次丢弃 stale state，避免逐字段 reset 漏掉新增状态。
  return (
    <ChatPanelSession
      key={newChatResetKey}
      useRag={useRag}
      onUseRagChange={setUseRag}
    />
  );
}

function ChatPanelSession({
  useRag,
  onUseRagChange,
}: {
  useRag: boolean;
  onUseRagChange: (enabled: boolean) => void;
}) {
  const bottomRef = useRef<HTMLDivElement | null>(null);

  const {
    selectedConversationId,
    setSelectedConversationId,
    selectionRestored,
    refreshConversations,
    streamingActive,
    setStreamingActive,
    subscribeConversationDeleted,
  } = useChatContext();

  const {
    messages,
    loading,
    error: messagesError,
    refetchMessages,
  } = useMessages(selectedConversationId);

  const {
    startStreaming,
    streamingMessage: currentStreamingMessage,
    error: currentStreamError,
    clearStreamingMessage,
  } = useStreamingChat();

  /**
   * Optimistic User Message。
   *
   * Backend History 还没接管 UI 前，
   * 先让用户刚刚发送的消息立即出现在页面上。
   */
  const [pendingUserMessage, setPendingUserMessage] =
    useState<ChatMessage | null>(null);

  /**
   * 当前这一轮临时消息实际属于哪个 Conversation。
   *
   * Existing Chat：
   * 发送开始时就已经知道 Conversation ID。
   *
   * New Chat：
   * 开始时为 null，
   * 收到 SSE start event 后更新为 Backend 创建的 ID。
   */
  const [temporaryConversationId, setTemporaryConversationId] = useState<
    string | null
  >(null);

  /**
   * Conversation 被删除后，用于隐藏仍然残留的
   * temporary / streaming state。
   */
  const [clearedConversationId, setClearedConversationId] = useState<
    string | null
  >(null);

  // handoff 只存在于当前 Chat session 内存中，不写 localStorage；
  // Conversation scope 防止切换对话后打开错误面板，requestId 则把它建模为一次性事件。
  const nextWorkflowHandoffRequestIdRef = useRef(0);
  const [returnEligibilityHandoff, setReturnEligibilityHandoff] = useState<{
    conversationId: string;
    requestId: number;
  } | null>(null);

  /**
   * handleSend 是一个长生命周期 async function。
   *
   * selectedConversationId 会因为用户切换 Sidebar 而变化，
   * 但 handleSend 内最初捕获的值不会自动变成最新值。
   *
   * Ref 用来在 Streaming 结束时读取：
   * “用户现在实际正在看哪个 Conversation？”
   */
  const selectedConversationIdRef = useRef(selectedConversationId);

  useEffect(() => {
    selectedConversationIdRef.current = selectedConversationId;
  }, [selectedConversationId]);

  const temporaryStateWasCleared =
    clearedConversationId !== null &&
    clearedConversationId === temporaryConversationId;

  const streamingMessage = temporaryStateWasCleared
    ? null
    : currentStreamingMessage;

  const streamError = temporaryStateWasCleared ? null : currentStreamError;

  /**
   * 页面最终展示的数据由三部分组成：
   *
   * 1. Backend Persistent History
   * 2. Optimistic User Message
   * 3. Temporary Streaming Assistant
   *
   * Backend 中空的 streaming Assistant 会被过滤，
   * 避免和 Frontend Streaming Assistant 重复显示。
   */
  const displayMessages = useMemo(
    () => [
      ...messages.filter(
        (message) =>
          !(
            message.role === "assistant" &&
            message.status === "streaming" &&
            !message.content
          ),
      ),

      ...(pendingUserMessage &&
      (!selectedConversationId ||
        pendingUserMessage.conversation_id === selectedConversationId)
        ? [pendingUserMessage]
        : []),

      ...(streamingMessage &&
      (!selectedConversationId ||
        streamingMessage.conversation_id === selectedConversationId)
        ? [streamingMessage]
        : []),
    ],
    [messages, pendingUserMessage, selectedConversationId, streamingMessage],
  );

  async function handleSend(message: string): Promise<boolean> {
    /**
     * Request Snapshot：
     *
     * 记录“这一轮请求是从哪个 Conversation 发出去的”。
     * 这个值从发送开始以后就不应该再变化。
     */
    const requestConversationId = selectedConversationId;

    const isNewConversationRequest = requestConversationId === null;

    setClearedConversationId(null);
    setStreamingActive(true);

    setTemporaryConversationId(requestConversationId);

    setPendingUserMessage({
      id: crypto.randomUUID(),
      role: "user",
      content: message,
      status: "completed",
      sources: [],
      temporary: true,
      conversation_id: requestConversationId ?? undefined,
    });

    const request: ChatRequest = {
      message,
      use_rag: useRag,
      ...(requestConversationId
        ? {
            conversation_id: requestConversationId,
          }
        : {}),
    };

    try {
      const conversationId = await startStreaming(request, {
        onConversationStarted: (startedConversationId) => {
          /**
           * Existing Conversation 已经有 ID，
           * 不需要重新处理 identity。
           */
          if (!isNewConversationRequest) {
            return;
          }

          /**
           * SSE start 表示：
           * Backend 已经正式创建了 New Conversation。
           */
          setTemporaryConversationId(startedConversationId);

          refreshConversations();
        },
        onWorkflowHandoff: (kind, handoffConversationId) => {
          if (kind === "return_eligibility") {
            // 每次 structured handoff 都生成新 requestId；相同 kind 连续到达时
            // 仍可被 Workflow UI 各消费一次，而不会变成持久 panelOpen 状态。
            setReturnEligibilityHandoff({
              conversationId: handoffConversationId,
              requestId: ++nextWorkflowHandoffRequestIdRef.current,
            });
          }
        },
      });

      /**
       * Streaming 成功以后进入：
       *
       * Temporary State
       *        ↓
       * Persistent History
       *
       * 的 hand-off。
       *
       * History 同步失败不应该被当作
       * LLM Generation 失败。
       */
      try {
        const currentSelectedConversationId = selectedConversationIdRef.current;

        if (isNewConversationRequest && conversationId) {
          if (currentSelectedConversationId === null) {
            /**
             * 用户一直留在 New Chat。
             *
             * 先把真实 History 准备好，
             * 再正式选中 Backend Conversation。
             */
            await refetchMessages(conversationId);

            /**
             * History 请求期间用户仍可能切换页面。
             *
             * 只有当前仍为 New Chat 时，
             * 才自动进入刚创建的 Conversation。
             */
            setSelectedConversationId((current) =>
              current === null ? conversationId : current,
            );
          } else if (currentSelectedConversationId === conversationId) {
            /**
             * 用户在 Streaming 过程中已经
             * 主动点击了 Sidebar 中的新 Conversation。
             *
             * 重新加载 History，
             * 让 Persistent Assistant 接管
             * Temporary Streaming Assistant。
             */
            await refetchMessages(conversationId);
          }

          /**
           * 如果用户已经切到了其他 Conversation B，
           * 不改变 selection，也不主动加载 A。
           *
           * A 的结果已经存在 Backend，
           * 用户以后再进入 A 时会正常加载。
           */
        } else if (requestConversationId) {
          /**
           * Existing Conversation 完成消息后，
           * 刷新 Sidebar，例如同步更新时间等变化。
           */
          refreshConversations();

          if (currentSelectedConversationId === requestConversationId) {
            /**
             * 用户仍然停留在原 Conversation：
             * 等 Persistent History 更新完成。
             */
            await refetchMessages(requestConversationId);
          }
        }

        /**
         * 只有 Persistent History 已经准备好，
         * 或者用户已经切离当前 Conversation，
         * Temporary State 才能安全退出。
         */
        setPendingUserMessage(null);
        clearStreamingMessage();
      } catch (historyError) {
        /**
         * LLM Generation 已经成功，
         * 这里只是 History 同步失败。
         *
         * 不返回 false，避免 MessageInput
         * 误以为发送失败并恢复已发送文本。
         *
         * 同时保留 Temporary Messages，
         * 避免页面突然丢失刚刚生成的内容。
         */
        console.error("Failed to sync persisted messages", historyError);
      }

      return true;
    } catch (error) {
      /**
       * 这里只处理真正的 Streaming /
       * Generation Failure。
       */
      console.error("Send message failed", error);

      setPendingUserMessage(null);

      return false;
    } finally {
      /**
       * streamingActive 表示整个发送生命周期：
       *
       * Streaming
       * +
       * Persistent History hand-off
       *
       * 因此要等到最后才释放。
       */
      setStreamingActive(false);
    }
  }

  /**
   * Conversation 被删除时，
   * 清理它仍然可能残留的 Temporary State。
   */
  useEffect(
    () =>
      subscribeConversationDeleted((deletedConversationId) => {
        setReturnEligibilityHandoff((current) =>
          current?.conversationId === deletedConversationId ? null : current,
        );

        if (temporaryConversationId !== deletedConversationId) {
          return;
        }

        setPendingUserMessage((current) =>
          current?.conversation_id === deletedConversationId ? null : current,
        );

        setClearedConversationId(deletedConversationId);
      }),
    [subscribeConversationDeleted, temporaryConversationId],
  );

  /**
   * Message 内容变化时自动跟随到底部。
   *
   * 当前 Streaming 每个 token 都可能触发滚动。
   * “用户主动向上滚动后停止 auto-scroll”
   * 留作后续 UX 优化。
   */
  useEffect(() => {
    bottomRef.current?.scrollIntoView({
      behavior: "smooth",
    });
  }, [displayMessages]);

  return (
    <section className="flex h-full min-w-0 flex-col">
      <header className="relative flex items-center justify-between gap-4 border-b border-gray-200 px-6 py-4">
        <h2 className="font-semibold text-gray-900">Chat</h2>
        <ReturnEligibilityWorkflow
          key={selectedConversationId ?? "no-conversation"}
          conversationId={selectedConversationId}
          openRequestId={
            // 只有当前选中的 Conversation 能收到 open request，避免异步 SSE
            // 在用户切换 Conversation 后打开另一条对话的 Workflow 面板。
            returnEligibilityHandoff?.conversationId === selectedConversationId
              ? returnEligibilityHandoff.requestId
              : null
          }
          onOpenRequestConsumed={(requestId) => {
            setReturnEligibilityHandoff((current) =>
              current?.requestId === requestId ? null : current,
            );
          }}
        />
      </header>

      <main className="flex-1 overflow-y-auto p-6">
        {selectionRestored &&
          !selectedConversationId &&
          displayMessages.length === 0 && (
            <div
              className="
                flex
                h-full
                flex-col
                items-center
                justify-center
                gap-3
                text-center
                text-gray-500
              "
            >
              <div className="text-4xl">🤖</div>

              <h2 className="text-lg font-semibold text-gray-900">
                AI Chat Assistant
              </h2>

              <p className="text-sm">Start a conversation and ask anything.</p>
            </div>
          )}

        {!selectionRestored && (
          <div className="flex h-full items-center justify-center text-sm text-gray-500">
            Loading...
          </div>
        )}

        {selectedConversationId && loading && (
          <div className="flex h-full items-center justify-center text-sm text-gray-500">
            Loading messages...
          </div>
        )}

        {selectedConversationId && !loading && messagesError && (
          <div
            // 无障碍
            role="alert"
            className="flex h-full items-center justify-center text-sm text-red-600"
          >
            {messagesError}
          </div>
        )}

        {selectedConversationId &&
          !loading &&
          !messagesError &&
          messages.length === 0 && (
            <div className="flex h-full items-center justify-center text-sm text-gray-500">
              No messages in this conversation.
            </div>
          )}

        {displayMessages.length > 0 && (
          <MessageList messages={displayMessages} />
        )}

        <div ref={bottomRef} />
      </main>

      <footer className="border-t border-gray-200 p-4">
        {streamError && (
          <p role="alert" className="mb-3 text-sm text-red-600">
            {streamError}
          </p>
        )}

        <MessageInput
          onSend={handleSend}
          sending={streamingActive}
          useRag={useRag}
          onUseRagChange={onUseRagChange}
        />
      </footer>
    </section>
  );
}
