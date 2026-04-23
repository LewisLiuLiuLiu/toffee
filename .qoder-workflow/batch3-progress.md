# Batch 3 Progress: Simulator Events Interface + AnalogAgent

## Tasks
- Task 6: Simulator base class `events`/`next_event` + `__event_loop` in asynchronous.py
- Task 7: AnalogAgent event configuration (actual path: `toffee/analog/analog_agent.py`)

## Status: IN PROGRESS

## Changes Needed

### Task 6: simulator.py
- Add `events` property (default: `{"step": self.clock_event}`)
- Add `async def next_event() -> str` (default: `step(1)` + return "step", NO tick — unified by __event_loop)

### Task 6: asynchronous.py
- Add `__event_loop(simulator)` async function as event-driven alternative to `__clock_loop`
- Update `start_clock()` to use `__event_loop`

### Task 7: analog_agent.py
- Add `event_name` parameter to `__init__`
- Use `simulator.events.get(event_name, simulator.clock_event)` for the wait event

### Tests
- Test `Simulator.events` default behavior
- Test `AnalogAgent` with custom event_name
