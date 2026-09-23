package com.ssafy.s15p21a206.tiger.capture

import android.hardware.camera2.CameraManager
import android.opengl.GLES20
import android.util.Log
import android.view.Surface
import com.google.ar.core.Camera
import com.google.ar.core.Session
import com.google.ar.core.TrackingState
import com.ssafy.s15p21a206.tiger.episode.CameraMetadata
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import java.io.File

/**
 * ARCore 프레임을 제 스레드에서 돌리며 pose를 적고 프리뷰를 그린다.
 *
 * 한 스레드가 둘을 다 하는 것은 `session.update()`가 프레임을 한 번만 내어 주기 때문이다. 그리기와
 * 기록을 갈라 두 스레드에서 각자 update를 부르면 서로 프레임을 빼앗는다.
 */
class ArPoseCollector(
    private val cameraManager: CameraManager,
) {
    private val trackingState = MutableStateFlow(TrackingSample(false, 0L))

    /**
     * 최신 ARCore Tracking 관측값. pose 수집 스레드가 갱신하고 수집 화면이 주기적으로 읽는다.
     *
     * 카메라 시각을 함께 실어 보내므로, 유실 구간의 기록용 시작 시각을 `arcore_poses.csv`와
     * 같은 값으로 맞출 수 있다.
     */
    val tracking: StateFlow<TrackingSample> = trackingState.asStateFlow()

    /** 첫 유효 프레임에서 확보한 촬영 Camera의 Intrinsic. 확보 전과 정리 후에는 null이다. */
    @Volatile var cameraMetadata: CameraMetadata? = null
        private set

    @Volatile private var running = false
    private var thread: Thread? = null

    /** 기록 대상. [stop] 이후 남은 스레드가 사라진 세션에 쓰지 않도록 비운다. */
    @Volatile private var poses: File? = null
    private var lastPoseTimestampNs = Long.MIN_VALUE

    /** 마지막 `TRACKING` 이후 처음 유실된 pose의 카메라 시각. 회복하면 비운다. */
    private var lossStartedAtNs: Long? = null

    /** CSV 헤더를 적고 기록 대상을 잡는다. 수집을 시작하기 전에 부른다. */
    fun open(poses: File) {
        poses.writeText("android_camera_timestamp_ns,tx,ty,tz,qx,qy,qz,qw,tracking_state,tracking_failure_reason\n")
        this.poses = poses
    }

    fun start(
        session: Session,
        previewSurface: Surface?,
    ) {
        running = true
        lossStartedAtNs = null
        lastPoseTimestampNs = Long.MIN_VALUE
        thread =
            Thread {
                val egl = CaptureEgl(previewSurface)
                try {
                    egl.makeCurrent()
                    val renderer = if (egl.hasWindow) CameraTextureRenderer() else null
                    val textureId = renderer?.createTexture() ?: IntArray(1).also { GLES20.glGenTextures(1, it, 0) }[0]
                    session.setCameraTextureName(textureId)
                    // 표시 회전을 Sensor 방향과 같게 준다. ARCore는 (Sensor 방향 - 표시 회전)만큼 이미지를
                    // 돌리므로, 두 값이 같으면 회전이 0이 되어 녹화본과 같은 방향의 프레임이 그려진다.
                    //
                    // 크기도 Camera 텍스처 그대로 가로로 준다. 녹화본과 같은 비율이라 ARCore가
                    // 잘라내지 않고, 프리뷰와 저장물의 화각이 일치한다.
                    val textureSize = session.cameraConfig.textureSize
                    if (renderer != null) {
                        session.setDisplayGeometry(SENSOR_DISPLAY_ROTATION, textureSize.width, textureSize.height)
                    }
                    while (running) {
                        // Tracking 유실·회복 구간에서 한 번 실패한다고 프리뷰와 pose 수집이 통째로
                        // 멈추면 안 된다. 실패를 남기고 다음 프레임으로 넘어간다.
                        val frame =
                            runCatching { session.update() }
                                .onFailure {
                                    Log.w(CAPTURE_LOG_TAG, "Could not update the ARCore frame", it)
                                    Thread.sleep(FRAME_RETRY_DELAY_MS)
                                }.getOrNull() ?: continue
                        if (renderer != null) {
                            // 타임스탬프 중복으로 걸러지는 프레임도 화면에는 그려야 프리뷰가 끊기지 않는다.
                            runCatching {
                                renderer.draw(frame, textureId, textureSize.width, textureSize.height)
                                // swapBuffers는 예외 대신 false를 돌려주므로, 조용히 정지하지 않게 확인한다.
                                check(egl.swapBuffers()) { "eglSwapBuffers rejected the preview surface" }
                            }.onFailure { Log.w(CAPTURE_LOG_TAG, "Could not draw the capture preview", it) }
                        }
                        val timestampNs = frame.androidCameraTimestamp
                        if (timestampNs == 0L || timestampNs == lastPoseTimestampNs) continue
                        lastPoseTimestampNs = timestampNs
                        val camera = frame.camera
                        val isTracking = camera.trackingState == TrackingState.TRACKING
                        // 유실 구간에서는 첫 유실 pose 시각을 계속 실어 보낸다. 화면 ticker는 100 ms
                        // 주기로 읽으므로, 매 프레임 최신 시각을 덮어쓰면 그사이 진행한 pose 시각이
                        // 기록에 들어가 `end_timestamp_ns`가 첫 유실 + 0.5초보다 늦어진다.
                        lossStartedAtNs = if (isTracking) null else lossStartedAtNs ?: timestampNs
                        trackingState.value = TrackingSample(isTracking, lossStartedAtNs ?: timestampNs)
                        if (cameraMetadata == null) {
                            // 회전하지 않는다. 녹화본이 회전 전 가로 프레임 그대로이고,
                            // `arcore_poses.csv`의 Camera 좌표계도 같은 기준이다.
                            cameraMetadata = readCameraMetadata(session, camera)
                        }
                        val translation = camera.pose.translation
                        val rotation = camera.pose.rotationQuaternion
                        poses?.appendText(
                            "$timestampNs,${translation[0]},${translation[1]},${translation[2]},${rotation[0]},${rotation[1]},${rotation[2]},${rotation[3]},${camera.trackingState.name},${camera.trackingFailureReason}\n",
                        )
                    }
                } catch (error: Throwable) {
                    // 여기서 끝나면 프리뷰와 pose 기록이 함께 멈춘다. 원인을 반드시 남긴다.
                    Log.e(CAPTURE_LOG_TAG, "Pose collection stopped unexpectedly", error)
                    throw error
                } finally {
                    egl.close()
                }
            }.apply {
                name = "TigerArPose"
                start()
            }
    }

    /**
     * 수집 스레드를 멈추고 기다린다.
     *
     * ARCore Session을 닫기 전에 불러야 한다. 스레드가 `session.update()` 안에 있는 동안 Session이
     * 닫히면 native 쪽에서 죽는다.
     */
    fun stop() {
        running = false
        thread?.join(JOIN_TIMEOUT_MS)
        thread = null
        poses = null
        cameraMetadata = null
    }

    /**
     * 첫 유효 프레임에서 촬영 Camera의 Intrinsic을 1회 확보한다.
     *
     * ARCore의 GPU 텍스처 스트림 기준 값이며, MediaRecorder 해상도를 같은 `cameraConfig.textureSize`로
     * 설정하므로 녹화 해상도와 대응이 보장된다. 실패하면 null을 돌려주고 수집은 그대로 이어간다.
     */
    private fun readCameraMetadata(
        session: Session,
        camera: Camera,
    ): CameraMetadata? =
        runCatching {
            val intrinsics = camera.textureIntrinsics
            val focalLength = intrinsics.focalLength
            val principalPoint = intrinsics.principalPoint
            val dimensions = intrinsics.imageDimensions
            val optics = CameraMetadataReader(cameraManager).read(session.cameraConfig.cameraId)
            CameraMetadata(
                cameraId = session.cameraConfig.cameraId,
                imageWidth = dimensions[0],
                imageHeight = dimensions[1],
                fx = focalLength[0],
                fy = focalLength[1],
                cx = principalPoint[0],
                cy = principalPoint[1],
                focalLengthMm = optics.focalLengthMm,
                sensorWidthMm = optics.sensorWidthMm,
                sensorHeightMm = optics.sensorHeightMm,
                distortionCoefficients = optics.distortionCoefficients,
            )
        }.onFailure { Log.w(CAPTURE_LOG_TAG, "Could not read camera metadata", it) }.getOrNull()

    private companion object {
        /**
         * ARCore에 알리는 표시 회전. Sensor 방향과 같은 값을 주면 (Sensor 방향 - 표시 회전)이 0이
         * 되어 이미지를 돌리지 않는다. 센서가 내보내는 가로 프레임이 그대로 그려져 녹화본과 방향이
         * 같고, 표시 기하의 비율도 텍스처와 같으므로 ARCore가 잘라내지 않는다.
         *
         * 돌리게 하면 세로 모양이 된 이미지를 가로 표시 기하에 맞추느라 크게 잘라내고 확대해,
         * 비율이 어긋나고 화질이 떨어진다. 수집 화면을 가로로 고정해 두므로 값이 바뀌지 않는다.
         */
        const val SENSOR_DISPLAY_ROTATION = Surface.ROTATION_90

        /** ARCore frame 갱신이 실패했을 때 다음 시도까지 쉬는 시간. 실패가 이어져도 CPU를 태우지 않는다. */
        const val FRAME_RETRY_DELAY_MS = 20L

        /** 수집 스레드가 스스로 끝나기를 기다리는 한계. */
        const val JOIN_TIMEOUT_MS = 500L
    }
}

/**
 * ARCore Tracking 관측 한 건.
 *
 * [observedAtNs]는 이 관측을 만든 프레임의 카메라 시각이며 `arcore_poses.csv`의
 * `android_camera_timestamp_ns`와 같은 값이다.
 */
data class TrackingSample(
    val isTracking: Boolean,
    val observedAtNs: Long,
)
