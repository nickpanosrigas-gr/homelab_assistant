from typing import Literal
from typing_extensions import TypedDict
from langchain_core.messages import SystemMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

# 1. FIXED: Use the new langchain-ollama package to remove the deprecation warning
from langchain_ollama import ChatOllama

from langgraph.graph import StateGraph, START, END
from langgraph.prebuilt import create_react_agent

from src.config.settings import settings
from src.agent.state import AssistantState
from src.agent.sub_agents.services import SERVICES_TOOLS, SERVICES_SYSTEM_PROMPT
from src.agent.sub_agents.storage import STORAGE_TOOLS, STORAGE_SYSTEM_PROMPT
from src.agent.prompts import SUPERVISOR_SYSTEM_PROMPT

# Extend the base AssistantState to include routing decision variable
class GraphState(AssistantState):
    next: str

# Initialize the Local LLM Backend
llm = ChatOllama(
    base_url=settings.OLLAMA_BASE_URL,
    model=settings.OLLAMA_MODEL,
    temperature=settings.OLLAMA_TEMPERATURE,
    num_ctx=settings.OLLAMA_NUM_CTX
)

# 3. FIXED: The newest versions of LangGraph use 'prompt' for the system instructions
services_agent = create_react_agent(
    model=llm,
    tools=SERVICES_TOOLS,
    prompt=SERVICES_SYSTEM_PROMPT
)

storage_agent = create_react_agent(
    model=llm,
    tools=STORAGE_TOOLS,
    prompt=STORAGE_SYSTEM_PROMPT
)

# Wrapper nodes to extract only the final message from the workers 
# (keeps the chat history clean in Telegram)
def services_node(state: GraphState):
    result = services_agent.invoke(state)
    return {"messages": [result["messages"][-1]]}

def storage_node(state: GraphState):
    result = storage_agent.invoke(state)
    return {"messages": [result["messages"][-1]]}

# Create the Main Supervisor
class RouteResponse(TypedDict):
    next: Literal["Services", "Storage", "FINISH"]

supervisor_prompt = ChatPromptTemplate.from_messages([
    ("system", SUPERVISOR_SYSTEM_PROMPT),
    MessagesPlaceholder(variable_name="messages"),
])

supervisor_chain = supervisor_prompt | llm.with_structured_output(RouteResponse)

def supervisor_node(state: GraphState):
    try:
        route = supervisor_chain.invoke({"messages": state["messages"]})
        next_node = route.get("next", "FINISH") if route else "FINISH"
    except Exception as e:
        # Failsafe: If the local LLM fails structured output parsing, drop to FINISH
        print(f"Supervisor routing failed: {e}")
        next_node = "FINISH"
        
    return {"next": next_node}

# Compile the Graph
builder = StateGraph(GraphState)

builder.add_node("Supervisor", supervisor_node)
builder.add_node("Services", services_node)
builder.add_node("Storage", storage_node)

builder.add_edge(START, "Supervisor")

# Conditional routing based on the supervisor's decision
builder.add_conditional_edges(
    "Supervisor",
    lambda state: state.get("next", "FINISH"),
    {
        "Services": "Services",
        "Storage": "Storage",
        "FINISH": END
    }
)

# Once a worker answers, finish the graph execution
builder.add_edge("Services", END)
builder.add_edge("Storage", END)

# Compile into a runnable application
app = builder.compile()