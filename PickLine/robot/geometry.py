"""World layout for the two tending robots, their outfeeds, and the lifts.

Each fill station has its own downstream line: a robot places full containers
onto its own outfeed conveyor, which feeds a vertical lift. The lift raises the
container to a palletizer that stacks containers and releases a finished
pallet once the target stack size is reached (station A = 4, station B = 2).
"""

# One six-axis robot per fill station, each feeding its own outfeed line.
ROBOT_A_BASE = (460.0, 135.0, 0.0)
ROBOT_B_BASE = (430.0, 205.0, 0.0)

PICK_A = (460.0, 100.0, 30.0)      # full container on fill station A
PICK_B = (400.0, 240.0, 30.0)      # full container on fill station B

# Outfeed A (station A, yellow): runs to the right at y = 170.
OUTFEED_A_Y = 170.0
OUTFEED_A_START_X = 420.0
OUTFEED_A_DROP = (430.0, OUTFEED_A_Y, 30.0)
OUTFEED_A_LIFT_X = 620.0

# Outfeed B (station B, green): runs to the right at y = 245.
OUTFEED_B_Y = 245.0
OUTFEED_B_START_X = 420.0
OUTFEED_B_DROP = (430.0, OUTFEED_B_Y, 30.0)
OUTFEED_B_LIFT_X = 620.0

OUTFEED_PITCH = 120.0             # minimum spacing between placed containers
OUTFEED_SPEED = 60.0              # mm/s (slow enough to stay visible)

# Vertical lift / palletizer parameters.
LIFT_TOP_Z = 50.0                 # mm above the line the lift carries containers
LIFT_SPEED = 40.0                 # mm/s vertical travel
LIFT_LOAD_TIME = 0.45             # seconds to load a container into the lift
LIFT_UNLOAD_TIME = 0.45           # seconds to transfer it onto the palletizer
PALLET_TARGET = {"a": 4, "b": 2}  # containers per finished pallet

GRIP_TOL = 18.0                   # mm, "close enough" to a pick/place point
