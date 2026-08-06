// Pure JSON builders kept separate from GNOME Shell so the wire contract can
// be tested without a compositor.

export function activeWindowPayload(window, callOrNull) {
  if (!window) {
    return {
      app_id: null,
      wm_class: null,
      title: null,
      pid: null,
    };
  }

  return {
    app_id: callOrNull(window, "get_gtk_application_id"),
    wm_class: callOrNull(window, "get_wm_class"),
    title: callOrNull(window, "get_title"),
    pid: callOrNull(window, "get_pid"),
  };
}

export function windowPayload(metaWindow, callOrNull, sandboxedAppId) {
  const id = callOrNull(metaWindow, "get_id");
  if (id === null) return null;

  const workspace = callOrNull(metaWindow, "get_workspace");
  const appId = sandboxedAppId(metaWindow);
  const app = metaWindow.get_app ? metaWindow.get_app() : null;
  return {
    window_id: String(id),
    wm_class: callOrNull(metaWindow, "get_wm_class"),
    gtk_application_id: callOrNull(metaWindow, "get_gtk_application_id"),
    sandboxed_app_id: appId,
    app_name: app && typeof app.get_name === "function" ? app.get_name() : null,
    title: callOrNull(metaWindow, "get_title"),
    workspace: workspace !== null && typeof workspace.index === "number" ? workspace.index : null,
    minimized: callOrNull(metaWindow, "minimized") === true,
  };
}
