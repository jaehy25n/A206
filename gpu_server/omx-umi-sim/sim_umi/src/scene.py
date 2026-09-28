"""Build the MuJoCo scene from measured parameters.

Written as a generator rather than a static XML because most of these numbers
are provisional: the black paper is "about 110 x 80", the robot base pose and
the camera extrinsic are not measured yet, and the manipulation object is not
chosen. Every one of those is a field here with a TODO where it is a guess, so
replacing a guess with a measurement is a one-line edit and a re-run.

Frame (table convention, as specified):

    origin = table centre, on the table SURFACE (z = 0)
    +X     = across the table, robot's left to right
    +Y     = away from the robot, into the table
    +Z     = up

The OMX base therefore sits at negative Y, centred: robot_base_xy.
"""
import dataclasses
import math
import pathlib
from typing import Optional, Tuple

ASSETS = pathlib.Path(__file__).resolve().parents[1] / "assets"


@dataclasses.dataclass
class SceneConfig:
    # ---- table --------------------------------------------------------- #
    table_size: Tuple[float, float] = (1.20, 0.80)      # measured
    table_thickness: float = 0.018
    #: Calibrated against the reference, like paper_albedo: the desk reads
    #: RGB (200, 200, 208) in the environment footage and (202, 196, 193) in
    #: the collector view -- the two agree, so the white is real and not an
    #: exposure artefact the way the work surface's grey is.
    desk_albedo: float = 0.92
    #: Room carpet, RGB (107, 98, 94) in the footage. Barely in frame, but the
    #: old 0.55 grey was lighter than the desk in places.
    floor_rgba: str = "0.42 0.385 0.37 1"
    #: Without a backdrop the top of the wrist frame is pure black void, where
    #: the reference footage shows the rest of the room. Not modelling the room
    #: -- just enough that the camera never looks at nothing.
    room_size: Tuple[float, float] = (6.0, 6.0)
    room_height: float = 2.6
    wall_rgba: str = "0.55 0.56 0.58 1"
    ceiling_rgba: str = "0.27 0.28 0.30 1"

    # ---- black work surface (검정 전지) -------------------------------- #
    # TODO(measure): "about 110 x 80 cm". Replace when the sheet is measured.
    paper_size: Tuple[float, float] = (1.10, 0.80)
    paper_center: Tuple[float, float] = (0.0, 0.0)      # table-centre frame
    #: NOT the physical albedo of black paper. Calibrated so the RENDER matches
    #: what the collector's camera actually records: the real work surface comes
    #: out at RGB (117, 113, 113) under the classroom lights with the phone's
    #: auto-exposure, not near-black. Matching the material instead of the image
    #: left the sim 10x darker than the footage it is supposed to imitate.
    paper_albedo: float = 0.275

    # ---- robot --------------------------------------------------------- #
    #: The base ORIGIN, not its edge. link0's footprint is 150 x 120 mm and the
    #: origin sits in the middle of it, so putting the origin on the table's
    #: near edge (-0.400) left 60 mm of the base hanging over nothing. Measured
    #: off the mesh: the back face lands exactly on the edge at -0.340.
    robot_base_xy: Tuple[float, float] = (0.0, -0.34)
    # From open_manipulator_x.urdf: 0.130 + 0.124 + 0.126.
    robot_reach: float = 0.380
    #: Stand the real arm up under the gripper. Without it the gripper
    #: floats, and a clearance check on a floating gripper says nothing about
    #: the elbow: the links, the base and the table are not in the model.
    use_arm: bool = True
    #: The arm is NOT rebuilt here. It is read out of ROBOTIS's own MuJoCo
    #: model (assets/omx_official/omx.xml, see PROVENANCE.txt) so that link
    #: origins, joint axes, the real joint limits, the inertias and the
    #: collision geometry are theirs, not a transcription. Their stock gripper
    #: (link6/link7, its mimic equality and its actuator) is removed and our
    #: own pivot gripper is mounted in its place.
    official_arm: str = "omx_official/omx.xml"
    #: Turn the arm's +x onto the table's +y, so the gripper's local frame --
    #: which every offset in this file is written in -- keeps pointing away
    #: from the robot.
    arm_base_yaw: float = math.pi / 2
    #: The mount: our gripper root, expressed in the official link5 frame.
    #: Derived, not chosen. Our TCP is (0.0016, 0.09193, 0) in the gripper
    #: frame; the URDF puts the end effector at (0.09193, -0.0016, 0) in
    #: link5. R_z(-90) takes the first to the second, and the same rotation
    #: takes our hinges (-0.0075, 0.0295) and (0.0108, 0.0295) onto the URDF's
    #: gripper_joint_1 (0.0295, 0.0075) and gripper_joint_2 (0.0295, -0.0108).
    #: Three independent points agreeing is the check that the sign is right;
    #: +90 would satisfy none of them.
    gripper_mount_pos: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    gripper_mount_yaw: float = -math.pi / 2

    #: Where the object and the bin stand when the model is loaded, both
    #: inside the 380 mm reach measured from the base.
    object_start_xy: Tuple[float, float] = (0.08, -0.16)
    bin_start_xy: Tuple[float, float] = (-0.14, -0.20)

    # ---- bin ----------------------------------------------------------- #
    bin_outer: float = 0.120
    bin_wall: float = 0.003
    marker_size: float = 0.060
    marker_height_frac: float = 0.60    # 1.0 = rim, 0.5 = centre -> just above
    aruco_dict: str = "4x4_50"
    bin_mass: float = 0.18

    # ---- object -------------------------------------------------------- #
    # TODO(decide): the real object is not chosen yet.
    object_type: str = "sphere"                    # box | cylinder | sphere
    #: 20 mm. Closed, the two crescents enclose a lens about 22.7 mm across at
    #: its widest (10.9 mm at the back, tips touching at the front), so that is
    #: what the cavity can cage. A 40 mm block cannot enter it at all -- it was
    #: funnelled out along the fingers, which is why the jaw kept closing to
    #: 3 mm on an object it was supposedly holding.
    #: A 50 mm styrofoam ball: radius in [0], and [2] doubles as the height
    #: the body starts at, which for a sphere is the same number.
    #:
    #: The size is not free. Measured, this claw holds a ball from about 44 mm
    #: up to 58 mm and drops 59 mm and everything above it -- the mouth simply
    #: does not close around a larger one, and on the way in the claw knocks it
    #: aside. 50 mm sits in the middle of that band.
    object_size: Tuple[float, float, float] = (0.025, 0.025, 0.025)
    #: White, because the ball is white styrofoam. 0.95 rather than a flat
    #: 1.0: styrofoam is not a perfect reflector and a clipped white loses the
    #: shading the camera needs to see it as a sphere at all. It sits on black
    #: paper, so it still separates from the background; against the gripper
    #: (0.93 PLA) it is close, which is what the real scene looks like.
    object_rgba: Tuple[float, float, float, float] = (0.95, 0.95, 0.95, 1.0)
    #: What the training set will draw from. Measured, not chosen: this claw
    #: holds a ball up to 58 mm and drops 59 mm. The lower end is where a ball
    #: stops being worth a 20 mm cavity.
    object_diameter_range: Tuple[float, float] = (0.030, 0.058)
    #: 25 kg/m3 -- styrofoam. A 50 mm ball is 1.6 g.
    object_mass: float = 0.0016

    # ---- contact ------------------------------------------------------- #
    #: MuJoCo's defaults (0.02 1 / 0.9 0.95 0.001) are soft for a 30 g finger
    #: against an 80 g block. Tightened only after the geometry and the
    #: contact normals were confirmed correct.
    contact_solref: str = "0.004 1"
    contact_solimp: str = "0.95 0.99 0.0005"

    # ---- collector gripper --------------------------------------------- #
    # Sized from open_manipulator_x.urdf rather than invented:
    #   gripper_*_joint origin  +-0.021 m, stroke [-0.011, +0.020]
    #   palm bbox               88.1 x 39.75 x 58.0 mm
    # so the real jaw spans roughly 0 mm closed to 58 mm open. The earlier
    # abstract collector opened to 94 mm with a 126 mm outer span, which is
    # wider than the bin's 114 mm opening -- it could not have been lowered
    # inside. Collision stays box-shaped on purpose; the visual mesh can be
    # swapped in later without touching contact behaviour.
    #: PIVOT gripper, from urdf/omx_f/omx_f.urdf -- the arm with five revolute
    #: joints and a hinged jaw, not open_manipulator_x's four joints and
    #: parallel slide. The two fingers hinge about z at asymmetric offsets and
    #: joint_2 mimics joint_1 with multiplier -1, so one motor drives both
    #: through a gear. Their midline lands at y = -1.65 mm, which is where the
    #: URDF puts its end effector (-1.6 mm) -- the geometry checks itself.
    hinge_a_xy: Tuple[float, float] = (0.0295, 0.0075)     # motorized finger
    hinge_b_xy: Tuple[float, float] = (0.0295, -0.0108)    # gear finger
    finger_length: float = 0.065               # mesh x-max
    finger_half_width: float = 0.010           # mesh y half-extent
    finger_half_height: float = 0.0213
    hinge_range: Tuple[float, float] = (0.0, 0.47)   # rad; 0 closed, 0.47 open

    # ---- gripper actuator ----------------------------------------------- #
    # The real one is NOT a position servo. From omx_f.ros2_control.xacro,
    # gripper dxl16:
    #     Operating Mode   5      <- Current-based Position Control
    #     Current Limit  600 / Goal Current 600
    #     Position P Gain 1000 / I 0 / D 1000
    #     Profile Velocity 50 / Acceleration 25
    #     (no Min/Max Position Limit, unlike the arm joints at Mode 3)
    # so it is given a position target and a current cap, and on contact the
    # joint stalls short of the target. Only gripper_joint_1 is commanded;
    # joint_2 mimics it. MuJoCo reproduces that as a position actuator with
    # forcerange, which is why the jaw is told to CLOSE rather than told a
    # width -- inverse geometry from a width was where three sign and offset
    # bugs came from, and it cannot check itself.
    #
    # TODO(measure): the motor model is not in this repo (dxl_model is a
    # runtime path), so the current -> torque constant is unconfirmed. 600 of
    # 1193 raw units is about half of full current; the default below assumes
    # an XM430-class stall torque of ~4.1 N*m, giving ~2.0 N*m. Replace with
    # the measured stall torque when the part number is known.
    #: The gripper's current limit, in N.m at the tendon. Measured against a
    #: 1.6 g styrofoam ball: at 0.2 and below the claw never grips it, at 2.0
    #: it squeezes 64 N and fires the ball 212 mm across the table, and at 0.5
    #: it holds (13 N, ball lifted). This is the real Mode-5 current limit, so
    #: it is a task setting, not a physics tweak.
    gripper_force_limit: float = 0.5        # N*m at the finger hinge
    gripper_kp: float = 60.0                # N*m/rad; saturates well before
                                            # the cap over the usable stroke
    #: Visual comes from the real palm STL; collision stays a box. The box is
    #: placed so its inner face matches the mesh's: the palm's inner surface is
    #: 12.2 mm from the joint origin toward the centreline (STL y-min).
    use_gripper_mesh: bool = True
    pad_thickness: float = 0.008               # collision box on the inner face
    #: A pivot gripper grips near the tip, and the URDF's end effector sits at
    #: 62.4 mm from the hinge against a 65 mm finger -- so the pad has to reach
    #: there. Centred at 46 mm it ended 16 mm short of the TCP, which is where
    #: the block is placed, so the jaw closed on empty air every time.
    #: Collision stations on the finger's INNER contour, measured from
    #: follower_07_gripper_motorized.stl across its FULL height -- the earlier
    #: numbers came from a |z| < 3 mm slice, which is a thin cut through the
    #: middle and understates the curve.
    #:
    #:   x (along finger)   inner surface y      -> station x = -y
    #:      0 mm             -10.00 mm
    #:     20                 -3.75
    #:     30                 +0.20   (cavity: the face pulls away)
    #:     40                 +0.19
    #:     50                 -3.59
    #:     60                 -9.15   (tip hooks back in)
    #:
    #: A ~10 mm deep concave face, and two of them closing make the lens the
    #: CAD shows. Each entry is (y_along_finger, inner_surface_x, radius,
    #: half_height); the capsule axis sits one radius behind the surface, and
    #: half_height follows the finger's taper so the tip does not collide
    #: taller than it is.
    #: (y_along_finger, inner_surface_x, half_thickness, half_height)
    #: (y_along_finger, inner_surface_x, OUTER_surface_x, half_height).
    #: Each station spans the finger's full cross-section, so the collision
    #: envelope matches the visual arm. Contact pads alone covered only the
    #: inner face, which left the outer half of the crescent with no collision
    #: at all -- the rendered arm swept straight through the bin wall.
    #: Outer values read off the same mesh slice as the inner ones.
    #: The stack stops at y = 20 mm on purpose. The two fingers are a meshed
    #: gear pair: their meshes run 0.04-0.12 mm apart through the whole stroke
    #: around the hinge (finger-frame y about -1.5 mm), which is what meshing
    #: teeth do. Boxes there are not a conservative approximation of the part,
    #: they are a bridge across the gap -- the stations at y = 0 and 10 mm
    #: overlapped the other finger by 1.5-1.8 mm at EVERY angle and pushed the
    #: jaw open: commanded shut, the joint stalled at 0.025 rad. The mesh
    #: itself closes to 0.00 mm tip to tip at q = 0.
    pad_stations: Tuple[Tuple[float, float, float, float], ...] = (
        # (y along the finger, inner x, outer x, half height) -- every number
        # cast at the mesh by scripts/fit_finger_pads.py, not drawn. The claw
        # is a hollow truss (a crescent from above, a windowed I-beam from the
        # side); the windows are lightening holes, so the boxes fill them and
        # model the claw as the solid wall an object actually presses on.
        # Guessed values had the pads twice as thick as the part and pushed
        # 6-8 mm outward, which is a collision with the bin that never happens.
        (0.020, +0.00226, -0.00991, 0.01975),   # claw 12.17 mm thick
        (0.025, +0.00039, -0.00947, 0.01850),   # claw  9.86
        (0.030, -0.00098, -0.00880, 0.01700),   # claw  7.81
        (0.035, -0.00139, -0.00785, 0.01575),   # claw  6.46
        (0.040, -0.00101, -0.00663, 0.01425),   # claw  5.61
        (0.045, +0.00024, -0.00514, 0.01300),   # claw  5.38
        (0.050, +0.00247, -0.00334, 0.01150),   # claw  5.81
        (0.055, +0.00578, -0.00127, 0.01025),   # claw  7.05
        (0.060, +0.00915, +0.00094, 0.00875),   # claw  8.21
    )
    pad_half_height: float = 0.018
    #: Where the jaw width is READ, held independent of the pad stack so that
    #: changing the contact geometry cannot silently redefine "gripper width"
    #: -- and with it the jaw table, the grasp command and the vision fit.
    #:
    #: 9.15 mm is not a choice: the hinges sit 18.3 mm apart (URDF, 7.5 and
    #: -10.8 mm), so two mirrored points meet exactly at (0.0075 + 0.0108)/2.
    #: It is also where the contour ends, and where the two meshes touch at
    #: q = 0. At the 10.0 mm used before, the two sites CROSSED by 1.7 mm at
    #: full close, so the width curve folded into a V -- a 0.3 mm reading meant
    #: the jaw was 1.4 mm past shut, and the jaw table, which sorts by width,
    #: quietly reordered itself around the fold.
    inner_site_x: float = 0.00915
    #: URDF: gripper joint at x=0.0817, end_effector at x=0.126 from link5.
    #: The TCP is therefore 44.3 mm ahead of the gripper origin -- inside the
    #: palm, not past its tip. An earlier guess of 120 mm put the grasp point
    #: 55 mm beyond the fingers, which grips nothing and drops it in transit.
    #: urdf/omx_f: end_effector_joint at (0.09193, -0.0016, 0) from link5.
    #: This is the TOOL frame and stays as the contract's TCP.
    tcp_offset: Tuple[float, float, float] = (0.0016, 0.09193, 0.0)
    #: Where a grasped object actually sits, which is not the tool frame. The
    #: deepest contour station is 60 mm along the finger -- 89.5 mm from the
    #: gripper origin -- so an object centred on the 91.9 mm TCP hangs past the
    #: fingertips and gets shoved forward: contact normals came out 0.98 along
    #: the finger instead of across it. The cavity centre is ~35 mm along the
    #: finger, so the scripted demo aims THIS point at the object while the
    #: policy's actions stay in the TCP frame.
    grasp_point_offset: Tuple[float, float, float] = (0.0016, 0.0645, 0.0)

    # ---- gripper appearance -------------------------------------------- #
    #: Both the collector and the real OMX use white PLA for the gripper; the
    #: rest of the arm is dark. Only the gripper is in the wrist view, so this
    #: is the colour the visual encoder actually sees.
    gripper_rgba: Tuple[float, float, float, float] = (0.93, 0.93, 0.93, 1.0)

    # ---- magenta tip patches (collector only) --------------------------- #
    #: The collector has no encoder on its jaw, so its opening is read off the
    #: camera: two saturated patches near the fingertips, thresholded and
    #: paired. The real OMX has no patches -- it reads its Dynamixel instead --
    #: so these are masked out of the RGB before the policy sees it.
    use_magenta_tips: bool = True
    magenta_rgba: Tuple[float, float, float, float] = (1.0, 0.0, 0.85, 1.0)
    #: Where the sticker goes, found by casting rays straight down onto the
    #: finger mesh IN THE FINGER'S OWN FRAME and reading back the hit -- not by
    #: reading the STL's bounding box. The mesh is turned 90 deg when it is
    #: mounted (euler 0 0 1.5708), so an x taken from the STL lands on the
    #: wrong axis: the previous -6.4 mm put the patch where the finger has no
    #: material at all near the tip (at y 61..65 mm the mesh spans x +1.8 ..
    #: +9.2 mm), and it rendered as a magenta square floating BESIDE the
    #: gripper. The earlier "9.59 mm surface" was measured there too, from the
    #: four stray vertices within 4 mm of a point that is off the part.
    #:
    #: The ray grid, left finger, top surface (mm):
    #:     y  56  58  60  62  64
    #:     z  9.98 9.43 8.88 8.33 7.78     flat in x, -0.275 mm per mm of y
    #:
    #: x is the LEFT finger's; the right one is its mirror, -x.
    #:
    #: The patch sat at x +6.0 and the held ball covered it. A 50 mm ball
    #: cradled above tips that shut to 31.5 mm is wider than the gap between
    #: them, and in the wrist camera its silhouette swallows the tips: a third
    #: of the recorded samples had no measurement and the width held "open"
    #: through the carry. scripts/fit_tip_patch.py casts a ray from the camera
    #: to every candidate spot, in four grasps that really hold the ball and
    #: with the jaw open as well, and measures how much of the square still
    #: reaches the lens. The old spot: 84% on the mesh, 2% visible. This one:
    #: 96% on the mesh, 76% visible, and 1.71 px per mm of jaw -- the same
    #: sensitivity the frozen calibration was fitted at (1.70), so only the
    #: offset moves.
    magenta_patch_x: float = 0.0025
    magenta_patch_y: float = 0.0605
    #: 0.1 mm proud of the 8.74 mm surface at (x 2.5, y 60.5) mm.
    magenta_patch_z: float = 0.00884
    #: The tip surface is a wedge, so a flat patch laid on it would bury one
    #: edge and lift the other by 0.4 mm over 3 mm. Lie it along the slope
    #: instead: atan(0.275) = 15.4 deg, negative so that +y tips downward.
    magenta_patch_pitch: float = -0.2685
    #: The jaw-width sites stay where they were. They are what
    #: `_measure_jaw_table` and every grasp decision are built on, and moving
    #: them because the sticker moved would redefine "gripper width" silently.
    inner_site_y: float = 0.055
    #: 2 x 2 mm. The corridor the ball leaves visible is only about 2 mm wide,
    #: and a 3 mm square laid in it keeps just over half its area: the visible
    #: part then shifts with wherever the ball settles, and so does its
    #: centroid. A square that fits sees 76% of itself instead of 55% and its
    #: centroid is the patch's, not the occlusion boundary's.
    magenta_patch_size: Tuple[float, float] = (0.0010, 0.0010)  # half-extents

    #: Rendering only -- these change what the camera can see, never physics.
    #: near = render_extent * render_znear = 4 mm, far = 30 m (the room is
    #: 6 m, so it still fits).
    #: Hide the stock wrist mount. See _official_arm for why.
    omit_link5_visual: bool = True
    #: What the camera plugin publishes, and what the collector records: the
    #: 16:9 raw stream, 65.5 deg across like the real lens.
    wrist_cam_resolution: Tuple[int, int] = (320, 180)
    render_extent: float = 1.0
    render_center_y: float = -0.10
    render_znear: float = 0.004
    render_zfar: float = 30.0

    # ---- wrist camera --------------------------------------------------- #
    # TODO(measure): camera<->TCP extrinsic. Keep the FOV at 60 deg.
    #: From the collector's own metadata.json (session a28cec73):
    #:   1920x1080, fx 1491.89 fy 1491.65, cx 973.02 cy 541.52
    #:   -> HFOV 65.5 deg, VFOV 39.8 deg
    #: MuJoCo's fovy is vertical, so 39.8 -- not the 60 that was guessed.
    wrist_cam_pos: Tuple[float, float, float] = (0.0, -0.01, 0.14)
    wrist_cam_pitch_deg: float = 42.0       # below horizontal
    #: Matched to the reference footage by eye against a measured target, after
    #: an automated match went wrong: a white-blob detector run over the real
    #: video was catching white pliers, printed parts and the laptop as often as
    #: the gripper, so the numbers it produced (9.5% of pixels, 0.38 of width)
    #: described no single object and nothing converged on them.
    #:
    #: The one clean reference frame shows the gripper occupying the bottom ~38%
    #: with only the front crescents in view -- the camera sits BEHIND the
    #: gripper, raised, and tilted shallow enough that the gear housing falls
    #: below the frame. This pose reproduces that.
    wrist_cam_fovy: float = 39.8

    # ---- lighting ------------------------------------------------------- #
    # Classroom ceiling panels: several broad overhead sources. Not tuned.
    ceiling_height: float = 2.40
    #: Calibrated with paper_albedo against the reference footage, not set by
    #: eye. Classroom lighting plus the phone's auto-exposure is what the policy
    #: sees, so the render is matched to the recording.
    light_diffuse: float = 0.34
    n_ceiling_lights: int = 4

    # ---- render --------------------------------------------------------- #
    offwidth: int = 1280
    offheight: int = 960

    # ------------------------------------------------------------------ #
    @property
    def bin_inner(self) -> float:
        return self.bin_outer - 2 * self.bin_wall

    def gap_at(self, theta: float) -> float:
        """Inner-face separation at hinge angle `theta` (rad).

        The fingers swing, so the tips travel on an arc and the faces both
        translate and tilt -- there is no constant stroke to add.
        """
        ay, by = self.hinge_a_xy[1], self.hinge_b_xy[1]
        L, w = self.finger_length, self.finger_half_width
        inner_a = ay + L * math.sin(theta) - w * math.cos(theta)
        inner_b = by - L * math.sin(theta) + w * math.cos(theta)
        return inner_a - inner_b

    def theta_for_gap(self, gap: float, tol: float = 1e-6) -> float:
        """Invert gap_at() numerically; it is not linear in theta."""
        lo, hi = self.hinge_range
        for _ in range(60):
            mid = (lo + hi) / 2
            if self.gap_at(mid) < gap:
                lo = mid
            else:
                hi = mid
            if hi - lo < tol:
                break
        return (lo + hi) / 2

    @property
    def gripper_open_gap(self) -> float:
        return self.gap_at(self.hinge_range[1])

    @property
    def gripper_closed_gap(self) -> float:
        return max(0.0, self.gap_at(self.hinge_range[0]))

    @property
    def gripper_outer_span(self) -> float:
        """Widest the jaw gets, for checking it fits inside the bin."""
        t = self.hinge_range[1]
        ay, by = self.hinge_a_xy[1], self.hinge_b_xy[1]
        L, w = self.finger_length, self.finger_half_width
        outer_a = ay + L * math.sin(t) + w * math.cos(t)
        outer_b = by - L * math.sin(t) - w * math.cos(t)
        return outer_a - outer_b

    def reachable(self, x: float, y: float, margin: float = 0.03) -> bool:
        bx, by = self.robot_base_xy
        return math.hypot(x - bx, y - by) <= self.robot_reach - margin

    def on_paper(self, x: float, y: float, clearance: float = 0.0) -> bool:
        pw, ph = self.paper_size
        cx, cy = self.paper_center
        return (abs(x - cx) <= pw / 2 - clearance
                and abs(y - cy) <= ph / 2 - clearance)

    def to_dict(self) -> dict:
        d = dataclasses.asdict(self)
        d["bin_inner"] = round(self.bin_inner, 5)
        d["gripper_open_gap"] = round(self.gripper_open_gap, 5)
        d["gripper_closed_gap"] = round(self.gripper_closed_gap, 5)
        return d


def _obj_geom(c: SceneConfig) -> str:
    if c.object_type == "box":
        size = " ".join(f"{v:.5f}" for v in c.object_size)
        return f'type="box" size="{size}"'
    if c.object_type == "cylinder":
        r, h = c.object_size[0], c.object_size[2]
        return f'type="cylinder" size="{r:.5f} {h:.5f}"'
    if c.object_type == "sphere":
        return f'type="sphere" size="{c.object_size[0]:.5f}"'
    raise ValueError(f"object_type {c.object_type!r} not in (box, cylinder, sphere)")


def _official_arm(c: "SceneConfig", gripper_block: str):
    """Lift the arm straight out of ROBOTIS's MuJoCo model.

    Returns (mesh assets, defaults, worldbody, actuators, contact excludes).
    Nothing here is transcribed: link origins, joint axes, the real joint
    limits (J2/J3 are -120..+90 deg, not the URDF's placeholder +-2 pi), the
    inertias and the collision meshes are read from the file. What we change
    is exactly three things, and each is a deletion or a mount:

      * link6 and link7, their mimic equality and the Gripper actuator are
        removed -- that is their stock gripper, and ours is the one that has
        been measured, tuned and verified.
      * link0 is placed on the table and turned so the arm's +x is the table's
        +y.
      * our gripper hangs off link5 at gripper_mount_yaw.

    Their file also excludes link6 from link7 -- ROBOTIS switch the two
    fingers' collision off against each other. Ours does not need that: the
    pads were measured off the claw and no longer bridge the gear.
    """
    import xml.etree.ElementTree as ET

    path = pathlib.Path(__file__).resolve().parents[1] / "assets" / c.official_arm
    root = ET.parse(path).getroot()
    # ros2_control maps a URDF joint to the MJCF actuator of the same name, so
    # the two files have to agree. ROBOTIS's MuJoCo model calls them Joint1..5
    # and their URDF calls them joint1..5; the URDF name wins, because that is
    # what MoveIt, the SRDF, joint_limits.yaml and the controllers all use.
    for el in root.iter():
        for attr in ("name", "joint", "class", "joint1", "joint2"):
            v = el.get(attr)
            if v and v.startswith("Joint") and v[5:].isdigit():
                el.set(attr, "joint" + v[5:])

    sub = path.parent.name  # assets/<here>/omx.xml, meshes are alongside

    meshes = []
    for mesh in root.findall("./asset/mesh"):
        name = mesh.get("name")
        if name in ("follower_07_gripper_motorized", "follower_08_gripper_gear"):
            continue          # our gripper already declares these
        meshes.append(f'    <mesh name="{name}" '
                      f'file="{sub}/assets/{mesh.get("file")}" '
                      f'scale="{mesh.get("scale")}"/>')

    dflt = root.find("./default/default[@class='omx']")
    defaults = "    " + ET.tostring(dflt, encoding="unicode").strip()

    link0 = root.find("./worldbody/body[@name='link0']")
    bx, by = c.robot_base_xy
    link0.set("pos", f"{bx:.5f} {by:.5f} 0")
    link0.set("euler", f"0 0 {c.arm_base_yaw:.5f}")
    link5 = link0.find(".//body[@name='link5']")
    if c.omit_link5_visual:
        # follower_06_pan_Revised is the stock camera/gripper mount, and it is
        # not the bracket on the real arm -- a different one is fitted there.
        # It sits 127.7 mm from the wrist camera, closer than anything else in
        # the view, so leaving it in puts a black slab across the bottom of
        # every frame the policy would be trained on. The VISUAL geom goes; the
        # collision geom stays, because something is bolted there and a
        # conservative volume is better than none.
        for g in list(link5.findall("./geom")):
            if g.get("class") == "visual":
                link5.remove(g)
    for stock in ("link6", "link7"):
        gone = link5.find(f"./body[@name='{stock}']")
        if gone is not None:
            link5.remove(gone)
    mx, my, mz = c.gripper_mount_pos
    mount = ET.SubElement(link5, "body")
    mount.set("name", "collector")
    mount.set("pos", f"{mx:.5f} {my:.5f} {mz:.5f}")
    mount.set("euler", f"0 0 {c.gripper_mount_yaw:.5f}")
    mount.text = "@GRIPPER@"
    body = ET.tostring(link0, encoding="unicode")
    body = body.replace("@GRIPPER@", "\n" + gripper_block + "\n      ")

    acts = [f'    {ET.tostring(a, encoding="unicode").strip()}'
            for a in root.findall("./actuator/position")
            if a.get("joint") not in ("Gripper", "Gripper_mimic")]

    excl = [f'    {ET.tostring(e, encoding="unicode").strip()}'
            for e in root.findall("./contact/exclude")
            if "link6" not in (e.get("body1"), e.get("body2"))
            and "link7" not in (e.get("body1"), e.get("body2"))]

    return ("\n".join(meshes), defaults, "    " + body.strip(),
            "\n".join(acts), "\n".join(excl))


def build_xml(c: SceneConfig) -> str:
    tw, th = (v / 2 for v in c.table_size)
    pw, ph = (v / 2 for v in c.paper_size)
    pcx, pcy = c.paper_center
    b, w = c.bin_outer / 2, c.bin_wall / 2
    ms = c.marker_size / 2
    mz = c.bin_outer * c.marker_height_frac
    # URDF fingers extend +x and hinge about z; this scene has them along +y
    # opening across +-x, so everything turns 90 deg about z: (x, y) -> (-y, x).
    # The hinge axis is z in both, so it survives the rotation unchanged.
    hax, hay = -c.hinge_a_xy[1], c.hinge_a_xy[0]
    hbx, hby = -c.hinge_b_xy[1], c.hinge_b_xy[0]
    th0, th1 = c.hinge_range
    # Measure the jaw where it actually touches. finger_half_width is the
    # mesh's widest point, but the contact surface only reaches the deepest
    # station -- putting the sites at the wider value made a 38 mm reading mean
    # 39.7 mm of real opening, so a 40 mm block was never gripped at all.
    innx = c.inner_site_x
    def _pads(sign):
        """Boxes tangent to the contour, not rods on it.

        A thin capsule touches a flat block along a line, and 18 N through a
        line contact fires a 40 mm cube out of the jaw. The real crescent
        presents a broad curved face, so each station gets a flat patch turned
        to the local tangent -- together they approximate the curve while each
        one contacts a flat face over an area.
        """
        st = c.pad_stations
        out = []
        for i, (py, px_in, px_out, ph) in enumerate(st):
            j0, j1 = max(0, i - 1), min(len(st) - 1, i + 1)
            dy = st[j1][0] - st[j0][0]
            dx = st[j1][1] - st[j0][1]
            ang = math.atan2(dx, dy) if dy else 0.0
            # Half the station spacing, so the boxes tile the claw instead of
            # overlapping two neighbours each. A longer box cannot follow a
            # curve: at 5 mm half-length the tip boxes left the material by
            # 5 mm, at 2.5 mm by 2.
            half_len = max(0.002, (st[j1][0] - st[j0][0]) / 4) if dy else 0.003
            half_t = abs(px_in - px_out) / 2
            # A box turned to the local tangent has its inner FACE parallel to
            # the contour, so its corners lie on the contour and stick out of
            # nothing -- except at the last station, where the contour ends and
            # the box simply overhangs the tip. There the corner swung 1.8 mm
            # past the meeting point, the two tip pads overlapped by 3.6 mm at
            # full close, and the jaw stalled 1.6 mm open. Inset that one until
            # its corner, not its face, sits on the contour.
            inset = 0.0
            if i == len(st) - 1:
                inset = (half_t * (1 - math.cos(ang))
                         + half_len * abs(math.sin(ang)))
            cx = sign * ((px_in + px_out) / 2 - inset)
            side = "left" if sign > 0 else "right"
            out.append(
                f'        <geom name="{side}_pad_{i}" class="finger" type="box"\n'
                f'              pos="{cx:.5f} {py:.5f} 0" '
                f'euler="0 0 {sign*ang:.5f}"\n'
                f'              size="{half_t:.5f} {half_len:.5f} {ph:.5f}"/>')
        return "\n".join(out)
    lpads, rpads = _pads(1), _pads(-1)
    tx, ty, tz = c.tcp_offset
    cam = (f'pos="{c.wrist_cam_pos[0]} {c.wrist_cam_pos[1]} '
           f'{c.wrist_cam_pos[2]}"')

    # ---- the arm ---------------------------------------------------------
    # The gripper block is the same either way; what changes is what holds it.
    # With the arm it hangs off link5, turned so its local +y (the finger
    # direction, which every offset in this file is written in) lands on the
    # arm's +x. Without the arm it is a free body on a weld, which is the
    # handheld collector -- useful for isolating the gripper, useless for
    # asking whether the elbow clears the bin.
    mesh_rot = 'euler="0 0 1.5708"'
    lmesh = (f'        <geom name="finger_a_visual" class="visualmesh" '
             f'mesh="finger_a" {mesh_rot}/>' if c.use_gripper_mesh else "")
    rmesh = (f'        <geom name="finger_b_visual" class="visualmesh" '
             f'mesh="finger_b" {mesh_rot}/>' if c.use_gripper_mesh else "")
    mx, my = c.magenta_patch_size
    def _tip(name, sign):
        if not c.use_magenta_tips:
            return ""
        return (f'        <geom name="{name}" class="tippatch" '
                f'pos="{sign * c.magenta_patch_x:.5f} {c.magenta_patch_y:.5f} '
                f'{c.magenta_patch_z:.5f}" '
                f'euler="{c.magenta_patch_pitch:.5f} 0 0" '
                f'size="{mx:.5f} {my:.5f} 0.0004"/>')
    ltip = _tip("left_tip_patch", 1.0)
    rtip = _tip("right_tip_patch", -1.0)

    gripper_block = f"""      <camera name="wrist" {cam} xyaxes="1 0 0 0 {math.sin(math.radians(c.wrist_cam_pitch_deg)):.4f} {math.cos(math.radians(c.wrist_cam_pitch_deg)):.4f}" fovy="{c.wrist_cam_fovy}" resolution="{c.wrist_cam_resolution[0]} {c.wrist_cam_resolution[1]}"/>
      <site name="tcp" pos="{tx:.5f} {ty:.5f} {tz:.5f}" size="0.005" rgba="1 0 0 0"/>

      <body name="left_finger" pos="{hax:.5f} {hay:.5f} 0">
        <joint name="gripper_joint_1" type="hinge" axis="0 0 1"
               range="{th0:.5f} {th1:.5f}" damping="0.05"/>
{lmesh}
{ltip}
{lpads}
        <site name="left_inner" pos="{innx:.5f} {c.inner_site_y:.5f} 0"
              size="0.002" rgba="0 0 0 0"/>
      </body>

      <body name="right_finger" pos="{hbx:.5f} {hby:.5f} 0">
        <joint name="gripper_joint_2" type="hinge" axis="0 0 -1"
               range="{th0:.5f} {th1:.5f}" damping="0.05"/>
{rmesh}
{rtip}
{rpads}
        <site name="right_inner" pos="{-innx:.5f} {c.inner_site_y:.5f} 0"
              size="0.002" rgba="0 0 0 0"/>
      </body>"""

    if c.use_arm:
        arm_meshes, arm_defaults, robot, arm_actuators, arm_contacts = \
            _official_arm(c, gripper_block)
        equality = "  <equality/>\n"
    else:
        arm_meshes = arm_defaults = arm_contacts = ""
        robot = ('    <body name="mocap_target" mocap="true" pos="0 0 0.16"/>\n\n'
                 '    <body name="collector" pos="0 0 0.16">\n'
                 '      <freejoint/>\n'
                 '      <inertial pos="0 0 0" mass="0.3" '
                 'diaginertia="0.002 0.002 0.002"/>\n'
                 + gripper_block + "\n    </body>")
        equality = ('  <equality>\n'
                    '    <weld body1="collector" body2="mocap_target" '
                    'relpose="0 0 0 1 0 0 0" solref="0.002 1"/>\n'
                    '  </equality>\n')
        arm_actuators = ""

    lights = []
    n = max(1, c.n_ceiling_lights)
    for i in range(n):
        lx = -0.45 + 0.90 * (i % 2)
        ly = -0.20 + 0.40 * (i // 2)
        lights.append(
            f'    <light name="ceil_{i}" pos="{lx} {ly} {c.ceiling_height}" '
            f'dir="0 0 -1" diffuse="{c.light_diffuse} {c.light_diffuse} {c.light_diffuse*0.97:.3f}" specular="0.05 0.05 0.05"/>')

    markers = []
    for i, (px, py, sx, sy) in enumerate([
            (0.0, -(b + 0.0002), ms, 0.0002),
            ((b + 0.0002), 0.0, 0.0002, ms),
            (0.0, (b + 0.0002), ms, 0.0002),
            (-(b + 0.0002), 0.0, 0.0002, ms)]):
        markers.append(
            f'      <geom name="aruco_{i}" class="decal" material="aruco{i}_mat"\n'
            f'            pos="{px:.5f} {py:.5f} {mz:.5f}" '
            f'size="{sx:.5f} {sy:.5f} {ms:.5f}"/>')

    return f"""<mujoco model="omx_umi_collector_scene">
  <!-- GENERATED by sim_umi/src/scene.py -- edit SceneConfig, not this file.

       Frame: origin = table centre, on the surface. +X across, +Y away from
       the robot, +Z up. The OMX base is at {c.robot_base_xy}, reach
       {c.robot_reach} m (from open_manipulator_x.urdf).
  -->
  <compiler angle="radian" autolimits="true" texturedir="../assets" meshdir="../assets"/>
  <option timestep="0.002" gravity="0 0 -9.81" integrator="implicitfast"/>

  <!-- The near clipping plane is stat.extent * map.znear, and extent is
       computed from the model, which now contains a 6 m room. That put the
       near plane at 128.7 mm while the wrist camera sits 133.8 mm from a
       grasped 50 mm ball: 5 mm of margin, and the ball was opening up in the
       policy's own view as soon as the lift brought it closer. Pin the extent
       to the working volume instead of the room, and clip at a few
       millimetres, which is what the real lens does. -->
  <statistic extent="{c.render_extent}" center="0 {c.render_center_y} 0.15"/>

  <visual>
    <global offwidth="{c.offwidth}" offheight="{c.offheight}"/>
    <map znear="{c.render_znear}" zfar="{c.render_zfar}"/>
    <headlight ambient="0.34 0.34 0.34" diffuse="0.32 0.32 0.32" specular="0 0 0"/>
  </visual>

  <asset>
    <texture name="aruco0" type="cube" file="aruco_{c.aruco_dict}_0.png"/>
    <texture name="aruco1" type="cube" file="aruco_{c.aruco_dict}_1.png"/>
    <texture name="aruco2" type="cube" file="aruco_{c.aruco_dict}_2.png"/>
    <texture name="aruco3" type="cube" file="aruco_{c.aruco_dict}_3.png"/>
    <material name="aruco0_mat" texture="aruco0" specular="0.1" shininess="0.1"/>
    <material name="aruco1_mat" texture="aruco1" specular="0.1" shininess="0.1"/>
    <material name="aruco2_mat" texture="aruco2" specular="0.1" shininess="0.1"/>
    <material name="aruco3_mat" texture="aruco3" specular="0.1" shininess="0.1"/>
    <material name="desk_white" rgba="{c.desk_albedo} {c.desk_albedo} {c.desk_albedo*0.98:.3f} 1" specular="0.15" shininess="0.2"/>
    <material name="paper_black" rgba="{c.paper_albedo} {c.paper_albedo} {c.paper_albedo*1.05:.4f} 1" specular="0.05" shininess="0.05"/>
    <material name="pla_white" rgba="0.93 0.93 0.93 1" specular="0.2" shininess="0.25"/>
    <material name="omx_dark" rgba="0.18 0.19 0.21 1" specular="0.3" shininess="0.4"/>
    <!-- the official model's links are "black"; keep its name so its geoms
         resolve, and give it the arm's real colour rather than pure black. -->
    <material name="black" rgba="0.16 0.17 0.19 1" specular="0.3" shininess="0.4"/>
    <material name="omx_gripper" rgba="{' '.join(str(v) for v in c.gripper_rgba)}"
              specular="0.2" shininess="0.25"/>
    <material name="tip_magenta" rgba="{' '.join(str(v) for v in c.magenta_rgba)}"
              specular="0.05" shininess="0.05"/>
    <mesh name="finger_a" file="omx/follower_07_gripper_motorized.stl" scale="0.001 0.001 0.001"/>
    <mesh name="finger_b" file="omx/follower_08_gripper_gear.stl" scale="0.001 0.001 0.001"/>
{arm_meshes}
  </asset>

  <default>
{arm_defaults}
    <joint damping="1"/>
    <geom friction="2 0.1 0.01" condim="4"/>
    <default class="decal">
      <geom type="box" contype="0" conaffinity="0" group="1"/>
    </default>
    <default class="binwall">
      <geom type="box" material="pla_white" friction="1.2 0.05 0.01"/>
    </default>
    <default class="finger">
      <!-- physics only: invisible box, real shape is the mesh above it.
           solref is stiffened from the 0.02 s default: at the default the
           pads sank 2-5 mm into the block for 1 mm of commanded squeeze and
           produced under half a newton, so the actuator's force never
           reached the object and it slid out while standing still. -->
      <!-- No contact margin here, and none on the bin either. Both were
           tried, to read a near miss off contact.dist, and both perturbed the
           thing they were measuring: on the bin it armed wall-vs-paper
           contacts whose normals are horizontal and the sideways micro-shoves
           threw the bin off the table; on the pads it cost the grasp. The
           clearance log is computed geometrically instead, outside the
           solver -- see Collector._bin_clearance. -->
      <geom rgba="0 0 0 0" mass="0.0075" friction="3 0.1 0.01"
            solref="{c.contact_solref}" solimp="{c.contact_solimp}"/>
    </default>
    <default class="visualmesh">
      <geom type="mesh" material="omx_gripper" contype="0" conaffinity="0"
            group="1" mass="0"/>
    </default>
    <default class="tippatch">
      <geom type="box" material="tip_magenta" contype="0" conaffinity="0"
            group="1" mass="0"/>
    </default>
  </default>

  <worldbody>
{chr(10).join(lights)}

    <geom name="room_floor" type="plane" pos="0 0 {-0.73:.3f}"
          size="{c.room_size[0]:.1f} {c.room_size[1]:.1f} 0.1" rgba="{c.floor_rgba}"/>
    <!-- room shell: the wrist camera looks out past the table, and without
         these the upper part of every frame is black void. -->
    <geom name="wall_far" type="box" rgba="{c.wall_rgba}"
          pos="0 {c.room_size[1]/2:.2f} {(c.room_height-0.73)/2:.2f}"
          size="{c.room_size[0]/2:.2f} 0.02 {(c.room_height+0.73)/2:.2f}"
          contype="0" conaffinity="0"/>
    <geom name="wall_left" type="box" rgba="{c.wall_rgba}"
          pos="{-c.room_size[0]/2:.2f} 0 {(c.room_height-0.73)/2:.2f}"
          size="0.02 {c.room_size[1]/2:.2f} {(c.room_height+0.73)/2:.2f}"
          contype="0" conaffinity="0"/>
    <geom name="wall_right" type="box" rgba="{c.wall_rgba}"
          pos="{c.room_size[0]/2:.2f} 0 {(c.room_height-0.73)/2:.2f}"
          size="0.02 {c.room_size[1]/2:.2f} {(c.room_height+0.73)/2:.2f}"
          contype="0" conaffinity="0"/>
    <geom name="ceiling" type="box" rgba="{c.ceiling_rgba}"
          pos="0 0 {c.room_height:.2f}"
          size="{c.room_size[0]/2:.2f} {c.room_size[1]/2:.2f} 0.02"
          contype="0" conaffinity="0"/>

    <geom name="desk" type="box" pos="0 0 {-c.table_thickness/2:.5f}"
          size="{tw:.5f} {th:.5f} {c.table_thickness/2:.5f}" material="desk_white"/>

    <geom name="black_paper" type="box" pos="{pcx:.5f} {pcy:.5f} 0.0005"
          size="{pw:.5f} {ph:.5f} 0.0005" material="paper_black"
          friction="1.5 0.08 0.01"/>

    <!-- measurement sites only: MuJoCo's default site colour is opaque grey,
         which rendered as little balls at the fingertips inside camera0_rgb --
         geometry the real collector does not have. -->
    <site name="robot_base" pos="{c.robot_base_xy[0]:.5f} {c.robot_base_xy[1]:.5f} 0"
          size="0.012" rgba="0 0 0 0"/>

{robot}

    <!-- The MJCF's own initial poses matter now: mujoco_ros2_control loads
         this file and there is no reset hook to place them, so they have to
         start somewhere the arm can reach (base at {c.robot_base_xy}). -->
    <body name="object" pos="{c.object_start_xy[0]:.5f} {c.object_start_xy[1]:.5f} {c.object_size[2]:.5f}">
      <freejoint/>
      <geom name="object_geom" {_obj_geom(c)} mass="{c.object_mass}"
            friction="3 0.1 0.01" solref="{c.contact_solref}" solimp="{c.contact_solimp}"
            rgba="{' '.join(str(v) for v in c.object_rgba)}"/>
    </body>

    <body name="bin" pos="{c.bin_start_xy[0]:.5f} {c.bin_start_xy[1]:.5f} 0">
      <freejoint/>
      <inertial pos="0 0 {b:.5f}" mass="{c.bin_mass}"
                diaginertia="0.0012 0.0012 0.0016"/>
      <geom name="bin_floor" class="binwall" pos="0 0 {w:.5f}"
            size="{b:.5f} {b:.5f} {w:.5f}"/>
      <!-- the walls stand ON the floor slab (z from 2w up), so the slab is
           the only geom that meets the table. Reaching them down to z=0 put
           four more box faces in the same plane as the paper, flickering
           either side of contact. -->
      <geom name="bin_wall_yp" class="binwall" pos="0 {b-w:.5f} {b+w:.5f}"
            size="{b:.5f} {w:.5f} {b-w:.5f}"/>
      <geom name="bin_wall_ym" class="binwall" pos="0 {-(b-w):.5f} {b+w:.5f}"
            size="{b:.5f} {w:.5f} {b-w:.5f}"/>
      <geom name="bin_wall_xp" class="binwall" pos="{b-w:.5f} 0 {b+w:.5f}"
            size="{w:.5f} {b-2*w:.5f} {b-w:.5f}"/>
      <geom name="bin_wall_xm" class="binwall" pos="{-(b-w):.5f} 0 {b+w:.5f}"
            size="{w:.5f} {b-2*w:.5f} {b-w:.5f}"/>
      <!-- invisible volume used only by the success test -->
      <site name="bin_volume" pos="0 0 {b/2:.5f}" type="box"
            size="{b-c.bin_wall:.5f} {b-c.bin_wall:.5f} {b/2:.5f}"
            rgba="0 1 0 0"/>
{chr(10).join(markers)}
    </body>
  </worldbody>

  <contact>
{arm_contacts}
  </contact>

  <equality>
    <joint joint1="gripper_joint_2" joint2="gripper_joint_1"
           polycoef="0 1 0 0 0" solimp="0.95 0.99 0.001" solref="0.005 1"/>
  </equality>
{equality}
  <tendon>
    <!-- One motor drives both fingers through a gear, so ros2_control has to
         see ONE joint. mujoco_ros2_control's documented pattern for that is a
         tendon actuator plus an equality: the tendon is what is commanded and
         reported, the equality makes the second finger follow. The two hinges
         carry opposite axes and therefore couple with +1, where ROBOTIS's own
         model uses parallel axes and -1. Same mechanism, same jaw. -->
    <fixed name="jaw">
      <joint joint="gripper_joint_1" coef="0.5"/>
      <joint joint="gripper_joint_2" coef="0.5"/>
    </fixed>
  </tendon>

  <actuator>
{arm_actuators}
    <position name="gripper_joint_1" tendon="jaw" kp="{c.gripper_kp}"
              ctrlrange="{th0:.5f} {th1:.5f}"
              forcerange="{-c.gripper_force_limit} {c.gripper_force_limit}"/>
  </actuator>
</mujoco>
"""


def write_scene(cfg: Optional[SceneConfig] = None,
                path: Optional[pathlib.Path] = None) -> pathlib.Path:
    cfg = cfg or SceneConfig()
    path = pathlib.Path(path or (pathlib.Path(__file__).resolve().parents[1]
                                 / "mjcf" / "collector_scene.xml"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(build_xml(cfg))
    return path
