package com.ssafy.s15p21a206.tiger.episode

import java.io.File
import java.io.InputStream
import java.io.OutputStream
import java.nio.file.Files
import java.security.MessageDigest
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class SessionBundleExporterTest {
    @Test
    fun `valid completed source is copied through attempt and published`() {
        val root = Files.createTempDirectory("export").toFile()
        val source = File(root, "source").apply { mkdirs() }
        writeBundle(source)
        val destination = File(root, "tree").apply { mkdirs() }

        val result = SessionBundleExporter(FileGateway(destination)).export(source, "session", destination.path, "attempt")

        assertTrue(result is SessionBundleExporter.ExportAttemptResult.Exported)
        assertTrue(SessionBundleValidator.validate(File(destination, "TigerCapture/session")).isValid)
        assertTrue(File(source, SessionBundle.METADATA_FILE).exists())
        assertFalse(File(destination, "TigerCapture/.session.exporting-attempt").exists())
        root.deleteRecursively()
    }

    @Test
    fun `retry uses a new attempt and overwrites only after validation`() {
        val root = Files.createTempDirectory("export").toFile()
        val source = File(root, "source").apply { mkdirs() }
        writeBundle(source)
        val destination = File(root, "tree").apply { mkdirs() }
        val exporter = SessionBundleExporter(FileGateway(destination))

        exporter.export(source, "session", destination.path, "first")
        val result = exporter.export(source, "session", destination.path, "second")

        assertTrue(result is SessionBundleExporter.ExportAttemptResult.Exported)
        assertTrue(SessionBundleValidator.validate(File(destination, "TigerCapture/session")).isValid)
        assertFalse(File(destination, "TigerCapture/.session.exporting-first").exists())
        assertFalse(File(destination, "TigerCapture/.session.exporting-second").exists())
        root.deleteRecursively()
    }

    @Test
    fun `tree boundary escape fails without changing source`() {
        val root = Files.createTempDirectory("export").toFile()
        val source = File(root, "source").apply { mkdirs() }
        writeBundle(source)
        val destination = File(root, "tree").apply { mkdirs() }
        val gateway = object : FileGateway(destination) {
            override fun isWithinTree(treeUri: String, documentUri: String) = false
        }

        val result = SessionBundleExporter(gateway).export(source, "session", destination.path, "escape")

        assertTrue(result is SessionBundleExporter.ExportAttemptResult.Failed)
        assertTrue(File(source, SessionBundle.METADATA_FILE).exists())
        root.deleteRecursively()
    }

    @Test
    fun `SAF capability exception is returned as an export failure`() {
        val root = Files.createTempDirectory("export").toFile()
        val source = File(root, "source").apply { mkdirs() }
        writeBundle(source)
        val gateway = object : FileGateway(root) {
            override fun hasPersistedWriteGrant(treeUri: String): Boolean = throw SecurityException("grant is unavailable")
        }

        val result = SessionBundleExporter(gateway).export(source, "session", root.path, "attempt")

        assertTrue(result is SessionBundleExporter.ExportAttemptResult.Failed)
        assertTrue(File(source, SessionBundle.METADATA_FILE).exists())
        root.deleteRecursively()
    }

    private fun writeBundle(directory: File) {
        val headers = mapOf(SessionBundle.MAIN_FRAME_TIMESTAMPS_FILE to "frame_number,timestamp_ns,timestamp_source", SessionBundle.ACCELEROMETER_FILE to "timestamp_ns,x,y,z,accuracy", SessionBundle.GYROSCOPE_FILE to "timestamp_ns,x,y,z,accuracy", SessionBundle.ROTATION_VECTOR_FILE to "timestamp_ns,x,y,z,scalar_component,heading_accuracy_rad,accuracy", SessionBundle.ARCORE_POSES_FILE to "android_camera_timestamp_ns,tx,ty,tz,qx,qy,qz,qw,tracking_state,tracking_failure_reason", SessionBundle.EPISODES_FILE to "episode_id,start_timestamp_ns,end_timestamp_ns,task,object,outcome")
        File(directory, SessionBundle.MAIN_VIDEO_FILE).writeBytes(byteArrayOf(1))
        headers.forEach { (name, header) -> File(directory, name).writeText("$header\n") }
        val manifest = directory.listFiles().orEmpty().sortedBy(File::getName).joinToString(",") { file -> """{"path":"${file.name}","sizeBytes":${file.length()},"sha256":"${hash(file)}"}""" }
        File(directory, SessionBundle.METADATA_FILE).writeText("""{"session_id":"session","camera_streams":{"main":true,"ultrawide":false},"files":[$manifest]}""")
    }

    private fun hash(file: File) = MessageDigest.getInstance("SHA-256").digest(file.readBytes()).joinToString("") { "%02x".format(it) }

    private open class FileGateway(private val root: File) : DocumentTreeGateway {
        override fun hasPersistedWriteGrant(treeUri: String) = treeUri == root.path
        override fun isWithinTree(treeUri: String, documentUri: String) = File(documentUri).canonicalPath.startsWith(root.canonicalPath)
        override fun list(directoryUri: String) = File(directoryUri).listFiles().orEmpty().map { DocumentNode(it.path, it.name, it.isDirectory) }
        override fun createDirectory(parentUri: String, name: String) = File(parentUri, name).let { if (it.mkdir()) DocumentNode(it.path, name, true) else null }
        override fun createFile(parentUri: String, name: String, mimeType: String) = File(parentUri, name).let { if (it.createNewFile()) DocumentNode(it.path, name, false) else null }
        override fun openInput(uri: String): InputStream? = File(uri).inputStream()
        override fun openOutput(uri: String): OutputStream? = File(uri).outputStream()
        override fun rename(uri: String, name: String) = File(uri).let { file -> File(file.parentFile, name).let { target -> if (file.renameTo(target)) DocumentNode(target.path, name, true) else null } }
        override fun delete(uri: String) = File(uri).deleteRecursively()
    }
}
