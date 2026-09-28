export ROS_ENV=/home/j-j15a206/.conda/envs/omx_ros
source $ROS_ENV/setup.bash 2>/dev/null || . $ROS_ENV/setup.sh
source /home/j-j15a206/omx_overlay/install/setup.bash     # 0.1.2 wins over the 0.0.3 install
export MUJOCO_GL=egl MUJOCO_EGL_DEVICE_ID=5
export ROS_DOMAIN_ID=77
