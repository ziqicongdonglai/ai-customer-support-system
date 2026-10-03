"use client";

import { useEffect, useState } from "react";

import ConversationItem from "@/components/chat/ConversationItem";
import { useConversations } from "@/hooks/useConversations";
import { useChatContext } from "@/context/ChatContext";

export default function Sidebar() {
  const {
    selectedConversationId,
    setSelectedConversationId,
    startNewChat,
    selectionRestored,
    conversationsRefreshKey,
    streamingActive,
    notifyConversationDeleted,
  } = useChatContext();

  const {
    conversations,
    loading,
    error,
    conversationMutation,
    renameError,
    deleteError,
    renameConversation,
    deleteConversation,
    clearRenameError,
    clearDeleteError,
  } = useConversations(conversationsRefreshKey);

  const [editingConversationId, setEditingConversationId] = useState<
    string | null
  >(null);

  const [openMenuConversationId, setOpenMenuConversationId] = useState<
    string | null
  >(null);

  const mutationPending = conversationMutation !== null;

  useEffect(() => {
    if (!openMenuConversationId) {
      return;
    }

    function closeMenu() {
      setOpenMenuConversationId(null);
    }

    function closeMenuOnEscape(event: KeyboardEvent) {
      if (event.key === "Escape") {
        closeMenu();
      }
    }

    document.addEventListener("click", closeMenu);
    document.addEventListener("keydown", closeMenuOnEscape);

    return () => {
      document.removeEventListener("click", closeMenu);
      document.removeEventListener("keydown", closeMenuOnEscape);
    };
  }, [openMenuConversationId]);

  async function handleDelete(conversationId: string, title: string | null) {
    const confirmed = window.confirm(
      `Delete "${title ?? "Untitled conversation"}"? This action cannot be undone.`,
    );

    if (!confirmed) {
      return;
    }

    const deleted = await deleteConversation(conversationId);

    if (!deleted) {
      return;
    }

    setSelectedConversationId((current) =>
      current === conversationId ? null : current,
    );

    notifyConversationDeleted(conversationId);
  }

  useEffect(() => {
    if (!selectionRestored || loading || error || !selectedConversationId) {
      return;
    }

    const selectedConversationExists = conversations.some(
      (conversation) => conversation.id === selectedConversationId,
    );

    if (!selectedConversationExists) {
      setSelectedConversationId(null);
    }
  }, [
    conversations,
    error,
    loading,
    selectedConversationId,
    selectionRestored,
    setSelectedConversationId,
  ]);

  return (
    <aside
      className="
            flex
            flex-col
            w-64
            border-r
            p-4
          "
    >
      <h2
        className="
              text-lg
              font-bold
              "
      >
        Conversations
      </h2>

      <button
        disabled={streamingActive}
        onClick={() => {
          setOpenMenuConversationId(null);
          // selection 可能本来就是 null；显式 reset signal 才能重建并清空旧 Chat session。
          startNewChat();
        }}
        className="
          mt-4
          w-full
          rounded
          border
          px-3
          py-2
          text-sm
          transition
          hover:bg-gray-100
          disabled:cursor-not-allowed
        disabled:bg-gray-100
        "
      >
        + New Chat
      </button>

      {/* 只有第一次没有数据时显示 Loading */}
      {loading && conversations.length === 0 && (
        <div className="mt-4">Loading...</div>
      )}

      {error && (
        <div
          role="alert"
          className="mt-4 rounded bg-red-50 p-2 text-sm text-red-600"
        >
          {error}
        </div>
      )}

      {deleteError && (
        <div
          role="alert"
          className="mt-4 rounded bg-red-50 p-2 text-sm text-red-600"
        >
          {deleteError}
        </div>
      )}

      {!loading && !error && conversations.length === 0 && (
        <div className="mt-4">No conversations</div>
      )}

      <div className="mt-4 flex-1 space-y-2 overflow-y-auto">
        {conversations.map((conversation) => {
          const selected = selectedConversationId === conversation.id;
          const editing = editingConversationId === conversation.id;
          const saving =
            conversationMutation?.type === "rename" &&
            conversationMutation.conversationId === conversation.id;
          const deleting =
            conversationMutation?.type === "delete" &&
            conversationMutation.conversationId === conversation.id;

          return (
            <ConversationItem
              key={conversation.id}
              conversation={conversation}
              selected={selected}
              editing={editing}
              saving={saving}
              deleting={deleting}
              menuOpen={openMenuConversationId === conversation.id}
              mutationPending={mutationPending}
              editDisabled={mutationPending}
              deleteDisabled={streamingActive}
              renameError={editing ? renameError : null}
              onSelect={() => {
                setOpenMenuConversationId(null);
                setSelectedConversationId(conversation.id);
              }}
              onToggleMenu={() => {
                clearDeleteError();
                setOpenMenuConversationId((current) =>
                  current === conversation.id ? null : conversation.id,
                );
              }}
              onCloseMenu={() => setOpenMenuConversationId(null)}
              onStartEditing={() => {
                clearDeleteError();
                setEditingConversationId(conversation.id);
              }}
              onCancelEditing={() => {
                setEditingConversationId(null);
                clearRenameError();
              }}
              onRename={(title) =>
                renameConversation(conversation.id, { title })
              }
              onDelete={() => {
                void handleDelete(conversation.id, conversation.title);
              }}
              onClearRenameError={clearRenameError}
            />
          );
        })}
      </div>
    </aside>
  );
}
