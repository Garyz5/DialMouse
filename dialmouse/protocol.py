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
CLICK_DOUBLE = "/dialmouse/click/double"          # ACTIVE in Step 4
DRAGLOCK_TOGGLE = "/dialmouse/draglock/toggle"    # ACTIVE in Step 4

# Sensitivity / scroll / control (ACTIVE in Step 3; presets/modes in Step 4)
SENSITIVITY = "/dialmouse/sensitivity"
SENSITIVITY_PRESET = "/dialmouse/sensitivity/preset"  # ACTIVE in Step 4
SCROLLSPEED = "/dialmouse/scrollspeed"
CONTROL_ENABLED = "/dialmouse/control/enabled"
CONTROL_TOGGLE = "/dialmouse/control/toggle"
MODE_PRECISION = "/dialmouse/mode/precision"      # ACTIVE in Step 4
MODE_TURBO = "/dialmouse/mode/turbo"              # ACTIVE in Step 4

# Confinement / Mini Mon (ACTIVE in Step 3)
CONFINE_MINIMON = "/dialmouse/confine/minimon"
CONFINE_OFF = "/dialmouse/confine/off"
CONFINE_TOGGLE = "/dialmouse/confine/toggle"
CURSOR_PARK = "/dialmouse/cursor/park"

# Keyboard — DialMouse owns shift/layer state (ACTIVE in Step 4)
KEY_TAP = "/dialmouse/key/tap"            # <name>  e.g. a, 1, enter, ctrl+c
KEY_DOWN = "/dialmouse/key/down"          # <name>  press and hold
KEY_UP = "/dialmouse/key/up"             # <name>  release
KEY_TYPE = "/dialmouse/key/type"          # <string> literal snippet text
KEY_MOD_TOGGLE = "/dialmouse/key/mod/toggle"  # <shift|ctrl|alt|win>
KEY_SNIPPET = "/dialmouse/key/snippet"    # <int> config-defined snippet, 1-based

# Reserved for later steps (display = Step 5)
DISPLAY_IDENTIFY = "/dialmouse/display/identify"

# Raw-UDP text fallback grammar (newline-delimited), for Companion Generic UDP:
#   dx <int>     dy <int>     scroll <int>
#   left|right|middle  down|up
#   click left|right|middle    dblclick    draglock
#   confine on|off|toggle     park
#   pause|resume|toggle
#   sensitivity <int>    scrollspeed <int>    preset <int>
#   precision on|off     turbo on|off
#   key <name>    kdown <name>    kup <name>    mod <name>    snippet <int>
#   type <text...>   (rest of line is typed literally)
# Parsed by server._parse_text_line().
