package app.accessfromphone

import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class HapticsTest {
    @Test fun `each action category has a distinct increasing tap length`() {
        val taps = listOf("tick", "light", "medium", "heavy").map { Haptics.waveform(it)[1] }
        assertEquals(listOf(12L, 20L, 32L, 50L), taps)
        assertTrue(taps.zipWithNext().all { (before, after) -> after > before })
        val patterns = listOf("tick", "light", "medium", "heavy", "success", "warning", "error", "alert")
            .map { Haptics.waveform(it).toList() }
        assertEquals(patterns.size, patterns.toSet().size)
    }

    @Test fun `a buzz is a delay of zero, then buzz and pause in turn`() {
        assertArrayEquals(longArrayOf(0, 12, 50, 12), Haptics.waveform("success"))
        assertArrayEquals(longArrayOf(0, 40, 70, 40, 70, 110), Haptics.waveform("alert"))
        assertArrayEquals(longArrayOf(0, 30, 50, 30, 50, 30), Haptics.waveform("error"))
    }

    @Test fun `no buzz is too short to feel`() {
        for (kind in listOf("tick", "light", "medium", "heavy", "success", "warning", "error", "alert")) {
            val w = Haptics.waveform(kind)
            for (i in 1 until w.size step 2) assertTrue("$kind buzz $i is ${w[i]} ms", w[i] >= 12)
        }
    }

    @Test fun `an unknown name is a light tap, never an error`() {
        assertArrayEquals(Haptics.waveform("light"), Haptics.waveform("nonsense"))
        assertEquals(2, Haptics.waveform("").size)
    }

    @Test fun `the alert is the strongest and longest pattern, so a lost PC is felt`() {
        val total = { kind: String -> Haptics.waveform(kind).sum() }
        for (other in listOf("tick", "light", "medium", "heavy", "success", "warning", "error")) assertTrue(other, total("alert") > total(other))
    }
}
