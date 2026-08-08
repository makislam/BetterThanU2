"""Thin wrapper around pyrealsense2 for the capture GUI: start a color-only
pipeline, poll the latest frame, and lock exposure/white-balance so colors
stay consistent between the two capture slots (auto-exposure/auto-WB would
otherwise shift colors frame to frame and corrupt the labeled dataset).
"""

import numpy as np
import pyrealsense2 as rs


class Camera:
    def __init__(self, width, height, fps):
        self.pipeline = rs.pipeline()
        config = rs.config()
        config.enable_stream(rs.stream.color, width, height, rs.format.bgr8, fps)
        self.profile = self.pipeline.start(config)
        self.color_sensor = self._find_color_sensor(self.profile.get_device())
        self.locked = False

    @staticmethod
    def _find_color_sensor(device):
        """Some RealSense models (e.g. D405) have no dedicated RGB sensor
        — color comes off the same Stereo Module as depth/infra, so
        `device.first_color_sensor()` fails. Find whichever sensor exposes
        color-relevant controls (white balance) instead of assuming a
        separate color sensor exists.
        """
        for sensor in device.query_sensors():
            if sensor.supports(rs.option.white_balance):
                return sensor
        raise RuntimeError("No sensor with white-balance control found on this device.")

    def latest_frame(self):
        """Return the most recent color frame as a BGR numpy array, or None
        if none is available yet (non-blocking)."""
        frames = self.pipeline.poll_for_frames()
        if not frames:
            return None
        color_frame = frames.get_color_frame()
        if not color_frame:
            return None
        return np.asanyarray(color_frame.get_data())

    def lock_exposure_and_white_balance(self):
        """Read the sensor's current (auto-converged) exposure/white-balance
        values, then pin them by disabling auto mode. Call this once the
        auto values have settled (after the viewfinder's been running a
        moment), before capturing either slot.
        """
        exposure = self.color_sensor.get_option(rs.option.exposure)
        white_balance = self.color_sensor.get_option(rs.option.white_balance)

        self.color_sensor.set_option(rs.option.enable_auto_exposure, 0)
        self.color_sensor.set_option(rs.option.exposure, exposure)
        self.color_sensor.set_option(rs.option.enable_auto_white_balance, 0)
        self.color_sensor.set_option(rs.option.white_balance, white_balance)

        self.locked = True
        return exposure, white_balance

    def unlock_exposure_and_white_balance(self):
        self.color_sensor.set_option(rs.option.enable_auto_exposure, 1)
        self.color_sensor.set_option(rs.option.enable_auto_white_balance, 1)
        self.locked = False

    def stop(self):
        self.pipeline.stop()
