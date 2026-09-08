package com.ssafy.s15p21a206.tiger.upload

import com.ssafy.s15p21a206.tiger.episode.RemoteReceipt
import com.ssafy.s15p21a206.tiger.episode.SessionBundle
import com.ssafy.s15p21a206.tiger.episode.SessionBundleValidator
import java.io.File
import java.util.UUID
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.boolean
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.asRequestBody

class SessionUploadRequestFactory(private val baseUrl: String) {
    fun create(bundle: SessionBundle): Request {
        require(bundle.sessionId.isUuid()) { "Session ID must be a UUID" }
        val body = MultipartBody.Builder().setType(MultipartBody.FORM).apply {
            add("metadata", bundle.metadata, "application/json")
            add("main_video", bundle.mainVideo, "video/mp4")
            add("main_frame_timestamps", bundle.mainFrameTimestamps, "text/csv")
            add("accelerometer", bundle.accelerometer, "text/csv")
            add("gyroscope", bundle.gyroscope, "text/csv")
            add("rotation_vector", bundle.rotationVector, "text/csv")
            add("arcore_poses", bundle.arcorePoses, "text/csv")
            add("episodes", bundle.episodes, "text/csv")
            if (metadataIncludesUltraWide(bundle)) {
                add("ultrawide_video", File(bundle.directory, SessionBundle.ULTRAWIDE_VIDEO_FILE), "video/mp4")
                add("ultrawide_frame_timestamps", File(bundle.directory, SessionBundle.ULTRAWIDE_FRAME_TIMESTAMPS_FILE), "text/csv")
            }
        }.build()
        return Request.Builder()
            .url("${baseUrl.trimEnd('/')}/sessions")
            .header("Idempotency-Key", bundle.sessionId)
            .post(body)
            .build()
    }

    private fun metadataIncludesUltraWide(bundle: SessionBundle): Boolean {
        val metadata = Json.parseToJsonElement(bundle.metadata.readText()).jsonObject
        require(metadata["session_id"]?.jsonPrimitive?.content == bundle.sessionId) {
            "Metadata session ID must match the idempotency key"
        }
        return metadata["camera_streams"]?.jsonObject
            ?.get("ultrawide")
            ?.jsonPrimitive
            ?.boolean
            ?: error("Metadata ultra-wide declaration is missing")
    }

    private fun MultipartBody.Builder.add(name: String, file: File, type: String) {
        addFormDataPart(name, file.name, file.asRequestBody(type.toMediaType()))
    }

    private fun String.isUuid(): Boolean = runCatching { UUID.fromString(this) }.isSuccess
}

sealed interface UploadResult {
    data object Uploaded : UploadResult
    data class Failed(val reason: String) : UploadResult
}

interface SessionUploadGateway {
    suspend fun upload(bundle: SessionBundle): UploadResult
}

class SessionUploader(
    private val client: OkHttpClient,
    private val factory: SessionUploadRequestFactory
) : SessionUploadGateway {
    private val json = Json { ignoreUnknownKeys = true }

    override suspend fun upload(bundle: SessionBundle): UploadResult = withContext(Dispatchers.IO) {
        if (!SessionBundleValidator.validate(bundle.directory).isValid) {
            return@withContext UploadResult.Failed("Completed bundle is invalid")
        }
        runCatching {
            client.newCall(factory.create(bundle)).execute().use { response ->
                if (response.code !in setOf(200, 201) || response.isRedirect) {
                    return@use UploadResult.Failed("Upload was rejected (${response.code})")
                }
                val contentType = response.body.contentType()
                if (contentType?.type != "application" || contentType.subtype != "json") {
                    return@use UploadResult.Failed("Upload receipt is not JSON")
                }
                val receipt = json.decodeFromString<RemoteReceipt>(response.body.string())
                if (receipt.sessionId == bundle.sessionId && receipt.result in setOf("created", "duplicate")) {
                    UploadResult.Uploaded
                } else {
                    UploadResult.Failed("Upload receipt does not match the session")
                }
            }
        }.getOrElse { UploadResult.Failed("Network upload failed") }
    }
}
