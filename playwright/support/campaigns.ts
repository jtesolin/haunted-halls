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
    return;
  }

  const campaigns = (await response.json()) as CampaignSummary[];
  for (const campaign of campaigns) {
    await request.delete(`${baseURL}/api/campaign/${encodeURIComponent(campaign.campaign_id)}`);
  }
}
