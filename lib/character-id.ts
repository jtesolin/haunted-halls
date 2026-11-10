/**
 * Merge an incoming campaign `character_id` into the one already held for a session.
 *
 * The engine reports `null` when a campaign has no character row, so an explicit `null`
 * must clear a previously stored id. Only an absent (`undefined`) field keeps the old value.
 */
export function mergeCharacterId(
  incoming: string | null | undefined,
  existing: string | null | undefined
): string | null | undefined {
  return incoming === undefined ? existing : incoming;
}
