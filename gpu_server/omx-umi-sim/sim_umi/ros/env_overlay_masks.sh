# The mask-capable evaluator's environment: the normal overlay, then the separately built
# camera plugin that adds the free joints to the joint snapshot (~/omx_overlay_masks, only
# mujoco_ros2_control_plugins; it comes first on AMENT_PREFIX_PATH and so wins).
source /home/j-j15a206/universal_manipulation_interface/sim_umi/ros/env_overlay.sh
source /home/j-j15a206/omx_overlay_masks/install/local_setup.bash
