package com.ssafy.s15p21a206.tiger.capture

import android.hardware.camera2.CameraCharacteristics
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class RealtimeTimestampSourceTest {
    @Test fun `a realtime source is accepted`() {
        assertTrue(isRealtimeTimestampSource(CameraCharacteristics.SENSOR_INFO_TIMESTAMP_SOURCE_REALTIME))
    }

    // UNKNOWN은 카메라 시각이 부팅 이후 경과 시간과 다른 시계에서 온다는 뜻이다.
    // IMU CSV와 같은 시간축에서 비교할 수 없으므로 수집을 시작해서는 안 된다.
    @Test fun `an unknown source is rejected`() {
        assertFalse(isRealtimeTimestampSource(CameraCharacteristics.SENSOR_INFO_TIMESTAMP_SOURCE_UNKNOWN))
    }

    // 기기가 특성 자체를 알려 주지 않는 경우다. 같은 시계라고 볼 근거가 없으므로 통과시키지 않는다.
    @Test fun `a missing source is rejected`() {
        assertFalse(isRealtimeTimestampSource(null))
    }
}
