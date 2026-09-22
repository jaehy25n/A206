package com.ssafy.s15p21a206.tiger.ui.capture

import android.graphics.Matrix
import android.graphics.SurfaceTexture
import android.hardware.camera2.CameraCharacteristics
import android.hardware.camera2.CameraManager
import android.view.Surface
import android.view.TextureView
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.viewinterop.AndroidView
import com.ssafy.s15p21a206.tiger.capture.CameraPreviewTransform
import com.ssafy.s15p21a206.tiger.episode.RecordingResolution
import com.ssafy.s15p21a206.tiger.ui.common.findActivity

/**
 * 카메라 프레임이 올라오는 판.
 *
 * `TextureView`와 그 `SurfaceTexture`의 수명만 맡는다. Camera2 session을 열고 닫는 것은 부모다 —
 * [onSurfaceAvailable]과 [onSurfaceDestroyed]로 알리기만 한다. 이전에는 리스너 안에서 세션을 직접
 * 열었고, 그 자리가 이 화면에서 "렌더링과 사용자 이벤트 처리로 한정"이 가장 크게 깨지는 곳이었다.
 *
 * [applyTransform]은 유휴 프리뷰에서만 켠다. 수집이 시작되면 ARCore가 같은 Surface에 표시 기하를
 * 반영해 직접 그리므로, `TextureView` 변환이 남아 있으면 그 위에 한 번 더 돌아간다.
 */
@Suppress("FunctionName")
@Composable
internal fun CapturePreviewSurface(
    bufferSize: RecordingResolution,
    applyTransform: Boolean,
    onSurfaceAvailable: (Surface, SurfaceTexture) -> Unit,
    onSurfaceDestroyed: () -> Unit,
    onFrame: () -> Unit,
    modifier: Modifier,
) {
    AndroidView(
        factory = { viewContext ->
            TextureView(viewContext).apply {
                surfaceTextureListener =
                    object : TextureView.SurfaceTextureListener {
                        override fun onSurfaceTextureAvailable(
                            surfaceTexture: SurfaceTexture,
                            width: Int,
                            height: Int,
                        ) {
                            surfaceTexture.setDefaultBufferSize(bufferSize.width, bufferSize.height)
                            applyIdlePreviewTransform(this@apply, width, height, bufferSize.width, bufferSize.height)
                            onSurfaceAvailable(Surface(surfaceTexture), surfaceTexture)
                        }

                        override fun onSurfaceTextureSizeChanged(
                            surfaceTexture: SurfaceTexture,
                            width: Int,
                            height: Int,
                        ) = applyIdlePreviewTransform(this@apply, width, height, bufferSize.width, bufferSize.height)

                        override fun onSurfaceTextureDestroyed(surfaceTexture: SurfaceTexture): Boolean {
                            onSurfaceDestroyed()
                            return true
                        }

                        // 실패한 프리뷰는 늦게 온 프레임으로 되살아나지 않는다. reduce가 막는다.
                        override fun onSurfaceTextureUpdated(surfaceTexture: SurfaceTexture) = onFrame()
                    }
            }
        },
        update = { view ->
            if (applyTransform) {
                applyIdlePreviewTransform(view, view.width, view.height, bufferSize.width, bufferSize.height)
            } else {
                view.setTransform(Matrix())
            }
        },
        modifier = modifier,
    )
}

/**
 * 유휴 프리뷰의 회전을 맞춘다.
 *
 * Camera2는 SurfaceTexture에 센서 방향 그대로 프레임을 넣고 TextureView는 회전을 반영하지 않는다.
 * 수집 중 프리뷰는 ARCore가 처리하지만 이 경로는 앱이 직접 걸어야 한다.
 */
private fun applyIdlePreviewTransform(
    view: TextureView,
    viewWidth: Int,
    viewHeight: Int,
    bufferWidth: Int,
    bufferHeight: Int,
) {
    val activity = view.context.findActivity() ?: return
    val manager = view.context.getSystemService(CameraManager::class.java) ?: return
    val rotation =
        runCatching {
            val cameraId =
                manager.cameraIdList.first {
                    manager.getCameraCharacteristics(it).get(CameraCharacteristics.LENS_FACING) ==
                        CameraCharacteristics.LENS_FACING_BACK
                }
            val sensorOrientation =
                manager.getCameraCharacteristics(cameraId).get(CameraCharacteristics.SENSOR_ORIENTATION) ?: 0

            @Suppress("DEPRECATION")
            val displayRotation = activity.windowManager.defaultDisplay.rotation
            CameraPreviewTransform.rotationDegrees(sensorOrientation, displayRotation)
        }.getOrNull() ?: return
    view.setTransform(
        CameraPreviewTransform.matrix(viewWidth, viewHeight, bufferWidth, bufferHeight, rotation),
    )
}
