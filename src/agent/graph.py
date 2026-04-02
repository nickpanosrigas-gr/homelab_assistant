from langgraph.prebuilt import ToolNode
from langchain_community.chat_models import ChatOllama
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from src.config.settings import settings
from src.agent.state import AssistantState
from src.agent.sub_agents.containers import get_container_status

# 1. Define the System Prompt
SYSTEM_PROMPT = """You are the Lead AIOps Assistant for a home lab infrastructure. 
Your job is to be brief, technical, and accurate. 
Do not guess or assume. If a user asks about a service, ALWAYS use your tools to check its real-time status before answering."""

# 2. Register tools
tools = [get_container_status]

def get_llm():
    """Connects to Ollama and binds the tools to the LLM."""
    llm = ChatOllama(
        base_url=settings.OLLAMA_BASE_URL,
        model=settings.OLLAMA_MODEL,
        temperature=0.1
    )
    return llm.bind_tools(tools)

def chatbot_node(state: AssistantState):
    """The main reasoning node for the AI."""
    llm = get_llm()
    
    # Inject the system prompt and the chat history
    prompt = ChatPromptTemplate.from_messages([
        ("system", SYSTEM_PROMPT),
        MessagesPlaceholder(variable_name="messages"),
    ])
    
    chain = prompt | llm
    response = chain.invoke({"messages": state["messages"]})
    return {"messages": [response]}

# 3. Construct the Graph
graph_builder = StateGraph(AssistantState)

# Add nodes
graph_builder.add_node("chatbot", chatbot_node)
graph_builder.add_node("tools", ToolNode(tools=tools))

# Add routing logic (If AI decides to use a tool, go to tools. Otherwise, end.)
graph_builder.add_conditional_edges(
    "chatbot",
    lambda state: "tools" if state["messages"][-1].tool_calls else END,
)
graph_builder.add_edge("tools", "chatbot")
graph_builder.add_edge(START, "chatbot")

# Compile the final application
assistant_app = graph_builder.compile()