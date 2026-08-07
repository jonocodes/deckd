// Pure JSON builders and compositor-accessor resolution kept separate from
// GNOME Shell so the wire contract can be tested without a compositor.

// Resolve the open-window actor list from the Shell ``global``.
// ``get_window_actors()`` lives on the Shell ``global`` (``Shell.Global``),
// NOT on ``global.display`` (``Meta.Display`` has no such method). Prefer it;
// fall back to the display accessor only if a future Shell moves it.
//
// If neither accessor exists we return ``[]`` — the daemon polls at the focus
// cadence (~100ms) and a thrown method every tick is worse than a degraded
// list — but we call ``onMissing`` so the caller can log it (#128). A silent
// ``[]`` is exactly what hid the stage-2 receiver bug (#126): "no windows
// open" and "the enumeration API moved" looked identical to the user.
export function resolveWindowActors(globalObj, onMissing) {
  if (typeof globalObj.get_window_actors === "function") {
    return globalObj.get_window_actors();
  }
  if (globalObj.display && typeof globalObj.display.get_window_actors === "function") {
    return globalObj.display.get_window_actors();
  }
  onMissing();
  return [];
}

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
