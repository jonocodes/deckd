# Scroll momentum is computed daemon-side

When the user releases a finger from a jogstrip, the client sends a `jog_end` message with the release velocity. The daemon owns the decay loop — emitting diminishing `REL_WHEEL_HI_RES` deltas until the velocity falls below threshold. The client does not compute or send the decaying sequence itself.

Chosen because all current and future clients (web app, ESP32 hardware client) inherit correct momentum behavior without implementing it themselves. Client-side momentum would require every client to duplicate the decay logic and tune the same friction constants.
