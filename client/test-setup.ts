if (typeof ResizeObserver === "undefined") {
  class ResizeObserverMock {
    observe() {}
    unobserve() {}
    disconnect() {}
  }
  globalThis.ResizeObserver = ResizeObserverMock as typeof ResizeObserver;
}

if (typeof DOMRect === "undefined") {
  class DOMRectPolyfill {
    x = 0;
    y = 0;
    width = 0;
    height = 0;
    top = 0;
    right = 0;
    bottom = 0;
    left = 0;
    toJSON() {
      return {};
    }
  }
  globalThis.DOMRect = DOMRectPolyfill as typeof DOMRect;
}
