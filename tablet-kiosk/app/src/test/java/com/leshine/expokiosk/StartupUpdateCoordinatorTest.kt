package com.leshine.expokiosk

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertSame
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test

class StartupUpdateCoordinatorTest {
    @Test
    fun `repeated start creates and runs only one updater`() {
        val coordinator = StartupUpdateCoordinator()
        var creates = 0
        var runs = 0
        val states = mutableListOf<UpdateState>()
        coordinator.attach(states::add)
        val factory = {
            creates += 1
            StartupUpdateRun { onState ->
                runs += 1
                onState(UpdateState.NoUpdate)
            }
        }

        coordinator.start(::runNow, factory)
        coordinator.start(::runNow, factory)

        assertEquals(1, creates)
        assertEquals(1, runs)
        assertEquals(listOf(UpdateState.NoUpdate), states)
    }

    @Test
    fun `new observer replaces old observer and old detach does not remove it`() {
        val coordinator = StartupUpdateCoordinator()
        val statesA = mutableListOf<UpdateState>()
        val statesB = mutableListOf<UpdateState>()
        val observerA: (UpdateState) -> Unit = { statesA += it }
        val observerB: (UpdateState) -> Unit = { statesB += it }

        coordinator.attach(observerA)
        coordinator.attach(observerB)
        coordinator.detach(observerA)
        coordinator.publish(UpdateState.Checking)

        assertTrue(statesA.isEmpty())
        assertEquals(listOf(UpdateState.Checking), statesB)
    }

    @Test
    fun `factory exception becomes a safe terminal failure`() {
        val coordinator = StartupUpdateCoordinator()
        val states = mutableListOf<UpdateState>()
        coordinator.attach(states::add)

        coordinator.start(::runNow) { throw IllegalStateException("token=secret") }

        val failure = states.single() as UpdateState.Failed
        assertEquals(StartupUpdateCoordinator.SAFE_FAILURE_MESSAGE, failure.message)
        assertFalse(UpdatePresentation.from(failure).blocksKiosk)
    }

    @Test
    fun `runner exception becomes a safe terminal failure`() {
        val coordinator = StartupUpdateCoordinator()
        val states = mutableListOf<UpdateState>()
        coordinator.attach(states::add)

        coordinator.start(::runNow) {
            StartupUpdateRun { throw IllegalStateException("https://secret.example") }
        }

        val failure = states.single() as UpdateState.Failed
        assertEquals(StartupUpdateCoordinator.SAFE_FAILURE_MESSAGE, failure.message)
        assertFalse(UpdatePresentation.from(failure).blocksKiosk)
    }

    @Test
    fun `late installing cannot replace a failed state`() {
        val coordinator = StartupUpdateCoordinator()
        val failure = UpdateState.Failed("internal")

        coordinator.publish(failure)
        coordinator.publish(UpdateState.Installing)

        assertEquals(failure, coordinator.currentState())
        assertFalse(UpdatePresentation.from(coordinator.currentState()!!).blocksKiosk)
    }

    @Test
    fun `fatal errors are not captured`() {
        val coordinator = StartupUpdateCoordinator()
        val fatal = AssertionError("fatal")

        try {
            coordinator.start(::runNow) { StartupUpdateRun { throw fatal } }
            fail("Expected fatal error")
        } catch (error: AssertionError) {
            assertSame(fatal, error)
        }
    }

    private fun runNow(task: () -> Unit) = task()
}
