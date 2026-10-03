import type { ChatMessage } from "@/types/chat";
import MarkdownRenderer from "@/components/markdown/MarkdownRenderer";
interface MessageListProps {
  messages: ChatMessage[];
}

function getMessageContent(message: ChatMessage): string {
  if (message.content.trim()) {
    return message.content;
  }

  if (message.status === "completed") {
    return "Empty assistant response.";
  }

  if (message.status === "streaming" && !message.content) {
    return "Thinking...";
  }

  return `Response unavailable. Status: ${message.status}`;
}

function getSourceName(source: string): string {
  return source.split(/[\\/]/).pop() || source;
}

export default function MessageList({ messages }: MessageListProps) {
  return (
    <div className="flex flex-col gap-4">
      {messages.map((message) => {
        const isUser = message.role === "user";

        return (
          <div
            key={message.id}
            className={`flex ${isUser ? "justify-end" : "justify-start"}`}
          >
            <div
              // 限制最大宽度为 75%
              className={`max-w-[75%] rounded-2xl px-4 py-3 ${
                isUser ? "bg-gray-900 text-white" : "bg-gray-100 text-gray-900"
              }`}
            >
              {isUser ? (
                <p className="whitespace-pre-wrap text-sm leading-6">
                  {getMessageContent(message)}
                </p>
              ) : (
                <>
                  <MarkdownRenderer>
                    {getMessageContent(message)}
                  </MarkdownRenderer>

                  {message.sources.length > 0 && (
                    <div className="mt-3 border-t border-gray-200 pt-2">
                      <p className="mb-1 text-xs font-medium text-gray-500">
                        Sources
                      </p>

                      <ul className="space-y-1 text-xs text-gray-500">
                        {message.sources.map((source) => (
                          <li key={source.chunk_id}>
                            {getSourceName(source.source)}
                            {" · "}
                            Chunk {source.chunk_index + 1}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                </>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
