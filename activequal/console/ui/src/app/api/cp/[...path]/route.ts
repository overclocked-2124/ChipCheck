import { proxyRequest } from "@/lib/server/proxy";
import { readOperatorToken, serverConfig } from "@/lib/server/config";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

type Ctx = { params: Promise<{ path: string[] }> };

async function handle(request: Request, ctx: Ctx): Promise<Response> {
  const { path } = await ctx.params;
  const config = serverConfig();
  return proxyRequest(request, path, { baseUrl: config.baseUrl, getToken: () => readOperatorToken(config.tokenFile) });
}

export const GET = handle;
export const POST = handle;
