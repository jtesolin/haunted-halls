export interface ChatRequest {
  message: string;
  campaign_id?: string;
  character_id?: string;
}

export interface ChatResponse {
  reply: string;
  campaign_id: string;
  turn_id: string;
}

export type ChatRole = "user" | "assistant";

export interface ChatMessage {
  id: string;
  role: ChatRole;
  text: string;
}

export interface ChatSession {
  id: string;
  title: string;
  messages: ChatMessage[];
}
