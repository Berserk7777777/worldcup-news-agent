from pathlib import Path

from monitoring.trace_recorder import AgentTraceRecorder
from monitoring.trace_store import TraceStore


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TRACE_STORE = TraceStore(PROJECT_ROOT / "data" / "agent_traces.db")


__all__ = ["AgentTraceRecorder", "DEFAULT_TRACE_STORE", "TraceStore"]
