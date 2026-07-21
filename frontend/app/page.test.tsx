import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import Home from "./page";

describe("Home", () => {
  it("introduces the anomaly-detection workflow", () => {
    render(<Home />);

    expect(
      screen.getByRole("heading", {
        level: 1,
        name: /find the laps that deserve a closer look/i,
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/compare timing and telemetry traces in the browser/i),
    ).toBeInTheDocument();
  });
});
