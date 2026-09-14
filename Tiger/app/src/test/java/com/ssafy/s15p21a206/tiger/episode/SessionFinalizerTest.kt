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
}
