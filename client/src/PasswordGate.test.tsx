import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { PasswordGate } from "./PasswordGate";

describe("PasswordGate", () => {
  afterEach(cleanup);

  it("renders a single password input and connect button", () => {
    render(<PasswordGate onSubmit={() => {}} retry={false} />);
    const input = screen.getByPlaceholderText("Password") as HTMLInputElement;
    expect(input.type).toBe("password");
    expect(screen.getByText("Enter the password to connect.")).not.toBeNull();
  });

  it("submits the trimmed password", () => {
    const onSubmit = vi.fn();
    render(<PasswordGate onSubmit={onSubmit} retry={false} />);
    const input = screen.getByPlaceholderText("Password") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "  hunter2  " } });
    fireEvent.click(screen.getByRole("button", { name: "Connect" }));
    expect(onSubmit).toHaveBeenCalledWith("hunter2");
  });

  it("keeps the submit button disabled while empty", () => {
    render(<PasswordGate onSubmit={() => {}} retry={false} />);
    const button = screen.getByRole("button", { name: "Connect" }) as HTMLButtonElement;
    expect(button.disabled).toBe(true);
  });

  it("shows the retry copy after a rejected attempt", () => {
    render(<PasswordGate onSubmit={() => {}} retry />);
    expect(screen.getByText("Incorrect password. Try again.")).not.toBeNull();
  });
});
