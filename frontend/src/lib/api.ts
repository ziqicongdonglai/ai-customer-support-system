import type {
    ChatRequest,
    ChatResponse,
    Conversation,
    ConversationListResponse,
    ConversationUpdateRequest,
    MessageListResponse,
  } from "@/types/chat";
import type {
  CandidateListResponse,
  WorkflowResponse,
  WorkflowResumeRequest,
  WorkflowStartRequest,
} from "@/types/workflow";
  
  const API_BASE_URL =
    process.env.NEXT_PUBLIC_API_URL;

  export class ApiError extends Error {
    constructor(readonly status: number) {
      super(`API Error: ${status}`);
      this.name = "ApiError";
    }
  }
  
  export async function apiClient<T>(
    endpoint: string,
    options?: RequestInit,
  ): Promise<T> {
    const response = await fetch(
      `${API_BASE_URL}${endpoint}`,
      {
        ...options,
        headers: {
          "Content-Type": "application/json",
          ...options?.headers,
        },
      },
    );
  
    if (!response.ok) {
      throw new ApiError(response.status);
    }
  
    return response.json() as Promise<T>;
  }
  
  export async function getConversations(): Promise<
    Conversation[]
  > {
    const data =
      await apiClient<ConversationListResponse>(
        "/conversations",
      );
  
    return data.conversations;
  }
  
  export async function getMessages(
    conversationId: string,
    page = 1,
    pageSize = 20,
  ): Promise<MessageListResponse> {
    const searchParams = new URLSearchParams({
      page: String(page),
      page_size: String(pageSize),
    });
  
    return apiClient<MessageListResponse>(
      `/conversations/${conversationId}/messages?${searchParams.toString()}`,
    );
  }

  export async function updateConversation(
    conversationId: string,
    request: ConversationUpdateRequest,
  ): Promise<Conversation> {
    return apiClient<Conversation>(
      `/conversations/${conversationId}`,
      {
        method: "PATCH",
        body: JSON.stringify(request),
      },
    );
  }

  export async function deleteConversation(
    conversationId: string,
  ): Promise<void> {
    await apiClient<{ message: string }>(
      `/conversations/${conversationId}`,
      {
        method: "DELETE",
      },
    );
  }

  export async function sendChatMessage(
    request: ChatRequest,
  ): Promise<ChatResponse> {
    return apiClient<ChatResponse>(
      "/chat",
      {
        method: "POST",
        body: JSON.stringify(request),
      },
    );
  }

  export function startWorkflow(
    request: WorkflowStartRequest,
  ): Promise<WorkflowResponse> {
    return apiClient<WorkflowResponse>("/workflows", {
      method: "POST",
      body: JSON.stringify(request),
    });
  }

  export function listReturnEligibilityCandidates(): Promise<CandidateListResponse> {
    return apiClient<CandidateListResponse>(
      "/workflows/return-eligibility/candidates",
    );
  }

  export function resumeWorkflow(
    workflowId: string,
    request: WorkflowResumeRequest,
  ): Promise<WorkflowResponse> {
    return apiClient<WorkflowResponse>(
      `/workflows/${encodeURIComponent(workflowId)}/resume`,
      {
        method: "POST",
        body: JSON.stringify(request),
      },
    );
  }
