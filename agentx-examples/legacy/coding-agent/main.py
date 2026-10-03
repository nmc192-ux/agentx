from agentx_sdk import AgentXClient

client = AgentXClient(api_key="your_api_key")

for event in client.listen_events():

    if event.type == "TASK_AVAILABLE":
        task = event.data

        if "code" in task.get("description", "").lower():
            print("[CODING AGENT] Accepting task:", task["task_id"])
            client.accept_task(task["task_id"])
