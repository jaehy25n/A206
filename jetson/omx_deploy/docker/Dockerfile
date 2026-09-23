# OMX-F control stack container.
# Multi-arch base: pulls arm64 on Jetson (JetPack 6 / Ubuntu 22.04) and amd64 on a PC.
# The workspace is bind-mounted at /ws; it is built INSIDE the container so the
# Jetson host stays untouched. The container user mirrors the host UID/GID so
# build artefacts and recordings on the bind mount belong to the host user.
FROM ros:humble-ros-base

ARG UID=1000
ARG GID=1000
ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
      sudo nano less usbutils iputils-ping \
      python3-colcon-common-extensions python3-rosdep python3-numpy python3-pip python3-serial \
      ros-humble-robot-state-publisher ros-humble-diagnostic-msgs ros-humble-std-srvs \
      ros-humble-usb-cam \
    && rm -rf /var/lib/apt/lists/*

# dialout (20) / video (44) match the host device groups -> /dev/ttyACM0 and /dev/video0 usable
RUN if ! getent group ${GID} >/dev/null; then groupadd -g ${GID} omx; fi \
    && useradd -m -u ${UID} -g ${GID} -G dialout,video,plugdev -s /bin/bash omx \
    && echo 'omx ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/omx

# ROS + workspace environment for every kind of shell (interactive, `bash -lc`, entrypoint)
RUN printf '%s\n' \
      'source /opt/ros/humble/setup.bash' \
      '[ -f /ws/install/setup.bash ] && source /ws/install/setup.bash' \
      'export RCUTILS_COLORIZED_OUTPUT=1' \
      > /etc/omx_env.sh \
    && echo 'source /etc/omx_env.sh' >> /home/omx/.bashrc \
    && ln -s /etc/omx_env.sh /etc/profile.d/omx_env.sh

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

USER omx
WORKDIR /ws
ENTRYPOINT ["/entrypoint.sh"]
CMD ["bash"]
