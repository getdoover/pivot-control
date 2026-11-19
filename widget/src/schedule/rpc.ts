import type { useDooverClient } from "doover-js/react";

type Client = ReturnType<typeof useDooverClient>;

export interface Actor {
  id: string;
  name: string;
  email: string;
}

export type RpcResult = { ok: true; response: Record<string, unknown> } | { ok: false; error: string };

const POLL_MS = 800;
const TIMEOUT_MS = 30_000;

function errorText(status: unknown): string {
  const msg = (status as { message?: unknown } | undefined)?.message;
  if (typeof msg === "string") return msg;
  const inner = (msg as { message?: unknown } | undefined)?.message;
  return typeof inner === "string" ? inner : "The pivot app refused the request";
}

/**
 * Call one of the Pivot Control processor's schedule RPCs, as the site's own
 * buttons do (and the MAIT Dashboard's Pump Control buttons): an RPC message on
 * the device's ui_cmds, then its id under the install's key in the ui_cmds
 * aggregate. Then wait for the processor to mark the message success or error.
 */
export async function callRpc(
  client: Client,
  agentId: string,
  appKey: string,
  method: string,
  request: Record<string, unknown>,
  label: string,
  actor?: Actor,
): Promise<RpcResult> {
  let messageId: string;
  try {
    const data = {
      type: "rpc",
      app_key: appKey,
      method,
      request,
      status: { code: "sent" },
      response: {},
      label,
      ...(actor ? { actor } : {}),
    };
    const message = await client.messages.postMessage(agentId, "ui_cmds", { data: data as never });
    messageId = String(message.id);
    await client.aggregates
      .patchAggregate(agentId, "ui_cmds", { [appKey]: { v2: { [method]: { message_id: messageId } } } } as never)
      .catch(() => undefined); // the marker is for the site's own history; the RPC stands without it
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : String(e) };
  }

  const deadline = Date.now() + TIMEOUT_MS;
  while (Date.now() < deadline) {
    await new Promise((r) => setTimeout(r, POLL_MS));
    try {
      const msg = await client.messages.getMessage(agentId, "ui_cmds", messageId);
      const data = (msg?.data ?? {}) as { status?: { code?: string }; response?: Record<string, unknown> };
      if (data.status?.code === "success") return { ok: true, response: data.response ?? {} };
      if (data.status?.code === "error") return { ok: false, error: errorText(data.status) };
    } catch {
      // keep waiting: a read can fail while the message is still being written
    }
  }
  return { ok: false, error: "No answer from the pivot app yet. Check again in a minute before retrying." };
}
