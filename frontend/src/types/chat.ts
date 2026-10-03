export interface SourceReference {
    document_id: string;
    chunk_id: string;
    source: string;
    chunk_index: number;
    score: number;
}

export interface Conversation {
    id: string;
    title: string | null;
    created_at: string;
    updated_at: string;
}

export interface ConversationUpdateRequest {
    title: string;
}

export interface ConversationListResponse {
    conversations: Conversation[];
}

export interface Message {
    id: string;
    conversation_id: string;
    role: "user" | "assistant";
    content: string;
    model:string|null;
    status: string;
    sources: SourceReference[];
    created_at: string;
}

export type ChatMessageRole =
    | "user"
    | "assistant";


export type ChatMessageStatus =
    | "streaming"
    | "completed"
    | "failed";


export interface ChatMessage {

    id:string;

    role:ChatMessageRole;

    content:string;

    status:ChatMessageStatus;

    // UI展示需要，但是临时消息可以为空
    conversation_id?:string;

    model?:string;

    // 来源
    sources: SourceReference[];

    created_at?:string;

    // 标记是否临时消息
    temporary?:boolean;
}

export interface MessageListResponse {

    messages:ChatMessage[];

    pagination:{
        page:number;

        page_size:number;

        total:number;
    }

}

export interface ChatRequest {
    message: string;
    conversation_id?: string;
    use_rag: boolean;
}

export interface ChatResponse {
    conversation_id: string;
    content: string;
    model: string;
    sources: SourceReference[];
}

export type StreamEvent =
    | {
        type: "start";
        conversation_id: string;
    }
    | {
        type: "token";
        content: string;
    }
    | {
        type: "sources";
        sources: SourceReference[];
    }
    | {
        type: "error";
        code: number;
        message: string;
    }
    | {
        type: "workflow_handoff";
        kind: "return_eligibility";
    }
    | {
        type: "end";
    };
