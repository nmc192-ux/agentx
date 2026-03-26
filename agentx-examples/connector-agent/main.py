from agentx_sdk import AgentXClient

def external_agent_logic(event):
    if event.type == "TASK_AVAILABLE":
        return {
            "type": "accept_task",
            "data": {"task_id": event.data["task_id"]}
        }

client = AgentXClient(api_key="your_api_key")

for event in client.listen_events():
    decision = external_agent_logic(event)

    if decision:
        client.act(
            action_type=decision["type"],
            data=decision["data"]
        )
