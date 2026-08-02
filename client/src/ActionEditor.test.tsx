import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ActionEditor } from "./ActionEditor";
import type { ActionFields } from "./ActionEditor";

describe("ActionEditor", () => {
  afterEach(cleanup);

  it("renders an 'Add' button when no action is present", () => {
    const onChange = vi.fn();
    render(<ActionEditor action={null} onChange={onChange} />);
    expect(screen.getByText("Action")).toBeTruthy();
    expect(screen.getByText("Add")).toBeTruthy();
  });

  it("fires onChange when clicking Add to create an empty action", () => {
    const onChange = vi.fn();
    render(<ActionEditor action={null} onChange={onChange} />);
    fireEvent.click(screen.getByText("Add"));
    expect(onChange).toHaveBeenCalledWith({});
  });

  it("renders all action fields when action is present", () => {
    const onChange = vi.fn();
    render(<ActionEditor action={{ key: "ctrl+t" }} onChange={onChange} />);
    expect(screen.getByText("Key combo")).toBeTruthy();
    expect(screen.getByText("Shell")).toBeTruthy();
    expect(screen.getByText("D-Bus")).toBeTruthy();
    expect(screen.getByText("URL")).toBeTruthy();
    expect(screen.getByText("Text")).toBeTruthy();
    expect(screen.getByText("Open terminal")).toBeTruthy();
  });

  it("removes the action when the trash button is clicked", () => {
    const onChange = vi.fn();
    render(<ActionEditor action={{ key: "ctrl+t" }} onChange={onChange} />);
    fireEvent.click(screen.getByLabelText("remove action"));
    expect(onChange).toHaveBeenCalledWith(null);
  });

  it("updates key combovalue", () => {
    const onChange = vi.fn();
    render(<ActionEditor action={{}} onChange={onChange} />);
    const input = screen.getByPlaceholderText("e.g. ctrl+t");
    fireEvent.change(input, { target: { value: "ctrl+w" } });
    expect(onChange).toHaveBeenCalledWith({ key: "ctrl+w" });
  });

  it("updates shell value", () => {
    const onChange = vi.fn();
    render(<ActionEditor action={{}} onChange={onChange} />);
    const input = screen.getByPlaceholderText("e.g. firefox");
    fireEvent.change(input, { target: { value: "notify-send hello" } });
    expect(onChange).toHaveBeenCalledWith({ shell: "notify-send hello" });
  });

  it("clears empty string fields", () => {
    const onChange = vi.fn();
    render(<ActionEditor action={{ key: "ctrl+t" }} onChange={onChange} />);
    const input = screen.getByDisplayValue("ctrl+t") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "" } });
    const last = onChange.mock.lastCall?.[0];
    expect(last?.key).toBeUndefined();
  });

  it("toggles terminal checkbox", () => {
    const onChange = vi.fn();
    render(<ActionEditor action={{}} onChange={onChange} />);
    const checkbox = screen.getByRole("checkbox");
    fireEvent.click(checkbox);
    expect(onChange).toHaveBeenCalledWith({ terminal: true });
  });

  it("disables URL and Text fields when terminal is checked", () => {
    const onChange = vi.fn();
    render(<ActionEditor action={{ terminal: true }} onChange={onChange} />);
    const urlInput = screen.getByPlaceholderText("https://...");
    const textInput = screen.getByPlaceholderText("type a string");
    expect((urlInput as HTMLInputElement).disabled).toBe(true);
    expect((textInput as HTMLInputElement).disabled).toBe(true);
  });

  it("handles all four action primitives", () => {
    const onChange = vi.fn();
    const action: ActionFields = {
      key: "ctrl+t",
      shell: "firefox",
      dbus: "org.example.Method",
      url: "https://example.com",
    };
    render(<ActionEditor action={action} onChange={onChange} />);
    expect((screen.getByPlaceholderText("e.g. ctrl+t") as HTMLInputElement).value).toBe("ctrl+t");
    expect((screen.getByPlaceholderText("e.g. firefox") as HTMLInputElement).value).toBe("firefox");
    expect((screen.getByPlaceholderText("https://...") as HTMLInputElement).value).toBe("https://example.com");
  });
});
