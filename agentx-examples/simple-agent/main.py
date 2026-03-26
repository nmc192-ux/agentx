from agentx_sdk import AgentXClient

client = AgentXClient(api_key="your_api_key")

for event in client.listen_events():
    print("[EVENT]", event.type, event.data)
