def check_node(state):
    # stop infinite loops
    if state["iterations"] >= 5:
        return {**state, "needs_more": False, "response": "I couldn't complete the operation after multiple attempts. Please try again or rephrase."}

    # if we flagged a pending action needing confirmation
    if state.get("pending_action"):
        return {**state, "needs_more": False}

    # if no plan was produced
    if not state["plan"]:
        return {**state, "needs_more": False, "response": "I couldn't decide what tools to use. Please be more specific."}

    # if tool_results empty, we still need more (execute tools)
    if len(state["tool_results"]) == 0:
        return {**state, "needs_more": True}

    # basic heuristic: if we got results, we can respond
    return {**state, "needs_more": False}
