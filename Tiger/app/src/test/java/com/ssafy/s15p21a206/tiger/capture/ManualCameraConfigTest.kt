package com.ssafy.s15p21a206.tiger.capture

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class ManualCameraConfigTest {
    /** 실기기(SM-G973N)에서 읽은 값. 범위를 바꿔 가며 다른 기기를 흉내 낸다. */
    private val galaxyS10 =
        ManualCameraCapabilities(
            cameraId = "0",
            manualSensor = true,
            aeOffSupported = true,
            afOffSupported = true,
            awbOffSupported = true,
            awbLockSupported = true,
            maxFocusDiopter = 10f,
            isoRange = 50..3200,
            exposureRangeNs = 85_000L..100_000_000L,
            maxFrameDurationNs = 142_857_142L,
        )

    private val fixedWhiteBalance =
        FixedWhiteBalance(
            redGain = 1.8f,
            greenEvenGain = 1f,
            greenOddGain = 1f,
            blueGain = 1.6f,
            transform = List(FixedWhiteBalance.TRANSFORM_SIZE) { 1 },
        )

    @Test
    fun `keeps the 30 fps frame duration when the device allows a longer one`() {
        assertEquals(ManualCameraConfig.TARGET_FRAME_DURATION_NS, galaxyS10.frameDurationNs())
    }

    @Test
    fun `falls back to the device limit when it cannot hold a 30 fps frame`() {
        val slow = galaxyS10.copy(maxFrameDurationNs = 20_000_000L)
        assertEquals(20_000_000L, slow.frameDurationNs())
    }

    @Test
    fun `clamps focus iso and exposure into the ranges the device reports`() {
        val coerced =
            galaxyS10.coerce(
                ManualCameraConfig(focusDistanceDiopter = 99f, iso = 10, exposureTimeNs = 1L),
            )
        assertEquals(10f, coerced.focusDistanceDiopter, 0f)
        assertEquals(50, coerced.iso)
        assertEquals(85_000L, coerced.exposureTimeNs)
    }

    /** 노출이 프레임 간격보다 길면 센서가 간격을 늘려 30 fps가 깨진다. */
    @Test
    fun `never lets the exposure outrun the frame duration`() {
        val coerced =
            galaxyS10.coerce(
                ManualCameraConfig(focusDistanceDiopter = 4f, iso = 100, exposureTimeNs = 100_000_000L),
            )
        assertEquals(ManualCameraConfig.TARGET_FRAME_DURATION_NS, coerced.exposureTimeNs)
        assertTrue(coerced.exposureFitsFrame)
    }

    @Test
    fun `offers only the shutter presets the device can actually reach`() {
        assertEquals(ShutterPreset.entries, galaxyS10.availableShutterPresets())
        // 1/500(2 ms)보다 느린 셔터만 되는 기기라면 그 preset은 고를 수 없다.
        val slowShutter = galaxyS10.copy(exposureRangeNs = 5_000_000L..100_000_000L)
        assertFalse(slowShutter.allows(ShutterPreset.ONE_FIVE_HUNDREDTH))
        assertTrue(slowShutter.allows(ShutterPreset.ONE_THIRTIETH))
    }

    /** 1/30은 프레임 간격과 정확히 같다. 경계를 넘는 것으로 세면 가장 흔한 preset이 사라진다. */
    @Test
    fun `treats a shutter equal to the frame duration as selectable`() {
        assertEquals(ManualCameraConfig.TARGET_FRAME_DURATION_NS, ShutterPreset.ONE_THIRTIETH.exposureTimeNs)
        assertTrue(galaxyS10.allows(ShutterPreset.ONE_THIRTIETH))
    }

    @Test
    fun `explains why a camera without manual sensor support cannot be driven by hand`() {
        assertNull(galaxyS10.unsupportedReason)
        assertNotNull(galaxyS10.copy(manualSensor = false).unsupportedReason)
        assertNotNull(galaxyS10.copy(aeOffSupported = false).unsupportedReason)
        assertNotNull(galaxyS10.copy(isoRange = null).unsupportedReason)
    }

    @Test
    fun `reports a fixed focus lens instead of pretending the slider works`() {
        assertTrue(galaxyS10.focusSupported)
        assertFalse(galaxyS10.copy(maxFocusDiopter = 0f).focusSupported)
    }

    /** gain을 걸 수 없는 기기에서 고정된 척하면, 색이 변하는 채로 변하지 않는다고 믿게 된다. */
    @Test
    fun `drops a fixed white balance the camera cannot apply`() {
        val requested =
            ManualCameraConfig(focusDistanceDiopter = 4f, iso = 100, exposureTimeNs = 8_333_333L, whiteBalance = fixedWhiteBalance)
        assertTrue(galaxyS10.coerce(requested).awbFixed)
        assertFalse(galaxyS10.copy(awbOffSupported = false).coerce(requested).awbFixed)
    }

    @Test
    fun `starts from a default that already sits inside the device ranges`() {
        val default = galaxyS10.defaultConfig()
        assertEquals(default, galaxyS10.coerce(default))
        assertTrue(default.exposureFitsFrame)
        assertTrue(default.iso in 50..3200)
    }

    @Test
    fun `refuses a colour correction transform that is not nine rationals`() {
        val error =
            runCatching {
                FixedWhiteBalance(redGain = 1f, greenEvenGain = 1f, greenOddGain = 1f, blueGain = 1f, transform = listOf(1, 1))
            }.exceptionOrNull()
        assertNotNull(error)
    }
}
