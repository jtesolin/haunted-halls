export interface ChatRequest {
  message: string;
  campaign_id?: string | null;
  character_id?: string | null;
}

export interface ChatResponse {
  reply: string;
  campaign_id: string;
  turn_id: string;
}

export type CreateCampaignRequest = Record<string, never>;

export type ChatRole = "user" | "assistant";

export interface ChatMessage {
  id: string;
  role: ChatRole;
  text: string;
  is_loading?: boolean;
  loading_text?: string;
}

export interface ChatSession {
  id: string;
  title: string;
  campaign_id?: string;
  last_message?: string | null;
  updated_at: number;
  conversation_loaded: boolean;
  messages: ChatMessage[];
  is_optimistic?: boolean;
}

export interface CampaignSummary {
  campaign_id: string;
  name: string;
  last_message: string | null;
}

export interface CampaignMessageEntry {
  turn_id: string;
  role: ChatRole;
  content: string;
  created_at: string;
}

export interface CampaignDetailsResponse {
  campaign_id: string;
  name: string;
  description: string | null;
  messages: CampaignMessageEntry[];
  truncated: boolean;
}

export type CreateCampaignResponse = CampaignDetailsResponse;
