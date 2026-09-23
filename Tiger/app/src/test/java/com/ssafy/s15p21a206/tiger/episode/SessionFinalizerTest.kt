package com.ssafy.s15p21a206.tiger.episode

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.floatOrNull
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File

class SessionFinalizerTest {
    @get:Rule val folder = TemporaryFolder()

    private val intrinsicsOnly =
        CameraMetadata(cameraId = "0", imageWidth = 640, imageHeight = 480, fx = 501.2f, fy = 501.1f, cx = 319.8f, cy = 239.5f)

    private fun bundle(): Pair<SessionBundle, SessionBundleStore> {
        val store = SessionBundleStore(folder.newFolder("capture"))
        val bundle = store.createStagingBundle(1)
        bundle.mainVideo.writeText("video")
        bundle.mainFrameTimestamps.writeText("frame_number,timestamp_ns,timestamp_source\n0,1,SENSOR_TIMESTAMP\n")
        bundle.accelerometer.writeText("timestamp_ns,x,y,z,accuracy\n")
        bundle.gyroscope.writeText("timestamp_ns,x,y,z,accuracy\n")
        bundle.rotationVector.writeText("timestamp_ns,x,y,z,scalar_component,heading_accuracy_rad,accuracy\n")
        bundle.arcorePoses.writeText("android_camera_timestamp_ns,tx,ty,tz,qx,qy,qz,qw,tracking_state,tracking_failure_reason\n")
        bundle.episodes.writeText("episode_id,start_timestamp_ns,end_timestamp_ns,task,object,outcome\n")
        return bundle to store
    }

    private fun metadataOf(directory: File) = Json.parseToJsonElement(File(directory, SessionBundle.METADATA_FILE).readText()).jsonObject

    @Test fun `camera intrinsics are written under the camera key`() {
        val (bundle, store) = bundle()
        val result = SessionFinalizer(store).finalize(bundle, camera = intrinsicsOnly) as FinalizeResult.Completed
        val camera = metadataOf(result.directory)["camera"]!!.jsonObject
        assertEquals("0", camera["camera_id"]!!.jsonPrimitive.content)
        assertEquals(640, camera["image_width"]!!.jsonPrimitive.content.toInt())
        assertEquals(480, camera["image_height"]!!.jsonPrimitive.content.toInt())
        assertEquals(501.2f, camera["fx"]!!.jsonPrimitive.floatOrNull!!, 0.001f)
        assertEquals(319.8f, camera["cx"]!!.jsonPrimitive.floatOrNull!!, 0.001f)
    }

    @Test fun `optional optics are omitted when the device does not provide them`() {
        val (bundle, store) = bundle()
        val result = SessionFinalizer(store).finalize(bundle, camera = intrinsicsOnly) as FinalizeResult.Completed
        val camera = metadataOf(result.directory)["camera"]!!.jsonObject
        listOf("focal_length_mm", "sensor_width_mm", "sensor_height_mm", "distortion_coefficients").forEach { key ->
            assertFalse(key, camera.containsKey(key))
        }
    }

    @Test fun `optional optics are written when available`() {
        val (bundle, store) = bundle()
        val camera =
            intrinsicsOnly.copy(focalLengthMm = 4.32f, sensorWidthMm = 5.645f, distortionCoefficients = listOf(0.1f, -0.2f))
        val result = SessionFinalizer(store).finalize(bundle, camera = camera) as FinalizeResult.Completed
        val written = metadataOf(result.directory)["camera"]!!.jsonObject
        assertEquals(4.32f, written["focal_length_mm"]!!.jsonPrimitive.floatOrNull!!, 0.001f)
        assertEquals(2, written["distortion_coefficients"]!!.jsonArray.size)
        assertFalse("sensor_height_mm", written.containsKey("sensor_height_mm"))
    }

    // 메타데이터 확보 실패가 수집한 영상·IMU·Pose를 잃게 만들어서는 안 된다.
    @Test fun `session finalizes without camera metadata`() {
        val (bundle, store) = bundle()
        val result = SessionFinalizer(store).finalize(bundle)
        assertTrue(result is FinalizeResult.Completed)
        val metadata = metadataOf((result as FinalizeResult.Completed).directory)
        assertNull(metadata["camera"])
        assertNotNull(metadata["session_id"])
    }

    @Test fun `existing keys stay intact and the bundle still validates`() {
        val (bundle, store) = bundle()
        val result = SessionFinalizer(store).finalize(bundle, camera = intrinsicsOnly) as FinalizeResult.Completed
        val metadata = metadataOf(result.directory)
        assertEquals(bundle.sessionId, metadata["session_id"]!!.jsonPrimitive.content)
        assertTrue(
            metadata["camera_streams"]!!
                .jsonObject["main"]!!
                .jsonPrimitive.content
                .toBoolean(),
        )
        assertFalse(
            metadata["camera_streams"]!!
                .jsonObject["ultrawide"]!!
                .jsonPrimitive.content
                .toBoolean(),
        )
        assertTrue(metadata["files"]!!.jsonArray.isNotEmpty())
        assertTrue(SessionBundleValidator.validate(result.directory).isValid)
    }

    private val manualSettings =
        CaptureSettingsMetadata(
            mode = "manual",
            requested =
                RequestedCaptureSettings(
                    focusDistanceDiopter = 4f,
                    iso = 100,
                    exposureTimeNs = 8_333_333L,
                    frameDurationNs = 33_333_333L,
                ),
            actual =
                ActualCaptureSettings(
                    focusDistanceDiopter = 3.9916728f,
                    iso = 100,
                    exposureTimeNs = 8_333_000L,
                    frameDurationNs = 33_333_000L,
                    afMode = "OFF",
                    aeMode = "OFF",
                    awbMode = "OFF",
                ),
            awbFixed = true,
        )

    /**
     * 요청값과 실제값을 나눠 적는다.
     *
     * `CaptureRequest`에 넣었다고 센서가 그 값을 썼다고 볼 수 없다. 둘을 한 칸에 합쳐 적으면
     * 나중에 어느 쪽을 보고 있는지 알 수 없고, calibration은 실제로 쓰인 값 위에서만 뜻이 있다.
     */
    @Test fun `capture settings keep the request and what the sensor used apart`() {
        val (bundle, store) = bundle()
        val result =
            SessionFinalizer(store).finalize(bundle, camera = intrinsicsOnly, captureSettings = manualSettings)
                as FinalizeResult.Completed

        val capture = metadataOf(result.directory)["capture_settings"]!!.jsonObject
        assertEquals("manual", capture["mode"]!!.jsonPrimitive.content)
        assertTrue(capture["awb_fixed"]!!.jsonPrimitive.content.toBoolean())

        val requested = capture["requested"]!!.jsonObject
        assertEquals(4f, requested["focus_distance_diopter"]!!.jsonPrimitive.floatOrNull!!, 0.001f)
        assertEquals(100, requested["iso"]!!.jsonPrimitive.content.toInt())
        assertEquals(8_333_333L, requested["exposure_time_ns"]!!.jsonPrimitive.content.toLong())
        assertEquals(33_333_333L, requested["frame_duration_ns"]!!.jsonPrimitive.content.toLong())
        assertEquals(30, requested["fps_target"]!!.jsonPrimitive.content.toInt())

        val actual = capture["actual"]!!.jsonObject
        assertEquals(3.9916728f, actual["focus_distance_diopter"]!!.jsonPrimitive.floatOrNull!!, 0.001f)
        assertEquals(8_333_000L, actual["exposure_time_ns"]!!.jsonPrimitive.content.toLong())
        assertEquals("OFF", actual["ae_mode"]!!.jsonPrimitive.content)
        assertEquals("OFF", actual["awb_mode"]!!.jsonPrimitive.content)
    }

    /** 읽지 못한 값은 지어내지 않는다. 없는 것은 없는 대로 남아야 나중에 읽는 쪽이 속지 않는다. */
    @Test fun `capture settings omit the values the camera never reported`() {
        val (bundle, store) = bundle()
        val partial = manualSettings.copy(actual = ActualCaptureSettings(iso = 100), awbFixed = false)
        val result =
            SessionFinalizer(store).finalize(bundle, camera = intrinsicsOnly, captureSettings = partial)
                as FinalizeResult.Completed

        val capture = metadataOf(result.directory)["capture_settings"]!!.jsonObject
        // 고정하지 않았다는 것도 사실이다. 기본값과 같다는 이유로 빠지면 안 된다.
        assertFalse(capture["awb_fixed"]!!.jsonPrimitive.content.toBoolean())
        val actual = capture["actual"]!!.jsonObject
        assertEquals(100, actual["iso"]!!.jsonPrimitive.content.toInt())
        listOf("focus_distance_diopter", "exposure_time_ns", "frame_duration_ns", "af_mode", "ae_mode", "awb_mode")
            .forEach { key -> assertFalse(key, actual.containsKey(key)) }
    }

    /**
     * 수동 설정을 쓰지 않은 Session에는 항목 자체가 없다.
     *
     * 기본값을 채워 적으면 자동으로 찍은 Session이 수동으로 찍힌 것처럼 읽힌다.
     */
    @Test fun `a session recorded without manual settings carries no capture settings`() {
        val (bundle, store) = bundle()
        val result = SessionFinalizer(store).finalize(bundle, camera = intrinsicsOnly) as FinalizeResult.Completed
        val metadata = metadataOf(result.directory)

        assertFalse(metadata.containsKey("capture_settings"))
        // 기존 항목은 그대로 남는다. 새 항목 추가가 예전 Session의 모양을 바꾸지 않는다.
        assertNotNull(metadata["camera"])
        assertNotNull(metadata["session_id"])
        assertTrue(metadata["files"]!!.jsonArray.isNotEmpty())
    }
}
