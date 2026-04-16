"""AgentX SDK — configuration dataclass."""
from dataclasses import dataclass, field


@dataclass
class AgentXConfig:
    """All runtime tunables for AgentXClient and AgentXWebSocket.

    Args:
        api_key:                  Bearer token used for authenticated requests.
        base_url:                 HTTP base URL of the AgentX platform.
        api_version:              Semantic version string injected as X-AgentX-Version header.
        timeout:                  HTTP request timeout in seconds.
        max_retries:              Maximum retry attempts for transient HTTP failures.
        ws_reconnect_base_delay:  Initial WebSocket reconnect delay (seconds, doubles each attempt).
        ws_reconnect_max_delay:   Upper bound on WebSocket reconnect delay (seconds).
        ws_heartbeat_interval:    Seconds between ping frames sent to the server.
        log_level:                Logging level string: "DEBUG", "INFO", "WARNING", "ERROR".
    """

    api_key: str
    base_url: str = "http://localhost:8000"
    api_version: str = "v1"
    timeout: int = 10
    max_retries: int = 3
    ws_reconnect_base_delay: float = 1.0
    ws_reconnect_max_delay: float = 30.0
    ws_heartbeat_interval: float = 10.0
    log_level: str = "INFO"
