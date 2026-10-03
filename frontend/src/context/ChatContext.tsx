"use client";

import {
  createContext,
  useCallback,
  useContext,
  useRef,
  useState,
  useSyncExternalStore,
} from "react";

import type { Dispatch, ReactNode, SetStateAction } from "react";

/* =========================================================
 * Conversation Selection Persistence
 * =========================================================
 *
 * selectedConversationId 需要在 F5 后仍然保留，
 * 因此不能只存在 React useState 中。
 *
 * 当前使用 localStorage 作为持久化数据源：
 *
 * localStorage
 *      ↓
 * useSyncExternalStore
 *      ↓
 * selectedConversationId
 *
 * 修改 selection 时：
 *
 * setSelectedConversationId()
 *      ↓
 * 修改 localStorage
 *      ↓
 * notify listener
 *      ↓
 * React 重新读取 snapshot
 *      ↓
 * UI 更新
 */

const SELECTED_CONVERSATION_STORAGE_KEY = "ai-chat:selected-conversation-id";

/**
 * useSyncExternalStore 需要一种方式：
 *
 * “External Store 改变后，怎么通知 React？”
 *
 * 当前 localStorage 的修改都通过
 * setSelectedConversationId() 完成，
 * 所以使用一个简单 Set 保存 React listener。
 */
const selectedConversationListeners = new Set<() => void>();

/**
 * Browser 中读取当前选择的 Conversation。
 *
 * localStorage 没有值时自然返回 null。
 */
function getSelectedConversationSnapshot(): string | null {
  return window.localStorage.getItem(SELECTED_CONVERSATION_STORAGE_KEY);
}

/**
 * Next.js Server Render 阶段没有 window/localStorage。
 *
 * 因此 Server 端暂时认为没有选中的 Conversation，
 * 等 Browser Hydration 后再读取真实 localStorage。
 */
function getSelectedConversationServerSnapshot(): string | null {
  return null;
}

/**
 * React 订阅 selectedConversationId 的变化。
 *
 * useSyncExternalStore 会把 listener 传进来。
 * 当 Store 改变时，我们执行 listener，
 * React 就会重新读取 getSnapshot()。
 */
function subscribeSelectedConversation(listener: () => void) {
  selectedConversationListeners.add(listener);

  return () => {
    selectedConversationListeners.delete(listener);
  };
}

/**
 * localStorage 修改完成后通知 React：
 * selectedConversationId 可能已经改变。
 */
function notifySelectedConversationChanged() {
  selectedConversationListeners.forEach((listener) => listener());
}

/* =========================================================
 * Hydration State
 * =========================================================
 *
 * Server 上：
 * selectionRestored = false
 *
 * Browser Hydration 后：
 * selectionRestored = true
 *
 * ChatPanel 利用它避免刷新时短暂显示：
 *
 * New Chat
 * ↓
 * Conversation
 *
 * 而是：
 *
 * Loading
 * ↓
 * Conversation
 */

/**
 * Hydration 状态不会持续变化，
 * 因此不需要真正订阅任何 External Store。
 */
function subscribeHydration() {
  return () => {};
}

function getClientHydrationSnapshot() {
  return true;
}

function getServerHydrationSnapshot() {
  return false;
}

/**
 * 封装 Conversation Selection 的持久化细节。
 *
 * ChatProvider 不需要关心：
 * - localStorage
 * - listener
 * - Server Snapshot
 * - Hydration
 *
 * 只拿到：
 *
 * selectedConversationId
 * setSelectedConversationId
 * selectionRestored
 */
function usePersistedConversationSelection() {
  /**
   * localStorage 是 selectedConversationId
   * 的实际持久化数据源。
   */
  const selectedConversationId = useSyncExternalStore(
    subscribeSelectedConversation,
    getSelectedConversationSnapshot,
    getSelectedConversationServerSnapshot,
  );

  /**
   * 判断 Browser 是否已经完成 Hydration，
   * 避免 Restore 期间出现 New Chat 闪烁。
   */
  const selectionRestored = useSyncExternalStore(
    subscribeHydration,
    getClientHydrationSnapshot,
    getServerHydrationSnapshot,
  );

  /**
   * 保持和 React useState setter 相同的调用方式。
   *
   * 支持：
   *
   * setSelectedConversationId("id")
   *
   * setSelectedConversationId(null)
   *
   * setSelectedConversationId(current => ...)
   */
  const setSelectedConversationId = useCallback<
    Dispatch<SetStateAction<string | null>>
  >((next) => {
    /**
     * 当前值直接从 localStorage 读取。
     */
    const current = getSelectedConversationSnapshot();

    /**
     * React setter 支持：
     *
     * 1. 直接传新值
     * 2. 传函数，根据 current 计算新值
     */
    const nextConversationId =
      typeof next === "function" ? next(current) : next;

    if (nextConversationId) {
      /**
       * 选中了某个 Conversation：
       * 保存 ID。
       */
      window.localStorage.setItem(
        SELECTED_CONVERSATION_STORAGE_KEY,
        nextConversationId,
      );
    } else {
      /**
       * New Chat / 当前 Conversation 被删除：
       * 清除持久化 selection。
       */
      window.localStorage.removeItem(SELECTED_CONVERSATION_STORAGE_KEY);
    }

    /**
     * localStorage 本身不会主动通知当前
     * useSyncExternalStore 实例。
     *
     * 所以写完以后主动通知 React
     * 重新读取 snapshot。
     */
    notifySelectedConversationChanged();
  }, []);

  return {
    selectedConversationId,
    setSelectedConversationId,
    selectionRestored,
  };
}

/* =========================================================
 * Chat Context
 * ========================================================= */

interface ChatContextType {
  /**
   * 当前正在查看的 Conversation。
   *
   * null = New Chat
   */
  selectedConversationId: string | null;

  /**
   * 修改当前 Conversation。
   *
   * 同时负责把 selection 同步到 localStorage。
   */
  setSelectedConversationId: Dispatch<SetStateAction<string | null>>;

  newChatResetKey: number;

  startNewChat: () => void;

  /**
   * Browser 是否已经完成 selection restore。
   */
  selectionRestored: boolean;

  /**
   * Sidebar Conversation List 的刷新信号。
   */
  conversationsRefreshKey: number;

  refreshConversations: () => void;

  /**
   * 当前是否处于完整发送生命周期：
   *
   * Streaming
   * +
   * Persistent History hand-off
   */
  streamingActive: boolean;

  setStreamingActive: Dispatch<SetStateAction<boolean>>;

  /**
   * Conversation 删除通知。
   *
   * Sidebar 删除 Conversation 后，
   * ChatPanel 可以清理对应 Temporary State。
   */
  notifyConversationDeleted: (conversationId: string) => void;

  subscribeConversationDeleted: (
    listener: (conversationId: string) => void,
  ) => () => void;
}

const ChatContext = createContext<ChatContextType | null>(null);

export function ChatProvider({ children }: { children: ReactNode }) {
  /**
   * Persistent Conversation Selection。
   *
   * 持久化实现已经封装在 Hook 中，
   * Provider 只关心最终状态。
   */
  const {
    selectedConversationId,
    setSelectedConversationId,
    selectionRestored,
  } = usePersistedConversationSelection();

  /**
   * Conversation List Refresh Signal。
   *
   * 当前 Sidebar 监听 refreshKey，
   * key 变化后重新请求 Conversation List。
   *
   * 这是现有架构，
   * Conversation State Ownership 重构留作后续。
   */
  const [conversationsRefreshKey, setConversationsRefreshKey] = useState(0);

  /**
   * 当前是否有一轮发送流程正在进行。
   */
  const [streamingActive, setStreamingActive] = useState(false);

  // 该计数器不是 Conversation identity，也不进入持久化；它只是显式的前端
  // Chat-session reset signal。失败的首条消息本来就从 null selection 开始，
  // 因此仅再次设置 selectedConversationId = null 无法表达“重新开始一次会话”。
  const [newChatResetKey, setNewChatResetKey] = useState(0);

  const startNewChat = useCallback(() => {
    setSelectedConversationId(null);
    setNewChatResetKey((current) => current + 1);
  }, [setSelectedConversationId]);

  /**
   * Conversation Deleted Event Listeners。
   *
   * 当前主要用于：
   *
   * Sidebar
   * → notify delete
   * → ChatPanel
   * → clear temporary state
   */
  const conversationDeletedListenersRef = useRef(
    new Set<(conversationId: string) => void>(),
  );

  function refreshConversations() {
    setConversationsRefreshKey((current) => current + 1);
  }

  const notifyConversationDeleted = useCallback((conversationId: string) => {
    conversationDeletedListenersRef.current.forEach((listener) => {
      listener(conversationId);
    });
  }, []);

  const subscribeConversationDeleted = useCallback(
    (listener: (conversationId: string) => void) => {
      const listeners = conversationDeletedListenersRef.current;

      listeners.add(listener);

      return () => {
        listeners.delete(listener);
      };
    },
    [],
  );

  return (
    <ChatContext.Provider
      value={{
        selectedConversationId,
        setSelectedConversationId,
        newChatResetKey,
        startNewChat,
        selectionRestored,

        conversationsRefreshKey,
        refreshConversations,

        streamingActive,
        setStreamingActive,

        notifyConversationDeleted,
        subscribeConversationDeleted,
      }}
    >
      {children}
    </ChatContext.Provider>
  );
}

export function useChatContext() {
  const context = useContext(ChatContext);

  if (!context) {
    throw new Error("useChatContext must be used within ChatProvider");
  }

  return context;
}
