import { streamCampaignEvents } from "@/lib/server/proxy";
import { readOperatorToken, serverConfig } from "@/lib/server/config";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/** Server-sent events for one campaign, relayed from the control plane with the operator token added here. */
export async function GET(request: Request, ctx: { params: Promise<{ id: string }> }): Promise<Response> {
  const { id } = await ctx.params;
  const config = serverConfig();
  return streamCampaignEvents(request, id, { baseUrl: config.baseUrl, getToken: () => readOperatorToken(config.tokenFile) });
}
