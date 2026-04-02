from typing import TypedDict, Annotated, Sequence
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages

class AssistantState(TypedDict):
    # Appends new messages to the existing list (crucial for Telegram chat memory)
    messages: Annotated[Sequence[BaseMessage], add_messages]
    # Used by cronjobs to pass in raw anomaly data
    context_data: dict 
    # Tracks if Ollama is currently available
    is_gpu_available: bool