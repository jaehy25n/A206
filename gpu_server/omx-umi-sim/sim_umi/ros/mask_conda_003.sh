#!/bin/bash
# Hide the conda-installed mujoco_ros2_control 0.0.3 so the 0.1.2 overlay is the
# only one found. Nothing is deleted -- everything is renamed .disabled.
#
#   ./mask_conda_003.sh hide     -> the overlay (0.1.2, with CameraPlugin) is used
#   ./mask_conda_003.sh restore  -> back to the conda 0.0.3, the rollback
#
# The msgs libraries have to be hidden too: the overlay's libraries carry a
# DT_RPATH that lists the conda lib directory, and RPATH is searched BEFORE
# LD_LIBRARY_PATH, so the 0.0.3 msgs would win and the node would die on an
# undefined SetFreeJointState symbol.
E=/home/j-j15a206/.conda/envs/omx_ros
IDX=$E/share/ament_index/resource_index
FILES="
$IDX/hardware_interface__pluginlib__plugin/mujoco_ros2_control
$IDX/mujoco_ros2_control_plugins__pluginlib__plugin/mujoco_ros2_control_plugins
$IDX/packages/mujoco_ros2_control
$IDX/packages/mujoco_ros2_control_plugins
"
LIBS=$(ls $E/lib/libmujoco_ros2_control*.so 2>/dev/null; ls $E/lib/libmujoco_ros2_control*.so.disabled 2>/dev/null | sed 's/.disabled$//')
case "$1" in
  hide)
    for f in $FILES $LIBS; do [ -e "$f" ] && mv "$f" "$f.disabled" && echo "hid  ${f##*/}"; done ;;
  restore)
    for f in $FILES $LIBS; do [ -e "$f.disabled" ] && mv "$f.disabled" "$f" && echo "back ${f##*/}"; done ;;
  *) echo "usage: $0 hide|restore"; exit 1 ;;
esac
