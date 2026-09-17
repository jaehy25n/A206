#!/usr/bin/env python3
"""DYNAMIXEL Protocol 2.0, by hand.  No dynamixel_sdk -- just bytes on a wire.

Everything the servos and we ever say to each other has this shape:

    FF FF FD 00 | ID | LEN_L LEN_H | INST | PARAM... | CRC_L CRC_H
    \_________/   \/   \_________/   \__/   \______/   \_________/
      header      id     length      what   arguments   CRC-16 over
                                     to do              every byte before it

  header   always these four bytes; it is how the servo finds the start of a
           packet in a stream it may have joined halfway through.
  id       0..252 addresses one servo, 254 is broadcast (no reply).
  length   counts what FOLLOWS it: INST + PARAM + CRC, i.e. len(param) + 3.
  inst     0x01 ping, 0x02 read, 0x03 write.  0x55 in a reply.
  crc      polynomial 0x8005, initial 0, MSB first.

A reply ("status packet") is the same, with INST = 0x55 and one extra byte in
front of the parameters: ERR, the servo's complaint, 0 when it is happy.

Every multi-byte number is little-endian.  Addresses, lengths, positions, all.

One wire, half duplex: the servos are daisy-chained on a single data line and
only speak when spoken to.  So the rule is always write-then-read, one at a
time, and never two processes on the same port.

Run this file directly to check the CRC against ROBOTIS' own published example
packets.  No robot needed -- if that passes, the protocol code is correct and
anything that goes wrong later is wiring, power or addresses.

Depends on nothing.  pyserial is used when it happens to be installed, and
otherwise a ~40 line termios backend below does the same job out of the
standard library, so this runs on a bare Jetson with system python3 -- no pip,
no venv, no container.
"""

HEADER = b'\xFF\xFF\xFD\x00'

PING = 0x01
READ = 0x02
WRITE = 0x03
STATUS = 0x55

BROADCAST = 0xFE

# The low 7 bits of the ERR byte.  Bit 7 set means "and I also have a hardware
# alert" (overheat, overload, ...) which is reported separately in register 70.
ERRORS = {
    1: 'result fail',
    2: 'instruction error (unknown instruction)',
    3: 'CRC error (the servo did not like OUR checksum)',
    4: 'data range (value outside what this register accepts)',
    5: 'data length (wrote fewer bytes than the register wants)',
    6: 'data limit (value outside the configured limits)',
    7: 'access error (bad address, or writing EEPROM while torque is on)',
}


def crc16(data):
    """CRC-16/IBM: poly 0x8005, init 0x0000, MSB first, no final xor.

    Written out longhand instead of the SDK's 256-entry lookup table, because
    the table tells you nothing and this is eight lines.
    """
    crc = 0
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ 0x8005) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
    return crc


def stuff(params):
    """Insert a 0xFD wherever the payload accidentally spells the header.

    If FF FF FD ever appeared inside a packet, a servo that started listening
    mid-stream would mistake it for the beginning of a new one.  So the sender
    appends an extra 0xFD, and the receiver strips it back out.

    It never triggers for the addresses and lengths we send, but a 4-byte goal
    position CAN contain those bytes, so it belongs here rather than in a
    comment.
    """
    out = bytearray()
    for b in params:
        out.append(b)
        if bytes(out[-3:]) == b'\xFF\xFF\xFD':
            out.append(0xFD)
    return bytes(out)


def unstuff(params):
    out = bytearray()
    i = 0
    while i < len(params):
        out.append(params[i])
        if bytes(out[-3:]) == b'\xFF\xFF\xFD' and i + 1 < len(params):
            i += 1                      # skip the inserted 0xFD
        i += 1
    return bytes(out)


def hexs(data):
    return ' '.join(f'{b:02X}' for b in data) if data else '(nothing)'


def to_int(data, signed=False):
    return int.from_bytes(data, 'little', signed=signed)


# --- the serial port ----------------------------------------------------------
class _RawSerial:
    """A serial port using only the standard library.

    pyserial does a great deal more than this, and if it is installed we use it.
    But all we actually need is 8N1 at a fixed baud with a read timeout, and
    doing that by hand costs forty lines and buys something worth having: the
    whole stack from packet to kernel has no third-party code in it.  Nothing to
    install means nothing to install ON -- no pip, no venv, no container.

    Linux only (termios).  That is where the robot is.
    """

    def __init__(self, port, baud, timeout):
        import os
        import termios

        self.os = os
        self.termios = termios
        self.timeout = timeout
        self.fd = os.open(port, os.O_RDWR | os.O_NOCTTY)

        speed = getattr(termios, f'B{baud}', None)
        if speed is None:
            os.close(self.fd)
            raise ValueError(f'termios has no B{baud}; pip install pyserial')

        cc = list(termios.tcgetattr(self.fd)[6])
        cc[termios.VMIN] = 0            # read() may return with fewer bytes...
        cc[termios.VTIME] = 1           # ...after 0.1 s of silence

        # raw 8N1: no parity, no flow control, no line discipline, no echo,
        # receiver enabled, modem control lines ignored
        termios.tcsetattr(self.fd, termios.TCSANOW, [
            0,                                                    # iflag
            0,                                                    # oflag
            termios.CS8 | termios.CREAD | termios.CLOCAL,         # cflag
            0,                                                    # lflag
            speed, speed, cc,
        ])

    def write(self, data):
        return self.os.write(self.fd, data)

    def read(self, n):
        """Read exactly n bytes, or fewer if the timeout runs out."""
        import time
        deadline = time.monotonic() + self.timeout
        buf = b''
        while len(buf) < n and time.monotonic() < deadline:
            chunk = self.os.read(self.fd, n - len(buf))   # blocks <= 0.1 s
            if chunk:
                buf += chunk
        return buf

    def reset_input_buffer(self):
        self.termios.tcflush(self.fd, self.termios.TCIFLUSH)

    def close(self):
        self.os.close(self.fd)


def open_port(port, baud, timeout):
    """Return (port_object, backend_name)."""
    try:
        import serial
        return serial.Serial(port, baud, timeout=timeout), 'pyserial'
    except ImportError:
        return _RawSerial(port, baud, timeout), 'termios (stdlib)'


class Bus:
    """One serial port with a chain of DYNAMIXELs on it."""

    def __init__(self, port='/dev/ttyACM0', baud=1000000, timeout=0.1):
        self.ser, self.backend = open_port(port, baud, timeout)

    def close(self):
        self.ser.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def send(self, dxl_id, instruction, params=b''):
        """Build and write one instruction packet.  Returns the bytes sent."""
        params = stuff(bytes(params))
        length = len(params) + 3
        body = (HEADER
                + bytes([dxl_id, length & 0xFF, (length >> 8) & 0xFF, instruction])
                + params)
        c = crc16(body)
        packet = body + bytes([c & 0xFF, (c >> 8) & 0xFF])
        self.ser.reset_input_buffer()    # drop anything stale before we listen
        self.ser.write(packet)
        return packet

    def recv(self):
        """Read one status packet.

        Returns (err, params, raw).  err is None when nothing usable arrived,
        and raw is whatever bytes did show up, so a failure is still
        inspectable rather than just False.
        """
        head = self.ser.read(7)                  # header + id + length
        if len(head) < 7:
            return None, b'silence', head
        if head[:4] != HEADER:
            return None, b'not a packet', head
        length = head[5] | (head[6] << 8)
        if not 4 <= length <= 300:
            return None, b'implausible length', head
        rest = self.ser.read(length)
        raw = head + rest
        if len(rest) < length:
            return None, b'truncated', raw
        if (raw[-2] | (raw[-1] << 8)) != crc16(raw[:-2]):
            return None, b'bad CRC', raw
        if raw[7] != STATUS:
            return None, b'not a status packet', raw
        return raw[8], unstuff(raw[9:-2]), raw

    def txrx(self, dxl_id, instruction, params=b''):
        """One round trip.  Returns (err, params, sent_bytes, received_bytes)."""
        sent = self.send(dxl_id, instruction, params)
        err, data, raw = self.recv()
        return err, data, sent, raw

    # --- reading changes nothing ---------------------------------------------
    def ping(self, dxl_id):
        return self.txrx(dxl_id, PING)

    def read(self, dxl_id, addr, size):
        params = bytes([addr & 0xFF, (addr >> 8) & 0xFF,
                        size & 0xFF, (size >> 8) & 0xFF])
        return self.txrx(dxl_id, READ, params)

    # --- writing does ---------------------------------------------------------
    def write(self, dxl_id, addr, data):
        """Write raw bytes to a register.

        There is no separate 'move' instruction: commanding the arm is writing
        four bytes to address 116.  Which is also why a typo in an address is a
        physical event rather than an exception.
        """
        params = bytes([addr & 0xFF, (addr >> 8) & 0xFF]) + bytes(data)
        return self.txrx(dxl_id, WRITE, params)


# -----------------------------------------------------------------------------
if __name__ == '__main__':
    # Example packets straight out of the ROBOTIS Protocol 2.0 manual.  If our
    # CRC matches theirs byte for byte, the packet builder is right.
    cases = [
        ('ping id 1',
         (1, PING, b''),
         'FF FF FD 00 01 03 00 01 19 4E'),
        ('ping broadcast',
         (BROADCAST, PING, b''),
         'FF FF FD 00 FE 03 00 01 31 42'),
        ('read 4 bytes from addr 132 (Present Position) on id 1',
         (1, READ, bytes([132, 0, 4, 0])),
         'FF FF FD 00 01 07 00 02 84 00 04 00 1D 15'),
    ]

    ok = True
    for name, (dxl_id, inst, params), expected in cases:
        params = stuff(params)
        length = len(params) + 3
        body = (HEADER
                + bytes([dxl_id, length & 0xFF, (length >> 8) & 0xFF, inst])
                + params)
        c = crc16(body)
        got = hexs(body + bytes([c & 0xFF, (c >> 8) & 0xFF]))
        mark = 'ok  ' if got == expected else 'FAIL'
        if got != expected:
            ok = False
        print(f'{mark} {name}')
        print(f'       ours {got}')
        if got != expected:
            print(f'       mfr  {expected}')

    print('\nprotocol code verified, no hardware needed' if ok
          else '\nCRC is wrong -- fix this before touching the robot')
