"""
AgentX — Founding Agents
All 8 founding agents, each powered by a dedicated Claude instance.
"""
from .atlas  import Atlas
from .bruno  import Bruno
from .daria  import Daria
from .quinn  import Quinn
from .gia    import Gia
from .marcus import Marcus
from .thea   import Thea
from .nova   import Nova

__all__ = [
    "Atlas", "Bruno", "Daria", "Quinn",
    "Gia", "Marcus", "Thea", "Nova",
]
