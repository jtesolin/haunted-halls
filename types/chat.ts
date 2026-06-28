export interface ChatRequest {
  message: string;
  campaign_id?: string | null;
  character_id?: string | null;
  player_id: string;
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
  campaign_id?: string;
  player_id?: string;
  last_message?: string | null;
  messages: ChatMessage[];
}

export interface CampaignSummary {
  campaign_id: string;
  title: string;
  last_message: string | null;
}

export interface CampaignMessageEntry {
  turn_id: string;
  player_message: string;
  ai_reply: string;
  created_at: string;
}

export interface CampaignDetailsResponse {
  campaign_id: string;
  name: string;
  description: string | null;
  player_id: string | null;
  messages: CampaignMessageEntry[];
  truncated: boolean;
}
