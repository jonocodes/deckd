"""deckd daemon — app-aware touch control surface for Linux."""

__version__ = "0.0.1"

# HTTP header carrying the shared password on the control endpoints (issue
# #16). Defined here — a dependency-free module both the server and the
# thin ``deckctl`` client import — so the two sides can't drift.
PASSWORD_HEADER = "X-Deckd-Password"
