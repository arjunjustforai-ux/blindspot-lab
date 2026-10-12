import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, api, errorMessage, mediaUrl } from "./api";

afterEach(() => vi.unstubAllGlobals());

describe("api client", () => {
  it("surfaces the API's structured error", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ error: { code: "duplicate_source", message: "Already uploaded" } }), { status: 409 })));
    const err = (await api("/api/x").catch((e: unknown) => e)) as ApiError;
    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(409);
    expect(err.code).toBe("duplicate_source");
    expect(errorMessage(err)).toBe("Already uploaded");
  });

  it("reports an unreachable backend clearly", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => Promise.reject(new TypeError("fetch failed"))));
    const err = (await api("/api/x").catch((e: unknown) => e)) as ApiError;
    expect(err.code).toBe("network_error");
  });

  it("returns undefined for 204 and parses JSON bodies", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(null, { status: 204 })));
    expect(await api("/api/x", { method: "DELETE" })).toBeUndefined();
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ ok: 1 }), { status: 200 })));
    expect(await api<{ ok: number }>("/api/x")).toEqual({ ok: 1 });
  });

  it("builds absolute media URLs", () => {
    expect(mediaUrl("/api/media/a?sig=1")).toMatch(/^http.*\/api\/media\/a\?sig=1$/);
    expect(mediaUrl("https://cdn.example/x")).toBe("https://cdn.example/x");
    expect(mediaUrl(null)).toBeUndefined();
  });
});
