"use client";

import { useLayoutEffect, useRef, useState } from "react";

import type { MouseEvent, SubmitEvent } from "react";

import type { Conversation } from "@/types/chat";

interface ConversationItemProps {
  conversation: Conversation;
  selected: boolean;
  editing: boolean;
  saving: boolean;
  deleting: boolean;
  menuOpen: boolean;
  mutationPending: boolean;
  editDisabled: boolean;
  deleteDisabled: boolean;
  renameError: string | null;
  onSelect: () => void;
  onToggleMenu: () => void;
  onCloseMenu: () => void;
  onStartEditing: () => void;
  onCancelEditing: () => void;
  onRename: (title: string) => Promise<boolean>;
  onDelete: () => void;
  onClearRenameError: () => void;
}

export default function ConversationItem({
  conversation,
  selected,
  editing,
  saving,
  deleting,
  menuOpen,
  mutationPending,
  editDisabled,
  deleteDisabled,
  renameError,
  onSelect,
  onToggleMenu,
  onCloseMenu,
  onStartEditing,
  onCancelEditing,
  onRename,
  onDelete,
  onClearRenameError,
}: ConversationItemProps) {
  const [draftTitle, setDraftTitle] = useState("");
  const [validationError, setValidationError] = useState<string | null>(null);
  const [menuPlacement, setMenuPlacement] = useState<"up" | "down">("down");

  const itemRef = useRef<HTMLDivElement | null>(null);
  const menuRef = useRef<HTMLDivElement | null>(null);

  useLayoutEffect(() => {
    if (!menuOpen || !itemRef.current || !menuRef.current) {
      return;
    }

    const list = itemRef.current.parentElement;

    if (!list) {
      return;
    }

    const itemRect = itemRef.current.getBoundingClientRect();
    const listRect = list.getBoundingClientRect();
    const menuHeight = menuRef.current.offsetHeight;
    const spaceBelow = listRect.bottom - itemRect.bottom;
    const spaceAbove = itemRect.top - listRect.top;

    setMenuPlacement(
      spaceBelow < menuHeight && spaceAbove >= menuHeight ? "up" : "down",
    );
  }, [menuOpen]);

  function startEditing(event: MouseEvent<HTMLButtonElement>) {
    event.stopPropagation();

    if (editDisabled) {
      return;
    }

    setDraftTitle(conversation.title ?? "");
    setValidationError(null);
    onClearRenameError();
    onCloseMenu();
    onStartEditing();
  }

  function toggleMenu(event: MouseEvent<HTMLButtonElement>) {
    event.stopPropagation();

    if (!mutationPending) {
      onToggleMenu();
    }
  }

  function deleteItem(event: MouseEvent<HTMLButtonElement>) {
    event.stopPropagation();

    if (deleteDisabled || mutationPending) {
      return;
    }

    onCloseMenu();
    onDelete();
  }

  function cancelEditing() {
    setDraftTitle("");
    setValidationError(null);
    onClearRenameError();
    onCancelEditing();
  }

  async function saveTitle(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    event.stopPropagation();

    if (saving) {
      return;
    }

    const title = draftTitle.trim();

    if (!title) {
      setValidationError("Title cannot be empty.");
      return;
    }

    if (title.length > 100) {
      setValidationError("Title cannot exceed 100 characters.");
      return;
    }

    setValidationError(null);

    const renamed = await onRename(title);

    if (renamed) {
      setDraftTitle("");
      onCancelEditing();
    }
  }

  return (
    <div
      ref={itemRef}
      onClick={() => {
        onCloseMenu();

        if (!deleting) {
          onSelect();
        }
      }}
      className={`
        group
        relative
        rounded
        border
        p-2
        transition

        ${deleting ? "cursor-wait opacity-70" : "cursor-pointer"}

        ${
          selected
            ? "border-gray-300 bg-gray-200"
            : "hover:bg-gray-100"
        }
      `}
    >
      {editing ? (
        <form
          onSubmit={saveTitle}
          onClick={(event) => event.stopPropagation()}
          className="space-y-2"
        >
          <label
            htmlFor={`conversation-title-${conversation.id}`}
            className="sr-only"
          >
            Conversation title
          </label>
          <input
            id={`conversation-title-${conversation.id}`}
            autoFocus
            value={draftTitle}
            onChange={(event) => {
              setDraftTitle(event.target.value);
              setValidationError(null);
              onClearRenameError();
            }}
            onKeyDown={(event) => {
              if (event.key === "Escape" && !saving) {
                event.preventDefault();
                cancelEditing();
              }
            }}
            disabled={saving}
            aria-invalid={Boolean(validationError)}
            className="w-full rounded border px-2 py-1 text-sm"
          />

          <div className="flex gap-2">
            <button
              type="submit"
              disabled={saving}
              className="rounded border px-2 py-1 text-xs disabled:cursor-not-allowed disabled:opacity-50"
            >
              {saving ? "Saving..." : "Save"}
            </button>
            <button
              type="button"
              onClick={cancelEditing}
              disabled={saving}
              className="rounded border px-2 py-1 text-xs disabled:cursor-not-allowed disabled:opacity-50"
            >
              Cancel
            </button>
          </div>

          {(validationError || renameError) && (
            <p role="alert" className="text-xs text-red-600">
              {validationError ?? renameError}
            </p>
          )}
        </form>
      ) : (
        <div className="flex items-center justify-between gap-2">
          <span className="min-w-0 flex-1 truncate">
            {conversation.title ?? "Untitled conversation"}
          </span>

          {deleting ? (
            <span className="shrink-0 text-xs text-gray-500">
              Deleting...
            </span>
          ) : (
            <div
              className="relative shrink-0"
              onClick={(event) => event.stopPropagation()}
            >
              <button
                type="button"
                onClick={toggleMenu}
                disabled={mutationPending}
                aria-label={`More actions for ${conversation.title ?? "untitled conversation"}`}
                aria-haspopup="menu"
                aria-expanded={menuOpen}
                className="rounded px-2 py-1 text-sm opacity-100 transition hover:bg-gray-200 focus:opacity-100 disabled:cursor-not-allowed disabled:opacity-50 sm:opacity-0 sm:group-hover:opacity-100 sm:group-focus-within:opacity-100"
              >
                ...
              </button>

              {menuOpen && (
                <div
                  ref={menuRef}
                  role="menu"
                  className={`absolute right-0 z-20 w-32 rounded border border-gray-200 bg-white p-1 text-sm shadow-lg ${
                    menuPlacement === "up"
                      ? "bottom-full mb-1"
                      : "top-full mt-1"
                  }`}
                >
                  <button
                    type="button"
                    role="menuitem"
                    onClick={startEditing}
                    disabled={editDisabled}
                    className="w-full rounded px-3 py-2 text-left hover:bg-gray-100 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    Rename
                  </button>
                  <button
                    type="button"
                    role="menuitem"
                    onClick={deleteItem}
                    disabled={deleteDisabled || mutationPending}
                    title={
                      deleteDisabled
                        ? "Wait for this response to finish before deleting."
                        : undefined
                    }
                    className="w-full rounded px-3 py-2 text-left text-red-600 hover:bg-red-50 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    Delete
                  </button>
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
