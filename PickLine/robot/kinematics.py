"""Six-axis robot kinematics (spherical-wrist 6R, gripper-down).

The robot is modelled as a vertical articulated arm: J1 yaws the arm plane, J2
(shoulder) and J3 (elbow) place the wrist centre, and the spherical wrist
(J4/J5/J6) holds the gripper pointing straight down. This is the standard
analytic form used by most industrial six-axis arms.

Units are millimetres and radians, matching the plant model.
"""
import math


class SixAxisRobot:
    def __init__(self, d1=150.0, a2=200.0, a3=180.0, d6=70.0):
        self.d1 = d1          # base to shoulder, mm
        self.a2 = a2          # upper arm
        self.a3 = a3          # forearm
        self.d6 = d6          # wrist centre to tool centre point (gripper down)

    # ------------------------------------------------------------------ #
    # Forward kinematics: joint angles -> tool centre point position.     #
    # ------------------------------------------------------------------ #
    def forward(self, q):
        q1, q2, q3, _q4, _q5, _q6 = q
        r = self.a2 * math.cos(q2) + self.a3 * math.cos(q2 + q3)
        wx = r * math.cos(q1)
        wy = r * math.sin(q1)
        wz = self.d1 + self.a2 * math.sin(q2) + self.a3 * math.sin(q2 + q3)
        # Gripper points straight down, so the TCP sits d6 below the wrist.
        return (wx, wy, wz - self.d6)

    # ------------------------------------------------------------------ #
    # Inverse kinematics: tool position -> joint angles (gripper down).   #
    # ------------------------------------------------------------------ #
    def inverse(self, position):
        x, y, z = position
        wx, wy, wz = x, y, z + self.d6

        q1 = math.atan2(wy, wx)

        r = math.hypot(wx, wy)
        h = wz - self.d1
        num = (r * r + h * h - self.a2 * self.a2 - self.a3 * self.a3)
        den = 2.0 * self.a2 * self.a3
        cos_q3 = max(-1.0, min(1.0, num / den))
        q3 = -math.acos(cos_q3)            # elbow-down solution
        q2 = math.atan2(h, r) - math.atan2(
            self.a3 * math.sin(q3), self.a2 + self.a3 * math.cos(q3)
        )

        # Wrist: keep the tool axis vertical (pointing down) and the roll
        # opposite to J1 so the gripper keeps a stable world orientation.
        q4 = 0.0
        q5 = -(q2 + q3)
        q6 = -q1
        return [q1, q2, q3, q4, q5, q6]

    # ------------------------------------------------------------------ #
    # Joint positions in the robot base frame, for 3D visualisation.      #
    # Returns [base, shoulder, elbow, wrist, tool].                       #
    # ------------------------------------------------------------------ #
    def joint_positions(self, q):
        q1, q2, q3, _q4, _q5, _q6 = q
        base = (0.0, 0.0, 0.0)
        shoulder = (0.0, 0.0, self.d1)

        # Arm plane (before the J1 yaw about Z).
        ex = self.a2 * math.cos(q2)
        ez = self.d1 + self.a2 * math.sin(q2)
        elbow_plane = (ex, 0.0, ez)
        wx = ex + self.a3 * math.cos(q2 + q3)
        wz = ez + self.a3 * math.sin(q2 + q3)
        wrist_plane = (wx, 0.0, wz)

        def yaw(point):
            x, y, z = point
            return (x * math.cos(q1) - y * math.sin(q1),
                    x * math.sin(q1) + y * math.cos(q1), z)

        elbow = yaw(elbow_plane)
        wrist = yaw(wrist_plane)
        tool = (wrist[0], wrist[1], wrist[2] - self.d6)
        return [base, shoulder, elbow, wrist, tool]
