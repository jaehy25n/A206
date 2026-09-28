# The camera comes from the plant, not from a copy of it

`mujoco_ros2_control` 0.0.3, the version RoboStack ships, has no camera plugin.
Without one the policy's picture had to be rendered from a second MuJoCo model
posed from `/joint_states` -- which meant the ball in that picture never moved,
because nothing in `/joint_states` says where a free body is. Fine for a single
cycle. Useless for a rollout.

Upstream 0.1.2 has `CameraPlugin`, and it renders from the same `mjModel` and
`mjData` the controllers act on.

## What was done

    ~/omx_overlay/            colcon workspace, ros-controls/mujoco_ros2_control
                              at 58f465b (2026-09-15), built against the conda
                              ROS. See PROVENANCE.txt.
    ros/env_overlay.sh        sources the conda env, then the overlay, so 0.1.2
                              wins
    ros/mask_conda_003.sh     hide | restore -- renames the conda 0.0.3 ament
                              entries and libraries out of the way
    ros/config/mujoco_plugins.yaml   CameraPlugin on the MJCF's `wrist` camera,
                              plus FreeJointStatePublisher for the ball's pose
                              (verification only; the policy never reads it)

The conda 0.0.3 install is untouched. `mask_conda_003.sh restore` puts it back
and the overlay is simply not sourced: that is the rollback.

Two things had to be hidden, not one. The ament index entries, so the plugin
scanner does not load the old plugin library into the new node; and the 0.0.3
message libraries, because the overlay's libraries carry a `DT_RPATH` that
lists the conda lib directory and RPATH is searched *before* LD_LIBRARY_PATH --
the node died on an undefined `SetFreeJointState` symbol until those moved.

## Verified

    image (180, 320, 3) rgb8 on /wrist_camera/image_raw, EGL headless

    1  the arm moves, the image follows     15.00 levels/px, joints within 0.59 deg
    2  grasp and lift                       ball rose +117.3 mm, pixels 122 -> 541 -> 526
    3  release                              25 frames in 1.2 s:
                                            141.6 -> 125.1 -> 82.0 -> 18.5 -> 24.8 mm
                                            pixels 526 -> 388 -> 0

Test 3 "failed" once before this, with the ball already at rest in the first
sample. The camera was fine; the test waited for the gripper action to finish,
and a released ball falls 117 mm in about 0.15 s.
