package com.ssafy.s15p21a206.tiger.episode

import java.io.File
import java.nio.file.Files
import java.util.UUID

class SessionBundleExporter(private val documentTreeGateway: DocumentTreeGateway) {
    suspend fun exportCompleted(repository: SessionRepository, sessionId: String, treeUri: String): ExportAttemptResult {
        val source = repository.completedSource(sessionId)
            ?: return ExportAttemptResult.Failed("Only completed sessions can be exported", UUID.randomUUID().toString())
        val previous = repository.exportFor(sessionId) ?: SessionExport(sessionId)
        val attemptId = UUID.randomUUID().toString()
        val exporting = previous.start(treeUri, attemptId)
        repository.updateExport(exporting)
        return when (val result = export(File(source.bundlePath), sessionId, treeUri, attemptId)) {
            is ExportAttemptResult.Exported -> {
                repository.updateExport(exporting.complete())
                result
            }
            is ExportAttemptResult.Failed -> {
                repository.updateExport(exporting.fail(result.reason))
                result
            }
        }
    }

    fun export(source: File, sessionId: String, treeUri: String, attemptId: String = UUID.randomUUID().toString()): ExportAttemptResult {
        if (!SessionBundleValidator.validate(source).isValid) return ExportAttemptResult.Failed("Completed source bundle is invalid", attemptId)
        if (!documentTreeGateway.supportsPublish(treeUri)) return ExportAttemptResult.Failed("Selected folder does not support persisted write access", attemptId)

        return runCatching {
            val tigerCapture = documentTreeGateway.list(treeUri).firstOrNull { it.name == EXPORT_ROOT && it.isDirectory }
                ?: requireNotNull(documentTreeGateway.createDirectory(treeUri, EXPORT_ROOT)) { "Cannot create export root" }
            check(documentTreeGateway.isWithinTree(treeUri, tigerCapture.uri)) { "Export root escapes selected tree" }
            val temporary = requireNotNull(documentTreeGateway.createDirectory(tigerCapture.uri, ".$sessionId.exporting-$attemptId")) { "Cannot create export attempt directory" }
            check(documentTreeGateway.isWithinTree(treeUri, temporary.uri)) { "Export attempt escapes selected tree" }
            copyBundle(source, temporary)
            validateDestination(temporary, source)

            documentTreeGateway.list(tigerCapture.uri).firstOrNull { it.name == sessionId }?.let {
                check(documentTreeGateway.delete(it.uri)) { "Cannot replace existing export" }
            }
            check(documentTreeGateway.rename(temporary.uri, sessionId) != null) { "Cannot publish export attempt" }
            ExportAttemptResult.Exported(attemptId)
        }.getOrElse { ExportAttemptResult.Failed(it.message ?: "Export failed", attemptId) }
    }

    private fun copyBundle(source: File, destination: DocumentNode) {
        val rawFiles = source.listFiles().orEmpty().filter { it.isFile && it.name != SessionBundle.METADATA_FILE }.sortedBy(File::getName)
        rawFiles.forEach { copyFile(it, destination) }
        copyFile(File(source, SessionBundle.METADATA_FILE), destination)
    }

    private fun copyFile(source: File, destination: DocumentNode) {
        val target = requireNotNull(documentTreeGateway.createFile(destination.uri, source.name, mimeType(source.name))) { "Cannot create ${source.name}" }
        source.inputStream().use { input ->
            requireNotNull(documentTreeGateway.openOutput(target.uri)) { "Cannot write ${source.name}" }.use { output -> input.copyTo(output) }
        }
    }

    private fun validateDestination(destination: DocumentNode, source: File) {
        val scratch = Files.createTempDirectory("tiger-export-").toFile()
        try {
            val expected = source.listFiles().orEmpty().filter(File::isFile).map(File::getName).toSet()
            val children = documentTreeGateway.list(destination.uri)
            check(children.none { it.isDirectory } && children.map(DocumentNode::name).toSet() == expected) { "Destination document set does not match source" }
            children.forEach { child ->
                requireNotNull(documentTreeGateway.openInput(child.uri)) { "Cannot read ${child.name}" }.use { input -> File(scratch, child.name).outputStream().use(input::copyTo) }
            }
            check(SessionBundleValidator.validate(scratch).isValid) { "Destination bundle validation failed" }
        } finally {
            scratch.deleteRecursively()
        }
    }

    private fun mimeType(name: String): String = when {
        name.endsWith(".mp4") -> "video/mp4"
        name.endsWith(".csv") -> "text/csv"
        name.endsWith(".json") -> "application/json"
        else -> "application/octet-stream"
    }

    sealed interface ExportAttemptResult {
        data class Exported(val attemptId: String) : ExportAttemptResult
        data class Failed(val reason: String, val attemptId: String) : ExportAttemptResult
    }

    private companion object { const val EXPORT_ROOT = "TigerCapture" }
}
