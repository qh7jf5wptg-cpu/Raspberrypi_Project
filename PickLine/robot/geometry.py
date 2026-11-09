"""World layout for the two tending robots and the shared outfeed conveyor."""

# One six-axis robot per fill station, both placing onto one outfeed belt.
ROBOT_A_BASE = (460.0, 135.0, 0.0)
ROBOT_B_BASE = (430.0, 205.0, 0.0)

PICK_A = (460.0, 100.0, 30.0)      # full container on fill station A
PICK_B = (400.0, 240.0, 30.0)      # full container on fill station B

OUTFEED_Y = 170.0
OUTFEED_START_X = 420.0
OUTFEED_DROP = (430.0, OUTFEED_Y, 30.0)   # single shared place point
OUTFEED_EXIT_X = 650.0
OUTFEED_PITCH = 120.0             # minimum spacing between placed containers
OUTFEED_SPEED = 60.0              # mm/s (slower so containers stay visible)

GRIP_TOL = 18.0                   # mm, "close enough" to a pick/place point
