package com.ssafy.s15p21a206.tiger.episode

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.longOrNull
import java.io.File
import java.security.MessageDigest

object SessionBundleValidator {
    private val requiredCsvHeaders =
        mapOf(
            SessionBundle.MAIN_FRAME_TIMESTAMPS_FILE to "frame_number,timestamp_ns,timestamp_source",
            SessionBundle.ACCELEROMETER_FILE to "timestamp_ns,x,y,z,accuracy",
            SessionBundle.GYROSCOPE_FILE to "timestamp_ns,x,y,z,accuracy",
            SessionBundle.ROTATION_VECTOR_FILE to "timestamp_ns,x,y,z,scalar_component,heading_accuracy_rad,accuracy",
            SessionBundle.ARCORE_POSES_FILE to "android_camera_timestamp_ns,tx,ty,tz,qx,qy,qz,qw,tracking_state,tracking_failure_reason",
            SessionBundle.EPISODES_FILE to "episode_id,start_timestamp_ns,end_timestamp_ns,task,object,outcome",
        )

    fun validate(
        directory: File,
        includesUltraWide: Boolean = false,
        requireMetadata: Boolean = true,
    ): BundleValidationResult {
        if (!directory.isDirectory) return BundleValidationResult.Invalid("bundle directory is missing")
        if (!File(directory, SessionBundle.MAIN_VIDEO_FILE).hasContent()) return BundleValidationResult.Invalid("main video is missing")
        for ((fileName, header) in requiredCsvHeaders) {
            if (!File(
                    directory,
                    fileName,
                ).hasHeader(header)
            ) {
                return BundleValidationResult.Invalid("invalid $fileName")
            }
        }
        if (!requireMetadata) {
            if (includesUltraWide && !hasValidUltraWideFiles(directory)) return BundleValidationResult.Invalid("invalid ultra-wide stream")
            return BundleValidationResult.Valid
        }

        val metadata =
            parseMetadata(File(directory, SessionBundle.METADATA_FILE))
                ?: return BundleValidationResult.Invalid("metadata commit marker is missing")
        val includesDeclaredUltraWide =
            metadata.cameraStreams["ultrawide"]?.jsonPrimitive?.booleanOrNull
                ?: return BundleValidationResult.Invalid("metadata ultra-wide declaration is missing")
        if (metadata.cameraStreams["main"]?.jsonPrimitive?.booleanOrNull !=
            true
        ) {
            return BundleValidationResult.Invalid("main stream declaration is invalid")
        }
        if (metadata.sessionId.isBlank()) return BundleValidationResult.Invalid("metadata session id is missing")
        if (includesDeclaredUltraWide !=
            hasUltraWideDocuments(directory)
        ) {
            return BundleValidationResult.Invalid("ultra-wide document set does not match metadata")
        }
        if (includesDeclaredUltraWide &&
            !hasValidUltraWideFiles(directory)
        ) {
            return BundleValidationResult.Invalid("invalid ultra-wide stream")
        }
        if (!hasExactManifest(
                directory,
                metadata.manifest,
            )
        ) {
            return BundleValidationResult.Invalid("metadata manifest does not match bundle")
        }
        return BundleValidationResult.Valid
    }

    private fun hasValidUltraWideFiles(directory: File): Boolean =
        File(directory, SessionBundle.ULTRAWIDE_VIDEO_FILE).hasContent() &&
            File(directory, SessionBundle.ULTRAWIDE_FRAME_TIMESTAMPS_FILE).hasHeader("frame_number,timestamp_ns,timestamp_source")

    private fun hasUltraWideDocuments(directory: File): Boolean =
        File(directory, SessionBundle.ULTRAWIDE_VIDEO_FILE).exists() ||
            File(directory, SessionBundle.ULTRAWIDE_FRAME_TIMESTAMPS_FILE).exists()

    private fun parseMetadata(metadataFile: File): BundleMetadata? =
        runCatching {
            if (!metadataFile.hasContent()) return null
            val root = Json.parseToJsonElement(metadataFile.readText()).jsonObject
            BundleMetadata(
                sessionId = root["session_id"]?.jsonPrimitive?.contentOrNull ?: return null,
                cameraStreams = root["camera_streams"]?.jsonObject ?: return null,
                manifest = root["files"]?.jsonArray?.map(::parseManifestEntry) ?: return null,
            )
        }.getOrNull()

    private fun parseManifestEntry(element: kotlinx.serialization.json.JsonElement): ManifestEntry? {
        val entry = element as? JsonObject ?: return null
        return ManifestEntry(
            path = entry["path"]?.jsonPrimitive?.contentOrNull ?: return null,
            sizeBytes = entry["sizeBytes"]?.jsonPrimitive?.longOrNull ?: return null,
            sha256 = entry["sha256"]?.jsonPrimitive?.contentOrNull ?: return null,
        )
    }

    private fun hasExactManifest(
        directory: File,
        manifest: List<ManifestEntry?>,
    ): Boolean {
        if (manifest.any { it == null }) return false
        val entries = manifest.filterNotNull()
        if (entries.map(ManifestEntry::path).toSet().size != entries.size) return false
        val documents = directory.listFiles()?.toList().orEmpty()
        if (documents.any { !it.isFile }) return false
        val rawDocuments = documents.filter { it.name != SessionBundle.METADATA_FILE }.associateBy(File::getName)
        if (entries.map(ManifestEntry::path).toSet() != rawDocuments.keys) return false
        return entries.all { entry ->
            val document = rawDocuments[entry.path] ?: return@all false
            entry.path == document.name &&
                entry.sizeBytes == document.length() &&
                entry.sha256.matches(SHA_256) &&
                entry.sha256 == sha256(document)
        }
    }

    private fun File.hasContent() = isFile && length() > 0L

    private fun File.hasHeader(header: String) = hasContent() && bufferedReader().use { it.readLine() == header }

    private fun sha256(file: File): String {
        val digest = MessageDigest.getInstance("SHA-256")
        val buffer = ByteArray(DEFAULT_BUFFER_SIZE)
        file.inputStream().use { input ->
            while (true) {
                val count = input.read(buffer)
                if (count <= 0) break
                digest.update(buffer, 0, count)
            }
        }
        return digest.digest().joinToString("") { "%02x".format(it) }
    }

    private data class BundleMetadata(
        val sessionId: String,
        val cameraStreams: JsonObject,
        val manifest: List<ManifestEntry?>,
    )

    private data class ManifestEntry(
        val path: String,
        val sizeBytes: Long,
        val sha256: String,
    )

    private val SHA_256 = Regex("[0-9a-f]{64}")
}

sealed interface BundleValidationResult {
    val isValid: Boolean

    data object Valid : BundleValidationResult {
        override val isValid = true
    }

    data class Invalid(
        val reason: String,
    ) : BundleValidationResult {
        override val isValid = false
    }
}
