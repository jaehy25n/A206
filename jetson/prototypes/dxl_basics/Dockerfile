# Our own container.  Four instructions, and every one of them is here for a
# reason we can state.
#
# What it deliberately does NOT contain: ROS 2, ros2_control, MoveIt, Gazebo,
# rviz, the vendor's packages.  Steps 1-7 open a serial port and write bytes to
# it; none of that stack participates.  Carrying several gigabytes of software
# we do not call is how "what is actually running?" became unanswerable in the
# first place.  When we later want a camera node or rviz, we add them on
# purpose, knowing what for.

FROM python:3.12-slim

# The only dependency.  pyserial wraps termios so we do not have to set baud
# rate and raw mode by hand -- everything ABOVE that, the packets themselves,
# we build ourselves in dxl_raw.py.
RUN pip install --no-cache-dir pyserial

# The code is mounted at run time, not copied in.  So editing a file on the
# host changes what runs on the next command, and the image never needs
# rebuilding.  An image that must be rebuilt to test a one-line change is an
# image you stop using.
WORKDIR /work

CMD ["bash"]
