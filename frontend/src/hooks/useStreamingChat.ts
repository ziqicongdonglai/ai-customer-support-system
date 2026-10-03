"use client";

import { useState } from "react";

import { streamChat } from "@/lib/stream";

import type { ChatMessage, ChatRequest } from "@/types/chat";

interface StartStreamingOptions {
    onConversationStarted?: (
        conversationId: string
    ) => void;
    onWorkflowHandoff?: (
        // handoff 绑定已由 SSE start 确认的 Conversation，避免跨 Conversation 泄漏。
        kind: "return_eligibility",
        conversationId: string,
    ) => void;
}

function getUserFriendlyStreamError(
    code: number,
): string {
    if (code === 1001) {
        return "The AI service is temporarily unavailable. Please try again later.";
    }

    if (code === 1002) {
        return "The chat service is temporarily unavailable. Please try again later.";
    }

    return "Something went wrong while generating the response. Please try again.";
}

class StreamingEventError extends Error {
    readonly code: number;
    readonly backendMessage: string;

    constructor(code: number, backendMessage: string) {
        super(getUserFriendlyStreamError(code));
        this.name = "StreamingEventError";
        this.code = code;
        this.backendMessage = backendMessage;
    }
}

export function useStreamingChat() {

    const [streamingMessage, 
        setStreamingMessage,
    ] = useState<ChatMessage | null>(null);

    const [streaming, setStreaming] = useState(false);

    const [error, setError] = useState<string | null>(null);

    async function startStreaming(params: ChatRequest, options?: StartStreamingOptions): Promise<string | null> {
        setStreaming(true);

        setError(null);
        
        const messageId = crypto.randomUUID();

        let conversationId: string | null = null;

        let streamFailed = false;

        setStreamingMessage({
            id: messageId,
            role: "assistant",
            content: "",
            status: "streaming",
            sources: [],
            temporary: true,
            conversation_id: params.conversation_id,
        });

        try {
            await streamChat(
                params,

                (event) => {
                    if (event.type === "start"){

                        conversationId = event.conversation_id ?? null;
                    
                    
                        setStreamingMessage(previous =>
                            previous
                            ?
                            {
                                ...previous,
                                conversation_id: conversationId ?? undefined
                            }
                            :
                            previous
                        );

                        if (conversationId) {
                            options?.onConversationStarted?.(
                                conversationId
                            );
                        }
                    
                    }

                    if (event.type === "sources") {
                        setStreamingMessage(previous => {
                            if (!previous) {
                                return previous;
                            }

                            return {
                                ...previous,
                                sources: event.sources,
                            }
                        });
                    }

                    if (event.type === "token") {
                        // 函数式 setState
                        setStreamingMessage(previous => {

                            if (!previous) {
                                return previous;
                            }

                            return {
                                ...previous,

                                content:
                                    previous.content
                                    +
                                    (event.content ?? ""),
                            }
                        });
                    }

                    if (event.type === "error") {
                        streamFailed = true;

                        console.error(
                            "Backend streaming error",
                            {
                                code: event.code,
                                message: event.message,
                            },
                        );

                        throw new StreamingEventError(
                            event.code,
                            event.message,
                        );
                    }

                    if (event.type === "workflow_handoff") {
                        // structured SSE 是一次应用控制信号，不从 LLM 文本推断 UI 动作；
                        // start 必须先建立 Conversation identity，handoff 才可被消费。
                        if (!conversationId) {
                            throw new Error("Workflow handoff received before conversation start");
                        }
                        options?.onWorkflowHandoff?.(event.kind, conversationId);
                    }

                    if (event.type === "end" && !streamFailed) {
                        setStreamingMessage(
                            previous => previous ? {
                                ...previous,
                                status: "completed",
                            }: previous
                        );
                    }
                }
            );

            return conversationId;
        } catch(error) {

            setStreamingMessage(
                previous => previous ? {
                    ...previous,
                    status:"failed",
                }: previous
            );
        
            const message =
                error instanceof Error
                ? error.message
                : "Unknown error";
        
            setError(message);
        
            throw error;
        } finally {
            setStreaming(false);
        }
    }

    // 普通失败路径不会调用 cleanup，因此失败消息和 error 会保留供用户查看或重试；
    // 显式清理 Chat session 时两者必须一起退出，不能让 error 脱离临时消息继续显示。
    function clearStreamingMessage() {
        setStreamingMessage(null);
        setError(null);
    }

    return {
        startStreaming,
        streamingMessage,
        streaming,
        error,
        clearStreamingMessage,
    };
}
