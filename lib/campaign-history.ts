import type { ChatMessage, ChatSession } from "@/types/chat";
import { mergeCharacterId } from "@/lib/character-id";

export type LoadedCampaignHistory = {
  title: string;
  character_id?: string | null;
  messages: ChatMessage[];
};

/**
 * Apply a fetched campaign history to one session, but only while that session is still
 * unloaded. A session that has since been loaded or modified locally (pending/failed
 * messages, a completed send) is returned untouched, so a late or duplicate history
 * response can never replace newer local state.
 */
export function applyLoadedHistory(
  sessions: ChatSession[],
  sessionId: string,
  history: LoadedCampaignHistory,
  now: number
): ChatSession[] {
  return sessions.map((session) =>
    session.id === sessionId && !session.conversation_loaded
      ? {
          ...session,
          title: history.title || session.title,
          character_id: mergeCharacterId(history.character_id, session.character_id),
          messages: history.messages,
          updated_at: now,
          conversation_loaded: true,
          history_load_failed: false,
        }
      : session
  );
}
