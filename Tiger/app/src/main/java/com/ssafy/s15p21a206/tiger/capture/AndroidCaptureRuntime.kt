package com.ssafy.s15p21a206.tiger.capture

import android.content.Context
import android.hardware.SensorManager
import android.hardware.camera2.CameraManager
import android.media.MediaRecorder
import android.os.Build
import android.util.Log
import android.view.Surface
import com.google.ar.core.CameraConfigFilter
import com.google.ar.core.Session
import com.ssafy.s15p21a206.tiger.episode.EpisodeMarker
import com.ssafy.s15p21a206.tiger.episode.FinalizeResult
import com.ssafy.s15p21a206.tiger.episode.RecordingInputValidator
import com.ssafy.s15p21a206.tiger.episode.RecordingResolution
import com.ssafy.s15p21a206.tiger.episode.SessionBundle
import com.ssafy.s15p21a206.tiger.episode.SessionBundleStore
import com.ssafy.s15p21a206.tiger.episode.SessionFinalizer
import kotlinx.coroutines.flow.StateFlow
import java.util.EnumSet

/** 수집 경로가 함께 쓰는 logcat 태그. 여러 클래스에서 나오는 한 수집의 로그를 한 줄로 이어 읽는다. */
internal const val CAPTURE_LOG_TAG = "TigerCapture"

/**
 * 한 번의 수집을 시작하고 마감한다.
 *
 * 실제 일은 셋에 나눠 맡긴다. [ArSharedCameraSession]이 카메라를, [ArPoseCollector]가 ARCore
 * 프레임을, [SensorLogWriter]와 [EpisodeLogWriter]가 기록을 든다. 이 클래스가 남겨 둔 것은
 * 그 넷을 여닫는 순서다. 순서가 곧 이 파일의 내용이며, 왜 그 순서여야 하는지는 각 단계에 적었다.
 */
class AndroidCaptureRuntime(
    context: Context,
    private val store: SessionBundleStore,
) {
    private val appContext = context.applicationContext
    private val sensorLog = SensorLogWriter(appContext.getSystemService(SensorManager::class.java))
    private val poseCollector = ArPoseCollector(appContext.getSystemService(CameraManager::class.java))
    private val cameraSession = ArSharedCameraSession(appContext) { frameTimestamps?.record(it) }
    private var mediaRecorder: MediaRecorder? = null
    private var arSession: Session? = null
    private var bundle: SessionBundle? = null
    private var frameTimestamps: FrameTimestampWriter? = null
    private var episodeLog: EpisodeLogWriter? = null

    /**
     * 최신 ARCore Tracking 관측값. pose 수집 스레드가 갱신하고 수집 화면이 주기적으로 읽는다.
     *
     * 카메라 시각을 함께 실어 보내므로, 유실 구간의 기록용 시작 시각을 `arcore_poses.csv`와
     * 같은 값으로 맞출 수 있다.
     */
    val tracking: StateFlow<TrackingSample> get() = poseCollector.tracking

    fun start(
        displayNumber: Int,
        resolution: RecordingResolution = RecordingInputValidator.DEFAULT_RESOLUTION,
        previewSurfaces: PreviewSurfaceProvider = PreviewSurfaceProvider { _, _ -> null },
    ): SessionBundle {
        check(bundle == null) { "Capture is already running" }
        val next = store.createStagingBundle(displayNumber)
        writeHeaders(next)
        try {
            openCapture(next, resolution, previewSurfaces)
        } catch (error: Exception) {
            abandon(next, error)
        }
        return next
    }

    /**
     * 수집에 필요한 것을 순서대로 연다.
     *
     * 센서 수신을 맨 뒤에 여는 것은 카메라가 실패하면 IMU만 쌓이는 상태가 되기 때문이다.
     * 하나라도 실패하면 예외가 그대로 올라가고, 뒷정리는 [abandon]이 한다.
     */
    private fun openCapture(
        next: SessionBundle,
        resolution: RecordingResolution,
        previewSurfaces: PreviewSurfaceProvider,
    ) {
        val session = Session(appContext, EnumSet.of(Session.Feature.SHARED_CAMERA))
        applyRecordingResolution(session, resolution)
        val recorder = prepareRecorder(session, next)
        arSession = session
        mediaRecorder = recorder
        bundle = next
        val previewSurface = previewSurfaceFor(session, previewSurfaces)
        cameraSession.open(session, recorder) {
            recorder.start()
            // 인코더가 실제로 돌기 시작한 뒤부터 Camera timestamp를 남긴다.
            frameTimestamps?.recording = true
            poseCollector.start(session, previewSurface)
        }
        sensorLog.listen()
    }

    /**
     * 시작하지 못한 수집을 버리고 실패를 올려 보낸다.
     *
     * 마감되지 않은 bundle을 남기면 다음 start가 막힌다. 헤더만 적힌 디렉터리도 함께 지운다.
     */
    private fun abandon(
        next: SessionBundle,
        error: Exception,
    ): Nothing {
        Log.e(CAPTURE_LOG_TAG, "Could not start ARCore shared capture", error)
        releaseResources()
        bundle = null
        next.directory.deleteRecursively()
        throw error
    }

    /** 녹화 크기를 ARCore Camera 텍스처에 맞춰 recorder를 준비한다. */
    private fun prepareRecorder(
        session: Session,
        bundle: SessionBundle,
    ): MediaRecorder =
        newMediaRecorder().apply {
            setVideoSource(MediaRecorder.VideoSource.SURFACE)
            setOutputFormat(MediaRecorder.OutputFormat.MPEG_4)
            setVideoEncoder(MediaRecorder.VideoEncoder.H264)
            setVideoFrameRate(30)
            setVideoSize(session.cameraConfig.textureSize.width, session.cameraConfig.textureSize.height)
            setOutputFile(bundle.mainVideo.absolutePath)
            // 회전 정보를 남기지 않는다. 폰을 가로로 눕혀 촬영하므로 센서가 내보내는
            // 가로 프레임이 곧 똑바로 선 장면이다. Intrinsic도 같은 기준으로 기록한다.
            prepare()
        }

    /**
     * 프리뷰를 그릴 Surface를 받아 온다. 녹화와 같은 가로 기준으로 크기를 넘긴다.
     *
     * 프리뷰를 붙이지 못해도 수집은 이어간다. 화면에 보이지 않을 뿐 기록은 온전하다.
     */
    private fun previewSurfaceFor(
        session: Session,
        previewSurfaces: PreviewSurfaceProvider,
    ): Surface? {
        val textureSize = session.cameraConfig.textureSize
        return runCatching { previewSurfaces.surfaceFor(textureSize.width, textureSize.height) }
            .onFailure { Log.w(CAPTURE_LOG_TAG, "Could not obtain a preview surface", it) }
            .getOrNull()
    }

    /**
     * 인자 없는 `MediaRecorder()`는 API 31에서 deprecated됐고, Context를 받는 생성자가 그 자리를
     * 대신한다. 31 이상에서는 Context를 넘겨 녹화가 어느 앱의 것인지 프레임워크에 알린다.
     * 31 미만에서는 그 생성자가 없으므로 옛 경로를 그대로 쓴다. 31 이상의 옛 생성자도 안에서
     * 프로세스의 Application context를 집어 쓰므로 두 경로의 동작은 같다.
     */
    private fun newMediaRecorder(): MediaRecorder =
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            MediaRecorder(appContext)
        } else {
            @Suppress("DEPRECATION")
            MediaRecorder()
        }

    fun stop(): FinalizeResult {
        val active = requireNotNull(bundle) { "No active capture" }
        sensorLog.stopListening()
        closeFrameWindow()
        val stopError = runCatching { mediaRecorder?.stop() }.exceptionOrNull()
        val camera = poseCollector.cameraMetadata
        releaseResources()
        bundle = null
        if (stopError != null) return FinalizeResult.Failed(stopError.message ?: "Video recording could not be finalized")
        return SessionFinalizer(store).finalize(active, camera = camera)
    }

    /**
     * Camera 프레임 공급을 먼저 끊고 타임스탬프 기록 창을 닫는다.
     *
     * 공급이 계속되는 상태에서 창만 닫으면, `MediaRecorder.stop()`이 끝나기까지 인코딩된 프레임이
     * `main_frame_timestamps.csv`에 남지 않아 MP4 frame 수와 벌어진다. 공급을 먼저 끊으면 인코더와
     * CSV가 같은 마지막 프레임에서 끝난다.
     */
    private fun closeFrameWindow() {
        cameraSession.stopRepeating()
        // stopRepeating 시점에 이미 진행 중인 프레임은 계속 인코딩된다. 그 프레임의
        // onCaptureCompleted까지 받고 창을 닫아야 CSV가 MP4와 같은 프레임에서 끝난다.
        runCatching { Thread.sleep(FRAME_DRAIN_DELAY_MS) }
        frameTimestamps?.recording = false
    }

    fun interrupt() {
        sensorLog.stopListening()
        closeFrameWindow()
        runCatching { mediaRecorder?.stop() }
        releaseResources()
        bundle = null
    }

    fun appendEpisode(marker: EpisodeMarker) {
        if (bundle == null) return
        episodeLog?.append(marker)
    }

    /**
     * 고른 녹화 해상도를 가진 Camera config를 세션에 지정한다.
     *
     * 녹화·프리뷰·Intrinsic이 모두 `cameraConfig.textureSize`를 따르므로, 여기서 config를 바꾸면
     * 나머지가 자동으로 같은 해상도를 쓴다. 후보가 없으면 기본 config 그대로 수집을 이어간다.
     * 해상도 하나 때문에 수집 자체를 막지 않는다.
     */
    private fun applyRecordingResolution(
        session: Session,
        resolution: RecordingResolution,
    ) {
        val selected =
            runCatching { selectCameraConfig(session, resolution) }
                .onFailure { Log.w(CAPTURE_LOG_TAG, "Could not read the supported camera configs", it) }
                .getOrNull()
        if (selected == null) {
            Log.w(CAPTURE_LOG_TAG, "No camera config matches ${resolution.width}x${resolution.height}; keeping the default config")
            return
        }
        runCatching { session.cameraConfig = selected }
            .onFailure { Log.w(CAPTURE_LOG_TAG, "Could not apply the selected camera config", it) }
    }

    /** 요청 해상도에 가장 가까운 Camera config를 고른다. 맞는 후보가 없으면 null이다. */
    private fun selectCameraConfig(
        session: Session,
        resolution: RecordingResolution,
    ) = RecordingCameraConfigSelector.select(
        candidates = session.getSupportedCameraConfigs(CameraConfigFilter(session)),
        imageSizeOf = { RecordingResolution(it.imageSize.width, it.imageSize.height) },
        textureSizeOf = { RecordingResolution(it.textureSize.width, it.textureSize.height) },
        target = resolution,
    )

    private fun releaseResources() {
        poseCollector.stop()
        // ARCore Session은 반드시 마지막에 닫는다. capture session이 닫힐 때 ARCore가
        // onCaptureSessionClosed에서 native Session을 건드리는데, Session이 먼저 닫혀 있으면
        // 콜백 스레드에서 잡히지 않는 예외가 나 프로세스가 죽는다.
        runCatching { arSession?.pause() }
        cameraSession.closeSession()
        runCatching { arSession?.close() }
        arSession = null
        mediaRecorder?.release()
        mediaRecorder = null
        // 콜백이 모두 전달된 뒤에 핸들러 스레드를 정리한다.
        cameraSession.closeThread()
        frameTimestamps = null
        episodeLog = null
        sensorLog.close()
    }

    private fun writeHeaders(bundle: SessionBundle) {
        frameTimestamps = FrameTimestampWriter(bundle.mainFrameTimestamps).also(FrameTimestampWriter::start)
        sensorLog.open(bundle)
        poseCollector.open(bundle.arcorePoses)
        episodeLog = EpisodeLogWriter(bundle.episodes).also(EpisodeLogWriter::start)
    }

    private companion object {
        /**
         * stopRepeating 뒤 진행 중인 프레임이 정리될 때까지 기다리는 시간.
         *
         * 120 ms에서는 중단 경로의 차이가 3 frame으로 남았다. 중단은 `ON_STOP`에서 일어나 마감이
         * 더 오래 걸린다. 220 ms에서 정상 마감과 중단 모두 1~2 frame으로 내려왔다.
         */
        const val FRAME_DRAIN_DELAY_MS = 220L
    }
}

/**
 * 수집에 사용할 preview Surface를 내어 준다.
 *
 * ARCore Camera 텍스처의 크기를 인자로 받는다. 프리뷰가 그 텍스처를 잘림 없이 그리려면
 * 호출 측이 이 크기로 버퍼를 맞춘 Surface를 돌려줘야 한다.
 * 프리뷰를 붙일 수 없으면 `null`을 돌려주며, 수집은 프리뷰 없이 진행된다.
 */
fun interface PreviewSurfaceProvider {
    fun surfaceFor(
        width: Int,
        height: Int,
    ): Surface?
}
