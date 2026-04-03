from typing import Annotated, Sequence
from typing_extensions import TypedDict, NotRequired
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages

class AssistantState(TypedDict):
    """
    The core state object passed between LangGraph nodes.
    """
    # The add_messages reducer appends new messages to the sequence.
    # This is crucial for maintaining conversational memory in Telegram.
    messages: Annotated[Sequence[BaseMessage], add_messages]
    
    # Used by proactive scripts (like check_anomalies.py) to pass in 
    # raw metrics/log data for analysis without clogging chat history.
    context_data: NotRequired[dict]
    
    # --- LangGraph Internal Keys ---
    # Required by the prebuilt ReAct agent to prevent infinite loops
    is_last_step: NotRequired[bool]
    remaining_steps: NotRequired[int]