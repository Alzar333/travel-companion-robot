"""
GPS Module — Alzar Robot Companion
Reads NMEA sentences from BU-353N5 (or similar) via serial,
parses with pynmea2, and keeps robot_state["gps"] current.
"""

import threading
import time
import serial
import pynmea2

GPS_PORT    = "/dev/ttyUSB0"
GPS_BAUD    = 4800
GPS_TIMEOUT = 2   # seconds per readline


class GPSReader:
    def __init__(self, robot_state: dict, socketio=None, port=GPS_PORT, baud=GPS_BAUD):
        self.robot_state = robot_state
        self.socketio    = socketio
        self.port        = port
        self.baud        = baud
        self.running     = False
        self.has_fix     = False
        self._thread     = None

    def start(self):
        self.running = True
        self._thread = threading.Thread(target=self._loop, daemon=True, name="gps-reader")
        self._thread.start()
        print(f"📡 GPS reader started on {self.port} @ {self.baud} baud")

    def stop(self):
        self.running = False

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _loop(self):
        while self.running:
            try:
                with serial.Serial(self.port, self.baud, timeout=GPS_TIMEOUT) as ser:
                    print(f"📡 GPS port open: {self.port}")
                    while self.running:
                        raw = ser.readline().decode("ascii", errors="ignore").strip()
                        if not raw:
                            continue
                        self._parse(raw)
            except serial.SerialException as e:
                print(f"⚠️  GPS serial error: {e} — retrying in 5s")
                time.sleep(5)
            except Exception as e:
                print(f"⚠️  GPS unexpected error: {e} — retrying in 5s")
                time.sleep(5)

    def _parse(self, raw: str):
        """Parse a single NMEA sentence and update robot_state if we have a fix."""
        try:
            msg = pynmea2.parse(raw)
        except pynmea2.ParseError:
            return

        # GGA — position + fix quality
        if isinstance(msg, pynmea2.GGA):
            quality = int(msg.gps_qual or 0)
            if quality > 0 and msg.latitude and msg.longitude:
                had_fix = self.has_fix
                self.has_fix = True
                self.robot_state["gps"] = {
                    "lat":      msg.latitude,
                    "lng":      msg.longitude,
                    "accuracy": self._hdop_to_metres(msg.horizontal_dil),
                    "alt":      float(msg.altitude or 0),
                    "fix":      quality,
                    "sats":     int(msg.num_sats or 0),
                }
                self._broadcast()
                if not had_fix:
                    print(f"✅ GPS fix acquired: {msg.latitude:.6f}, {msg.longitude:.6f}")
            else:
                if self.has_fix:
                    print("⚠️  GPS fix lost")
                self.has_fix = False
                # Update sats count even without fix
                self.robot_state["gps"]["fix"] = 0
                self.robot_state["gps"]["sats"] = int(msg.num_sats or 0)

    @staticmethod
    def _hdop_to_metres(hdop_str) -> float:
        """Rough accuracy estimate: HDOP × 5m (CEP ~5m per HDOP unit)."""
        try:
            return round(float(hdop_str) * 5.0, 1)
        except (TypeError, ValueError):
            return 0.0

    def _broadcast(self):
        """Push state_update to all connected WebSocket clients."""
        if self.socketio:
            self.socketio.emit("state_update", self.robot_state)
