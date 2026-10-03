"use client";

import { SyntheticEvent, KeyboardEvent, useState, useRef } from "react";

interface MessageInputProps {
  disabled?: boolean;
  sending?: boolean;
  onSend: (message: string) => Promise<boolean>;
  useRag: boolean;
  onUseRagChange: (enabled: boolean) => void;
}

export default function MessageInput({
  disabled = false,
  sending = false,
  onSend,
  useRag,
  onUseRagChange,
}: MessageInputProps) {
  const [message, setMessage] = useState("");

  const textareaRef = useRef<HTMLTextAreaElement | null>(null);

  const trimmedMessage = message.trim();

  const cannotSend = !trimmedMessage || disabled || sending;

  async function handleSubmit(
    event: SyntheticEvent<HTMLFormElement, SubmitEvent>,
  ) {
    event.preventDefault();

    if (cannotSend) {
      return;
    }

    const currentMessage = trimmedMessage;

    // 立即清空输入框
    setMessage("");

    requestAnimationFrame(() => {
      if (textareaRef.current) {
        textareaRef.current.style.height = "auto";
      }
    });

    const success = await onSend(trimmedMessage);

    if (!success) {
      setMessage(currentMessage);
    }
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();

      if (!cannotSend) {
        event.currentTarget.form?.requestSubmit();
      }
    }
  }

  function adjustTextareaHeight() {
    const textarea = textareaRef.current;

    if (!textarea) {
      return;
    }

    textarea.style.height = "auto";

    textarea.style.height = `${Math.min(textarea.scrollHeight, 160)}px`;
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-3">
      <label
        className={`
          inline-flex w-fit items-center gap-2 text-sm
          ${
            disabled || sending
              ? "cursor-not-allowed text-gray-400"
              : "cursor-pointer text-gray-600"
          }
        `}
      >
        <input
          type="checkbox"
          checked={useRag}
          onChange={(event) => onUseRagChange(event.target.checked)}
          disabled={disabled || sending}
          className="h-4 w-4"
        />

        <span>Use knowledge base</span>
      </label>
      <div className="flex items-end gap-3">
        <textarea
          ref={textareaRef}
          value={message}
          onChange={(event) => {
            setMessage(event.target.value);

            requestAnimationFrame(adjustTextareaHeight);
          }}
          onKeyDown={handleKeyDown}
          placeholder="Type your message..."
          disabled={disabled || sending}
          rows={1}
          className="
            max-h-40
            min-h-11
            flex-1
            resize-none
            overflow-y-auto
            rounded-xl
            border
            border-gray-300
            px-4
            py-2.5
            text-sm
            leading-5
            text-gray-900
            outline-none
            transition
            placeholder:text-gray-400
            focus:border-gray-500
            disabled:cursor-not-allowed
            disabled:bg-gray-100
          "
        />

        <button
          type="submit"
          disabled={cannotSend}
          className="
            h-11
            min-w-20
            rounded-xl
            bg-gray-900
            px-5
            text-sm
            font-medium
            text-white
            transition
            hover:bg-gray-700
            disabled:cursor-not-allowed
            disabled:bg-gray-300
          "
        >
          {sending ? "Sending..." : "Send"}
        </button>
      </div>
    </form>
  );
}
