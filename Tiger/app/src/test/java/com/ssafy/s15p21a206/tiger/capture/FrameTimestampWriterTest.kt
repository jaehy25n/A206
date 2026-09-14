package com.ssafy.s15p21a206.tiger.capture

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File

class FrameTimestampWriterTest {
    @get:Rule val folder = TemporaryFolder()

    private fun writer(): Pair<FrameTimestampWriter, File> {
        val file = File(folder.root, "main_frame_timestamps.csv")
        return FrameTimestampWriter(file).also(FrameTimestampWriter::start) to file
    }

    private fun File.dataRows() = readLines().drop(1).filter(String::isNotBlank)

    @Test fun `header stays unchanged`() {
        val (_, file) = writer()
        assertEquals("frame_number,timestamp_ns,timestamp_source", file.readLines().first())
    }

    @Test fun `frame number starts at zero and increases by one`() {
        val (writer, file) = writer()
        writer.recording = true
        listOf(106907744502871L, 106907811008986L, 106907844207178L).forEach(writer::record)
        assertEquals(
            listOf(
                "0,106907744502871,SENSOR_TIMESTAMP",
                "1,106907811008986,SENSOR_TIMESTAMP",
                "2,106907844207178,SENSOR_TIMESTAMP",
            ),
            file.dataRows(),
        )
    }

    // 동일한 CaptureCallback이 두 번 등록돼 있어 같은 프레임이 두 번 도착할 수 있다.
    @Test fun `duplicate timestamp advances neither row nor frame number`() {
        val (writer, file) = writer()
        writer.recording = true
        assertTrue(writer.record(100))
        assertFalse(writer.record(100))
        assertTrue(writer.record(200))
        assertEquals(listOf("0,100,SENSOR_TIMESTAMP", "1,200,SENSOR_TIMESTAMP"), file.dataRows())
    }

    @Test fun `rows outside the recording window are dropped`() {
        val (writer, file) = writer()
        assertFalse(writer.record(100))
        writer.recording = true
        assertTrue(writer.record(200))
        writer.recording = false
        assertFalse(writer.record(300))
        assertEquals(listOf("0,200,SENSOR_TIMESTAMP"), file.dataRows())
    }

    @Test fun `frame number keeps counting across a recording gap`() {
        val (writer, file) = writer()
        writer.recording = true
        writer.record(100)
        writer.recording = false
        writer.record(200)
        writer.recording = true
        writer.record(300)
        assertEquals(listOf("0,100,SENSOR_TIMESTAMP", "1,300,SENSOR_TIMESTAMP"), file.dataRows())
    }
}
