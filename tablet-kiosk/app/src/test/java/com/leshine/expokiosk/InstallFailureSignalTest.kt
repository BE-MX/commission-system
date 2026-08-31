package com.leshine.expokiosk

import org.junit.Assert.assertFalse
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertSame
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test

class InstallFailureSignalTest {
    @Test
    fun `missing and incorrect tokens are rejected`() {
        val storage = MemoryTokenStorage()
        val gate = OneTimeTokenGate(storage)
        val issued = gate.issue()

        assertFalse(gate.consume(null))
        assertFalse(gate.consume(""))
        assertFalse(gate.consume("wrong-$issued"))
        assertTrue(gate.consume(issued))
    }

    @Test
    fun `correct token can only be consumed once`() {
        val gate = OneTimeTokenGate(MemoryTokenStorage())
        val issued = gate.issue()

        assertTrue(gate.consume(issued))
        assertFalse(gate.consume(issued))
    }

    @Test
    fun `generated tokens are non empty and distinct`() {
        val gate = OneTimeTokenGate(MemoryTokenStorage())

        val first = gate.issue()
        val second = gate.issue()

        assertTrue(first.isNotBlank())
        assertTrue(second.isNotBlank())
        assertNotEquals(first, second)
    }

    @Test
    fun `failed token clear never reports a successful consumption`() {
        val storage = MemoryTokenStorage(clearResult = false)
        val gate = OneTimeTokenGate(storage)
        val issued = gate.issue()

        assertFalse(gate.consume(issued))
        assertFalse(gate.consume(issued))
    }

    @Test
    fun `issue exception happens only after process failure and prevents launch`() {
        val events = mutableListOf<String>()
        val recovery = InstallFailureRecovery(
            failProcess = { events += "fail" },
            issueToken = {
                events += "issue"
                throw IllegalStateException("storage failed")
            },
            launch = { events += "launch" },
        )

        recovery.run()

        assertEquals(listOf("fail", "issue"), events)
    }

    @Test
    fun `launch exception keeps process failed after token was issued`() {
        val events = mutableListOf<String>()
        val recovery = InstallFailureRecovery(
            failProcess = { events += "fail" },
            issueToken = {
                events += "issue"
                "private-token"
            },
            launch = {
                events += "launch"
                throw IllegalStateException("activity unavailable")
            },
        )

        recovery.run()

        assertEquals(listOf("fail", "issue", "launch"), events)
    }

    @Test
    fun `normal recovery orders process failure before issue and launch`() {
        val events = mutableListOf<String>()
        val recovery = InstallFailureRecovery(
            failProcess = { events += "fail" },
            issueToken = {
                events += "issue"
                "private-token"
            },
            launch = { events += "launch:$it" },
        )

        recovery.run()

        assertEquals(listOf("fail", "issue", "launch:private-token"), events)
    }

    @Test
    fun `fatal recovery errors are not swallowed`() {
        val fatal = AssertionError("fatal")
        val recovery = InstallFailureRecovery(
            failProcess = {},
            issueToken = { throw fatal },
            launch = {},
        )

        try {
            recovery.run()
            fail("Expected fatal error")
        } catch (error: AssertionError) {
            assertSame(fatal, error)
        }
    }

    private class MemoryTokenStorage(
        private val clearResult: Boolean = true,
    ) : OneTimeTokenStorage {
        private var token: String? = null

        override fun read(): String? = token

        override fun write(token: String): Boolean {
            this.token = token
            return true
        }

        override fun clear(): Boolean {
            if (clearResult) token = null
            return clearResult
        }
    }
}
