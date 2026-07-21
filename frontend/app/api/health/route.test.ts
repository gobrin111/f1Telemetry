import { describe, expect, it } from "vitest";

import { GET } from "./route";

describe("frontend health route", () => {
  it("reports that the browser service is healthy", async () => {
    const response = GET();

    expect(response.status).toBe(200);
    await expect(response.json()).resolves.toEqual({
      status: "ok",
      service: "frontend",
    });
  });
});
