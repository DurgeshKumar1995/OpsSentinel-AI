# graph/workflow.py

from langgraph.graph import END, START, StateGraph

from models.state import IncidentState
from services.agent_logic import call_agent, execute_tools, route_action


def get_graph_builder():
    """Constructs and returns the uncompiled StateGraph for the Incident Agent."""
    builder = StateGraph(IncidentState)

    # 1. Add Processing Nodes
    builder.add_node("agent", call_agent)
    builder.add_node("execute_tools", execute_tools)

    # 2. Define Execution Connections & Conditional Routing Edges
    builder.add_edge(START, "agent")

    builder.add_conditional_edges(
        "agent",
        route_action,
        {
            "execute_tools": "execute_tools",
            "pause_for_hitl": END,  # Pauses state execution for Human-In-The-Loop approval
            "end": END,
        },
    )

    builder.add_edge("execute_tools", "agent")

    return builder
