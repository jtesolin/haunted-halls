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

export type ChatDeliveryState = "pending" | "failed";
export type ChatFailureCategory = "rejected" | "ambiguous";

export interface ChatFailure {
  message: string;
  title?: string;
  retryable: boolean;
  category: ChatFailureCategory;
  code?: string;
  retry_at?: string;
}

export interface ChatMessage {
  id: string;
  role: ChatRole;
  text: string;
  request_id?: string;
  is_loading?: boolean;
  loading_text?: string;
  delivery_state?: ChatDeliveryState;
  failure?: ChatFailure;
}

export interface ChatSession {
  id: string;
  title: string;
  campaign_id?: string;
  last_message?: string | null;
  updated_at: number;
  character_id?: string | null;
  conversation_loaded: boolean;
  history_load_failed?: boolean;
  messages: ChatMessage[];
  is_optimistic?: boolean;
}

export interface CampaignSummary {
  campaign_id: string;
  name: string;
  last_message: string | null;
  character_id?: string | null;
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
  character_id?: string | null;
}

export type CreateCampaignResponse = CampaignDetailsResponse;

export interface CharacterInventoryItem {
  id: string;
  name: string;
  description: string;
  quantity: number;
}

export interface CharacterAbility {
  ability_id: string;
  display_name: string;
  description: string;
  available: boolean;
  availability_reason?: string | null;
}

export interface CharacterDetailResponse {
  character_id: string;
  name: string;
  inventory: CharacterInventoryItem[];
  abilities: CharacterAbility[];
}
