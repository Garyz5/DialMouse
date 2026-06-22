"""DialMouse OSC address constants.

Single source of truth for the wire protocol so the receiver and any sender
(the loopback test, the Companion guide) agree. Mirrors section 6 of the spec.
Only the addresses wired in Step 3 are marked ACTIVE; the rest are reserved for
later steps and currently logged-and-ignored.
"""

from __future__ import annotations

# Pointer / scroll / buttons (ACTIVE in Step 3)
MOVE_X = "/dialmouse/move/x"
MOVE_Y = "/dialmouse/move/y"
SCROLL = "/dialmouse/scroll"
BUTTON_LEFT = "/dialmouse/button/left"
BUTTON_RIGHT = "/dialmouse/button/right"
BUTTON_MIDDLE = "/dialmouse/button/middle"
CLICK_LEFT = "/dialmouse/click/left"
CLICK_RIGHT = "/dialmouse/click/right"
CLICK_MIDDLE = "/dialmouse/click/middle"

# Sensitivity / scroll / control (ACTIVE in Step 3)
SENSITIVITY = "/dialmouse/sensitivity"
SCROLLSPEED = "/dialmouse/scrollspeed"
CONTROL_ENABLED = "/dialmouse/control/enabled"
CONTROL_TOGGLE = "/dialmouse/control/toggle"

# Confinement / Mini Mon (ACTIVE in Step 3)
CONFINE_MINIMON = "/dialmouse/confine/minimon"
CONFINE_OFF = "/dialmouse/confine/off"
CONFINE_TOGGLE = "/dialmouse/confine/toggle"
CURSOR_PARK = "/dialmouse/cursor/park"

# Reserved for later steps (keyboard = Step 4, display = Step 5)
KEY_TAP = "/dialmouse/key/tap"
DISPLAY_IDENTIFY = "/dialmouse/display/identify"

# Raw-UDP text fallback grammar (newline-delimited), for Companion Generic UDP:
#   dx <int>     dy <int>     scroll <int>
#   left|right|middle  down|up
#   click left|right|middle
#   confine on|off|toggle     park
#   pause|resume|toggle
# Parsed by server._parse_text_line().
