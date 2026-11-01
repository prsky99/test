"""Catalog-only MCP discovery; conversation writes belong to hello/chat."""

from .engine import Reply
from .protocols import requested_protocol

TOOLS = frozenset(("search", "find_agents", "whats_new", "search_workflows"))


def lookup(front, name, args, token):
    visitor = front.book.by_token(token) if token else None
    if name == "whats_new":
        previous, _ = front.book.last_results(visitor.id) if visitor else ([], 0)
        interests = front.book.interests(visitor.id) if visitor and not previous else []
        task = (
            previous[0].get("task")
            if previous
            else interests[0]["task"]
            if interests
            else None
        )
        if not task:
            return Reply(
                "No saved task is available. Use chat to start or resume a conversation, or search with an explicit task.",
                "whats_new",
                {"status": "task_context_required", "recommendations": []},
            )
        protocol = (
            previous[0].get("protocol_filter") if previous else interests[0].get("kind")
        )
    else:
        task = args["task"]
        protocol = requested_protocol(task, {"kind": args.get("kind")})
    from .chat_guidance import review, redacted, MESSAGES

    guidance = review(task)
    if redacted(task) != task:
        guidance = "needs_redaction"
    if guidance:
        return Reply(
            MESSAGES[guidance], "clarify", {"status": guidance, "recommendations": []}
        )
    if name == "search_workflows":
        from .workflow_discovery import recommend

        value = recommend(
            front.store, task, {"protocol": protocol}, runtime=front.workflows
        )
        text = (
            "\n".join(
                str(i + 1) + ". " + row["name"]
                for i, row in enumerate(value["workflows"])
            )
            or "No relevant published workflow found."
        )
        return Reply(text, "find_workflow", value)
    return front.concierge.lookup(visitor, task, protocol=protocol)
