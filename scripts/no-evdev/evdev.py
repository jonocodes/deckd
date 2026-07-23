raise ImportError(
    "evdev shadowed for tests: forces LoggingKeySink / LoggingScrollSink so "
    "daemon keystrokes are logged rather than injected into the host desktop."
)