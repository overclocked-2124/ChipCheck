import { readFile } from "node:fs/promises";

export type ServerConfig = { baseUrl: string; tokenFile: string | undefined };

export function serverConfig(env: Record<string, string | undefined> = process.env): ServerConfig {
  return { baseUrl: (env.ACTIVEQUAL_URL || "http://127.0.0.1:8001").replace(/\/+$/, ""), tokenFile: env.ACTIVEQUAL_OPERATOR_TOKEN_FILE };
}

export class TokenError extends Error {}

/** Read the operator token from disk on every call (a rotated token needs no Console restart). Error text is UI-safe. */
export async function readOperatorToken(tokenFile: string | undefined): Promise<string> {
  if (!tokenFile) throw new TokenError("The Console server has no operator token configured: set ACTIVEQUAL_OPERATOR_TOKEN_FILE and restart it.");
  let text: string;
  try { text = await readFile(tokenFile, "utf-8"); }
  catch { throw new TokenError("The Console server cannot read the operator token file named by ACTIVEQUAL_OPERATOR_TOKEN_FILE."); }
  const token = text.trim();
  if (!token) throw new TokenError("The operator token file is empty.");
  return token;
}
