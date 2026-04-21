import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import App from "./App";

const routerFutureFlags = {
  v7_relativeSplatPath: true,
  v7_startTransition: true,
};

describe("App routes", () => {
  it("renders the home route", () => {
    render(
      <MemoryRouter future={routerFutureFlags} initialEntries={["/"]}>
        <App />
      </MemoryRouter>,
    );

    expect(screen.getByRole("heading", { name: /league-specific intelligence/i })).toBeInTheDocument();
  });

  it("renders the draft placeholder route", () => {
    render(
      <MemoryRouter future={routerFutureFlags} initialEntries={["/draft"]}>
        <App />
      </MemoryRouter>,
    );

    expect(screen.getByRole("heading", { name: /draft analytics/i })).toBeInTheDocument();
  });

  it("renders the not found route", () => {
    render(
      <MemoryRouter future={routerFutureFlags} initialEntries={["/missing"]}>
        <App />
      </MemoryRouter>,
    );

    expect(screen.getByRole("heading", { name: /page not found/i })).toBeInTheDocument();
  });
});
