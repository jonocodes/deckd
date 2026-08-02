import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { IconPicker } from "./IconPicker";

vi.mock("simple-icons", () => ({
  siFirefox: { slug: "firefox", path: "M1 2z", title: "Firefox" },
  siSignal: { slug: "signal", path: "M3 4z", title: "Signal" },
  siGithub: { slug: "github", path: "M5 6z", title: "GitHub" },
  siLinux: { slug: "linux", path: "M7 8z", title: "Linux" },
  siGnome: { slug: "gnome", path: "M9 10z", title: "GNOME" },
  siVscodium: { slug: "vscodium", path: "M11 12z", title: "VSCodium" },
}));

const VIRTUAL_ROWS = 10;
const ROW_SIZE = 56;

vi.mock("@tanstack/react-virtual", () => ({
  useVirtualizer: vi.fn().mockImplementation(
    ({ count }: { count: number }) => {
      const items: { key: string; index: number; start: number; size: number }[] = [];
      const visible = Math.min(count, VIRTUAL_ROWS);
      for (let i = 0; i < visible; i++) {
        items.push({
          key: `row-${i}`,
          index: i,
          start: i * ROW_SIZE,
          size: ROW_SIZE,
        });
      }
      return {
        getVirtualItems: () => items,
        getTotalSize: () => count * ROW_SIZE,
        measure: vi.fn(),
      };
    },
  ),
}));

function openPicker() {
  render(
    <IconPicker
      value={null}
      onChange={vi.fn()}
      open={true}
      onClose={vi.fn()}
    />,
  );
}

describe("IconPicker", () => {
  afterEach(cleanup);

  it("renders Lucide and Brands tabs", () => {
    openPicker();
    expect(screen.getByText("Lucide")).toBeTruthy();
    expect(screen.getByText("Brands")).toBeTruthy();
  });

  it("renders search input and Done button", () => {
    openPicker();
    expect(
      screen.getByPlaceholderText("Search Lucide icons…"),
    ).toBeTruthy();
    expect(screen.getByText("Done")).toBeTruthy();
  });

  it("renders Lucide grid entries", async () => {
    openPicker();
    await waitFor(() => {
      expect(screen.getByLabelText("a-arrow-down")).toBeTruthy();
    });
  });

  it("filters Lucide icons by search term", () => {
    openPicker();
    const input = screen.getByPlaceholderText("Search Lucide icons…");
    fireEvent.change(input, { target: { value: "globe" } });
    expect(screen.getByLabelText("globe")).toBeTruthy();
    expect(screen.queryByLabelText("a-arrow-down")).toBeFalsy();
  });

  it("selects a Lucide icon and shows it in the chip", () => {
    const onChange = vi.fn();
    render(
      <IconPicker
        value={null}
        onChange={onChange}
        open={true}
        onClose={vi.fn()}
      />,
    );
    const input = screen.getByPlaceholderText("Search Lucide icons…");
    fireEvent.change(input, { target: { value: "globe" } });
    fireEvent.click(screen.getByLabelText("globe"));
    expect(onChange).toHaveBeenCalledWith({
      source: "lucide",
      name: "globe",
    });
  });

  it("shows the selected icon chip when value is provided", () => {
    render(
      <IconPicker
        value={{ source: "lucide", name: "globe" }}
        onChange={vi.fn()}
        open={true}
        onClose={vi.fn()}
      />,
    );
    expect(screen.getByText("lucide/globe")).toBeTruthy();
  });

  it("clears selection when remove chip button is clicked", () => {
    const onChange = vi.fn();
    render(
      <IconPicker
        value={{ source: "lucide", name: "globe" }}
        onChange={onChange}
        open={true}
        onClose={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByLabelText("remove icon"));
    expect(onChange).toHaveBeenCalledWith(null);
  });

  it("closes when Done is clicked", () => {
    const onClose = vi.fn();
    render(
      <IconPicker
        value={null}
        onChange={vi.fn()}
        open={true}
        onClose={onClose}
      />,
    );
    fireEvent.click(screen.getByText("Done"));
    expect(onClose).toHaveBeenCalled();
  });

  it("closes when backdrop is clicked", () => {
    const onClose = vi.fn();
    render(
      <IconPicker
        value={null}
        onChange={vi.fn()}
        open={true}
        onClose={onClose}
      />,
    );
    fireEvent.click(screen.getByTestId("icon-picker-backdrop"));
    expect(onClose).toHaveBeenCalled();
  });

  it("renders nothing when open is false", () => {
    render(
      <IconPicker
        value={null}
        onChange={vi.fn()}
        open={false}
        onClose={vi.fn()}
      />,
    );
    expect(screen.queryByText("Lucide")).toBeFalsy();
  });

  it("switches to Brands tab and lazy-loads simple icons", async () => {
    render(
      <IconPicker
        value={null}
        onChange={vi.fn()}
        open={true}
        onClose={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByText("Brands"));

    await waitFor(() => {
      expect(
        screen.getByPlaceholderText("Search brand icons…"),
      ).toBeTruthy();
    });

    await waitFor(() => {
      expect(screen.getByLabelText("firefox")).toBeTruthy();
    });
  });

  it("selects a Simple Icon from the Brands tab", async () => {
    const onChange = vi.fn();
    render(
      <IconPicker
        value={null}
        onChange={onChange}
        open={true}
        onClose={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByText("Brands"));

    await waitFor(() => {
      expect(screen.getByLabelText("firefox")).toBeTruthy();
    });

    fireEvent.click(screen.getByLabelText("firefox"));
    expect(onChange).toHaveBeenCalledWith({
      source: "simple-icons",
      name: "firefox",
    });
  });

  it("sets active tab from value when simple-icons is preselected", () => {
    render(
      <IconPicker
        value={{ source: "simple-icons", name: "firefox" }}
        onChange={vi.fn()}
        open={true}
        onClose={vi.fn()}
      />,
    );
    expect(screen.getByText("simple-icons/firefox")).toBeTruthy();
  });

  it("shows empty state when search matches nothing", () => {
    openPicker();
    const input = screen.getByPlaceholderText("Search Lucide icons…");
    fireEvent.change(input, { target: { value: "zzzzzznomatch" } });
    expect(screen.getByText("No icons match your search.")).toBeTruthy();
  });

  it("shows loading state when Brands tab loads", () => {
    render(
      <IconPicker
        value={null}
        onChange={vi.fn()}
        open={true}
        onClose={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByText("Brands"));
    expect(screen.getByText("Loading brand icons…")).toBeTruthy();
  });
});
