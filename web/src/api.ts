import type { AskResponse } from "./types";

/** Calls POST /api/ask. Throws with a readable message on a non-2xx response (e.g. the
 * 503 the API returns when ANSWER_BACKEND=anthropic is set with no real API key). */
export async function ask(question: string, groups: string[] = []): Promise<AskResponse> {
  const res = await fetch("/api/ask", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question, groups }),
  });

  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(body?.detail ?? `Request failed with status ${res.status}`);
  }

  return res.json() as Promise<AskResponse>;
}
