package com.leshine.expokiosk

import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertTrue
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

    private class MemoryTokenStorage : OneTimeTokenStorage {
        private var token: String? = null

        override fun read(): String? = token

        override fun write(token: String): Boolean {
            this.token = token
            return true
        }

        override fun clear(): Boolean {
            token = null
            return true
        }
    }
}
