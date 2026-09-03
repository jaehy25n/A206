package com.ssafy.s15p21a206.tiger.upload

import com.ssafy.s15p21a206.tiger.episode.SessionBundle
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.Request
import okhttp3.RequestBody.Companion.asRequestBody
import okhttp3.OkHttpClient
import com.ssafy.s15p21a206.tiger.episode.UploadState

class SessionUploadRequestFactory(private val baseUrl: String) {
    fun create(bundle: SessionBundle, includesUltraWide: Boolean = false): Request {
        val body = MultipartBody.Builder().setType(MultipartBody.FORM).apply {
            add("metadata", bundle.metadata, "application/json")
            add("main_video", bundle.mainVideo, "video/mp4")
            add("main_frame_timestamps", bundle.mainFrameTimestamps, "text/csv")
            add("accelerometer", bundle.accelerometer, "text/csv")
            add("gyroscope", bundle.gyroscope, "text/csv")
            add("rotation_vector", bundle.rotationVector, "text/csv")
            add("arcore_poses", bundle.arcorePoses, "text/csv")
            add("episodes", bundle.episodes, "text/csv")
            if (includesUltraWide) { add("ultrawide_video", java.io.File(bundle.directory, SessionBundle.ULTRAWIDE_VIDEO_FILE), "video/mp4"); add("ultrawide_frame_timestamps", java.io.File(bundle.directory, SessionBundle.ULTRAWIDE_FRAME_TIMESTAMPS_FILE), "text/csv") }
        }.build()
        return Request.Builder().url("$baseUrl/sessions").header("Idempotency-Key", bundle.sessionId).post(body).build()
    }

    private fun MultipartBody.Builder.add(name: String, file: java.io.File, type: String) = addFormDataPart(name, file.name, file.asRequestBody(type.toMediaType()))
}

class SessionUploader(private val client: OkHttpClient, private val factory: SessionUploadRequestFactory) {
    fun upload(bundle: SessionBundle): UploadState = try {
        client.newCall(factory.create(bundle)).execute().use { response ->
            if (response.code == 200 || response.code == 201) UploadState.UPLOADED else UploadState.FAILED
        }
    } catch (_: Exception) { UploadState.FAILED }
}
