import type { APIRequestContext } from "@playwright/test";

type CampaignSummary = {
  campaign_id: string;
};

/**
 * Deletes all campaigns for the authenticated E2E identity through the real BFF API
 * (not by touching PostgreSQL directly), so tests can start from a clean slate
 * without depending on execution order.
 */
export async function resetE2ECampaigns(request: APIRequestContext, baseURL: string): Promise<void> {
  const response = await request.get(`${baseURL}/api/campaigns`);
  if (!response.ok()) {
    throw new Error(
      `resetE2ECampaigns: failed to list campaigns from ${baseURL}/api/campaigns ` +
        `(status ${response.status()} ${response.statusText()}): ${await response.text()}`,
    );
  }

  const campaigns = (await response.json()) as CampaignSummary[];
  for (const campaign of campaigns) {
    const deleteResponse = await request.delete(`${baseURL}/api/campaign/${encodeURIComponent(campaign.campaign_id)}`);
    // A 404 is an explicitly benign outcome: the campaign was already gone
    // (e.g. removed by a concurrent test or a prior partially-applied cleanup).
    // Any other non-success status means we cannot guarantee a clean starting
    // state, so fail fast rather than continuing with unknown server state.
    if (!deleteResponse.ok() && deleteResponse.status() !== 404) {
      throw new Error(
        `resetE2ECampaigns: failed to delete campaign ${campaign.campaign_id} ` +
          `(status ${deleteResponse.status()} ${deleteResponse.statusText()}): ${await deleteResponse.text()}`,
      );
    }
  }
}
