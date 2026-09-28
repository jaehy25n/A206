"""Build the robot_description that ros2_control and MoveIt will use.

    python sim_umi/ros/make_urdf.py

ROBOTIS's omx_f.urdf is taken as-is for links, joints, limits and meshes --
it is the description their SRDF, joint_limits.yaml and moveit_controllers.yaml
are written against. Two things are added and nothing is redesigned:

  * package:// mesh paths are rewritten to file:// absolute paths, because the
    ROS package they name is not installed here (we vendored the meshes).
  * a <ros2_control> block naming mujoco_ros2_control/MujocoSystemInterface,
    pointing at OUR MJCF -- the one with the official arm and the custom pivot
    gripper. Joint names already match on both sides (joint1..joint5,
    gripper_joint_1/2); the gripper is exposed as the single joint the tendon
    drives, which is what the real hardware is: one Dynamixel, two fingers.
"""
import pathlib
import re

SIM = pathlib.Path(__file__).resolve().parent.parent
SRC = SIM / "ros" / "description" / "omx_f.urdf"
OUT = SIM / "ros" / "description" / "omx_f_mujoco.urdf"
MESHES = SIM / "assets" / "omx_official" / "assets"
MJCF = SIM / "mjcf" / "collector_scene.xml"

ARM = [f"joint{i}" for i in range(1, 6)]

BLOCK = """
  <ros2_control name="MujocoSystem" type="system">
    <hardware>
      <plugin>mujoco_ros2_control/MujocoSystemInterface</plugin>
      <param name="mujoco_model">{mjcf}</param>
      <param name="headless">true</param>
      <param name="sim_speed_factor">1.0</param>
    </hardware>
{joints}  </ros2_control>
"""

JOINT = """    <joint name="{name}">
      <command_interface name="position"/>
      <state_interface name="position">
        <param name="initial_value">0.0</param>
      </state_interface>
      <state_interface name="velocity"/>
      <state_interface name="effort"/>
    </joint>
"""


def main():
    urdf = SRC.read_text()
    urdf = re.sub(r'package://open_manipulator_description/meshes/omx_f/',
                  f'file://{MESHES}/', urdf)
    joints = "".join(JOINT.format(name=n) for n in ARM + ["gripper_joint_1"])
    block = BLOCK.format(mjcf=MJCF, joints=joints)
    urdf = urdf.replace("</robot>", block + "</robot>")
    OUT.write_text(urdf)
    missing = [m for m in re.findall(r'file://([^"]+)', urdf)
               if not pathlib.Path(m).is_file()]
    print(f"-> {OUT}")
    print(f"   meshes referenced: {len(re.findall(r'file://', urdf))}, "
          f"missing: {len(missing)}")
    for m in missing[:5]:
        print("   MISSING", m)


if __name__ == "__main__":
    main()
