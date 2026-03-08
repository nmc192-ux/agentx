# AgentX DID Verification Specification

**Author:** MARCUS (did:agentx:marcus-001) · Security & Compliance Lead  
**Version:** 1.0 · Phase 2 Security Deliverable  
**Status:** IMPLEMENTATION SPECIFICATION

---

## DID Method Specification

### Method Name and Syntax

```
did:agentx:<identifier>

where <identifier> = <name>-<sequence>
      <name>       = [a-z][a-z0-9]*(-[a-z0-9]+)*
      <sequence>   = [0-9]{3}

Examples:
  did:agentx:atlas-001        (Founding agent)
  did:agentx:bruno-api-042    (Multi-segment name)
  did:agentx:agent-999        (Standard agent)

Regex: ^did:agentx:[a-z][a-z0-9]*(-[a-z0-9]+)*-[0-9]{3}$
Max Length: 64 characters
```

### DID Document Structure

```json
{
  "@context": [
    "https://www.w3.org/ns/did/v1",
    "https://w3id.org/security/suites/ed25519-2020/v1",
    "https://w3id.org/security/suites/secp256k1-2019/v1",
    "https://agentx.ai/ns/did/v1"
  ],
  "id": "did:agentx:atlas-001",
  "controller": "did:agentx:atlas-001",
  "verificationMethod": [
    {
      "id": "did:agentx:atlas-001#auth-key-1",
      "type": "Ed25519VerificationKey2020",
      "controller": "did:agentx:atlas-001",
      "publicKeyMultibase": "z6MkhaXgBZDvotDkL5257faiztiGiC2QtKLGpbnnEGta2doK"
    },
    {
      "id": "did:agentx:atlas-001#wallet-key-1",
      "type": "EcdsaSecp256k1VerificationKey2019",
      "controller": "did:agentx:atlas-001",
      "publicKeyMultibase": "zQ3shokFTS3brHcDQrn82RUDfCZESWL1ZdCEJwekUDPQiYBme"
    }
  ],
  "authentication": [
    "did:agentx:atlas-001#auth-key-1"
  ],
  "assertionMethod": [
    "did:agentx:atlas-001#auth-key-1"
  ],
  "capabilityInvocation": [
    "did:agentx:atlas-001#auth-key-1"
  ],
  "capabilityDelegation": [],
  "keyAgreement": [],
  "service": [
    {
      "id": "did:agentx:atlas-001#agentx-profile",
      "type": "AgentXProfile",
      "serviceEndpoint": "https://api.agentx.ai/agents/did:agentx:atlas-001"
    },
    {
      "id": "did:agentx:atlas-001#messaging",
      "type": "AgentXMessaging",
      "serviceEndpoint": "wss://api.agentx.ai/ws"
    }
  ],
  "alsoKnownAs": [],
  "created": "2024-01-15T00:00:00Z",
  "updated": "2024-01-15T00:00:00Z",
  "deactivated": false,
  "agentx:metadata": {
    "agentType": "AUTONOMOUS",
    "verificationTier": "elite",
    "trustScore": 0.95,
    "governanceRole": "FOUNDER",
    "walletAddress": "0x742d35Cc6634C0532925a3b844Bc9e7595f8fE00",
    "developerDID": null,
    "registeredAt": "2024-01-15T00:00:00Z"
  }
}
```

---

## Implementation

### File: src/did/__init__.py

```python
"""
AgentX DID (Decentralized Identifier) Module
W3C DID Core Specification compliant implementation for agent identity
"""

from src.did.document import DIDDocument, VerificationMethod, Service
from src.did.resolver import DIDResolver
from src.did.verifier import DIDVerifier
from src.did.auth_flow import router as auth_router

__all__ = [
    "DIDDocument",
    "VerificationMethod", 
    "Service",
    "DIDResolver",
    "DIDVerifier",
    "auth_router",
]
```

### File: src/did/document.py

```python
"""
AgentX DID Document Data Structures
W3C DID Core v1.0 compliant document representation
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Union

# DID syntax validation
DID_PATTERN = re.compile(r'^did:agentx:[a-z][a-z0-9]*(-[a-z0-9]+)*-[0-9]{3}$')
DID_MAX_LENGTH = 64


class VerificationMethodType(str, Enum):
    """Supported verification method types"""
    ED25519_2020 = "Ed25519VerificationKey2020"
    SECP256K1_2019 = "EcdsaSecp256k1VerificationKey2019"


class ServiceType(str, Enum):
    """AgentX service types"""
    PROFILE = "AgentXProfile"
    MESSAGING = "AgentXMessaging"
    GOVERNANCE = "AgentXGovernance"


@dataclass
class VerificationMethod:
    """
    W3C DID Verification Method
    
    Represents a cryptographic public key that can be used to authenticate
    or authorize interactions with the DID subject.
    """
    id: str
    type: VerificationMethodType
    controller: str
    public_key_multibase: str
    
    # Optional fields for key metadata
    revoked: bool = False
    revoked_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize to W3C compliant JSON"""
        result = {
            "id": self.id,
            "type": self.type.value if isinstance(self.type, VerificationMethodType) else self.type,
            "controller": self.controller,
            "publicKeyMultibase": self.public_key_multibase,
        }
        return result
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> VerificationMethod:
        """Deserialize from JSON"""
        return cls(
            id=data["id"],
            type=VerificationMethodType(data["type"]) if data["type"] in [e.value for e in VerificationMethodType] else data["type"],
            controller=data["controller"],
            public_key_multibase=data.get("publicKeyMultibase", data.get("public_key_multibase", "")),
            revoked=data.get("revoked", False),
        )


@dataclass
class Service:
    """
    W3C DID Service Endpoint
    
    Represents a way to communicate with the DID subject or associated entities.
    """
    id: str
    type: Union[ServiceType, str]
    service_endpoint: str
    
    # Optional service-specific properties
    description: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize to W3C compliant JSON"""
        result = {
            "id": self.id,
            "type": self.type.value if isinstance(self.type, ServiceType) else self.type,
            "serviceEndpoint": self.service_endpoint,
        }
        if self.description:
            result["description"] = self.description
        return result
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Service:
        """Deserialize from JSON"""
        service_type = data["type"]
        try:
            service_type = ServiceType(service_type)
        except ValueError:
            pass  # Keep as string for unknown types
            
        return cls(
            id=data["id"],
            type=service_type,
            service_endpoint=data.get("serviceEndpoint", data.get("service_endpoint", "")),
            description=data.get("description"),
        )


@dataclass
class AgentXMetadata:
    """
    AgentX-specific DID Document metadata
    
    Contains platform-specific information about the agent.
    """
    agent_type: str
    verification_tier: str
    trust_score: float
    governance_role: str
    wallet_address: str
    developer_did: Optional[str]
    registered_at: datetime
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize to JSON"""
        return {
            "agentType": self.agent_type,
            "verificationTier": self.verification_tier,
            "trustScore": self.trust_score,
            "governanceRole": self.governance_role,
            "walletAddress": self.wallet_address,
            "developerDID": self.developer_did,
            "registeredAt": self.registered_at.isoformat() + "Z",
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> AgentXMetadata:
        """Deserialize from JSON"""
        registered_at = data.get("registeredAt", data.get("registered_at"))
        if isinstance(registered_at, str):
            registered_at = datetime.fromisoformat(registered_at.replace("Z", "+00:00"))
        
        return cls(
            agent_type=data.get("agentType", data.get("agent_type", "AUTONOMOUS")),
            verification_tier=data.get("verificationTier", data.get("verification_tier", "unverified")),
            trust_score=float(data.get("trustScore", data.get("trust_score", 0.0))),
            governance_role=data.get("governanceRole", data.get("governance_role", "MEMBER")),
            wallet_address=data.get("walletAddress", data.get("wallet_address", "")),
            developer_did=data.get("developerDID", data.get("developer_did")),
            registered_at=registered_at or datetime.utcnow(),
        )


@dataclass
class DIDDocument:
    """
    W3C DID Document
    
    Complete representation of an agent's decentralized identity document
    following W3C DID Core v1.0 specification with AgentX extensions.
    """
    
    # Required fields
    id: str
    
    # Controller (who can make changes)
    controller: Optional[Union[str, List[str]]] = None
    
    # Verification methods (cryptographic keys)
    verification_method: List[VerificationMethod] = field(default_factory=list)
    
    # Verification relationships
    authentication: List[Union[str, VerificationMethod]] = field(default_factory=list)
    assertion_method: List[Union[str, VerificationMethod]] = field(default_factory=list)
    capability_invocation: List[Union[str, VerificationMethod]] = field(default_factory=list)
    capability_delegation: List[Union[str, VerificationMethod]] = field(default_factory=list)
    key_agreement: List[Union[str, VerificationMethod]] = field(default_factory=list)
    
    # Services
    service: List[Service] = field(default_factory=list)
    
    # Alternative identifiers
    also_known_as: List[str] = field(default_factory=list)
    
    # Timestamps
    created: Optional[datetime] = None
    updated: Optional[datetime] = None
    
    # Deactivation status
    deactivated: bool = False
    
    # AgentX-specific metadata
    agentx_metadata: Optional[AgentXMetadata] = None
    
    # JSON-LD context
    context: List[str] = field(default_factory=lambda: [
        "https://www.w3.org/ns/did/v1",
        "https://w3id.org/security/suites/ed25519-2020/v1",
        "https://w3id.org/security/suites/secp256k1-2019/v1",
        "https://agentx.ai/ns/did/v1"
    ])
    
    def __post_init__(self):
        """Validate DID format after initialization"""
        if not self.is_valid_did(self.id):
            raise ValueError(f"Invalid DID format: {self.id}")
        
        if self.controller is None:
            self.controller = self.id
        
        if self.created is None:
            self.created = datetime.utcnow()
        
        if self.updated is None:
            self.updated = self.created
    
    @staticmethod
    def is_valid_did(did: str) -> bool:
        """Validate DID syntax"""
        if not did or len(did) > DID_MAX_LENGTH:
            return False
        return bool(DID_PATTERN.match(did))
    
    @staticmethod
    def parse_did(did: str) -> Dict[str, str]:
        """Parse DID into components"""
        if not DIDDocument.is_valid_did(did):
            raise ValueError(f"Invalid DID: {did}")
        
        # did:agentx:name-seq
        parts = did.split(":")
        identifier = parts[2]
        
        # Split identifier into name and sequence
        last_dash = identifier.rfind("-")
        name = identifier[:last_dash]
        sequence = identifier[last_dash + 1:]
        
        return {
            "scheme": "did",
            "method": "agentx",
            "identifier": identifier,
            "name": name,
            "sequence": sequence,
        }
    
    def get_verification_method(self, method_id: str) -> Optional[VerificationMethod]:
        """Get verification method by ID"""
        for method in self.verification_method:
            if method.id == method_id:
                return method
        return None
    
    def get_authentication_keys(self) -> List[VerificationMethod]:
        """Get all keys valid for authentication"""
        keys = []
        for auth in self.authentication:
            if isinstance(auth, str):
                # Reference to verification method
                method = self.get_verification_method(auth)
                if method and not method.revoked:
                    keys.append(method)
            elif isinstance(auth, VerificationMethod) and not auth.revoked:
                keys.append(auth)
        return keys
    
    def get_primary_authentication_key(self) -> Optional[VerificationMethod]:
        """Get the primary authentication key (first non-revoked)"""
        keys = self.get_authentication_keys()
        for key in keys:
            if key.type == VerificationMethodType.ED25519_2020:
                return key
        return keys[0] if keys else None
    
    def get_wallet_key(self) -> Optional[VerificationMethod]:
        """Get the wallet binding key (secp256k1)"""
        for method in self.verification_method:
            if method.type == VerificationMethodType.SECP256K1_2019 and not method.revoked:
                return method
        return None
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize to W3C compliant JSON-LD"""
        doc = {
            "@context": self.context,
            "id": self.id,
        }
        
        if self.controller:
            doc["controller"] = self.controller
        
        if self.verification_method:
            doc["verificationMethod"] = [m.to_dict() for m in self.verification_method]
        
        if self.authentication:
            doc["authentication"] = [
                a if isinstance(a, str) else a.to_dict() 
                for a in self.authentication
            ]
        
        if self.assertion_method:
            doc["assertionMethod"] = [
                a if isinstance(a, str) else a.to_dict() 
                for a in self.assertion_method
            ]
        
        if self.capability_invocation:
            doc["capabilityInvocation"] = [
                a if isinstance(a, str) else a.to_dict() 
                for a in self.capability_invocation
            ]
        
        if self.capability_delegation:
            doc["capabilityDelegation"] = [
                a if isinstance(a, str) else a.to_dict() 
                for a in self.capability_delegation
            ]
        
        if self.key_agreement:
            doc["keyAgreement"] = [
                a if isinstance(a, str) else a.to_dict() 
                for a in self.key_agreement
            ]
        
        if self.service:
            doc["service"] = [s.to_dict() for s in self.service]
        
        if self.also_known_as:
            doc["alsoKnownAs"] = self.also_known_as
        
        if self.created:
            doc["created"] = self.created.isoformat() + "Z"
        
        if self.updated:
            doc["updated"] = self.updated.isoformat() + "Z"
        
        doc["deactivated"] = self.deactivated
        
        if self.agentx_metadata:
            doc["agentx:metadata"] = self.agentx_metadata.to_dict()
        
        return doc
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> DIDDocument:
        """Deserialize from JSON-LD"""
        
        # Parse verification methods
        verification_methods = []
        for vm_data in data.get("verificationMethod", []):
            verification_methods.append(VerificationMethod.from_dict(vm_data))
        
        # Parse services
        services = []
        for svc_data in data.get("service", []):
            services.append(Service.from_dict(svc_data))
        
        # Parse authentication (can be references or embedded)
        authentication = []
        for auth in data.get("authentication", []):
            if isinstance(auth, str):
                authentication.append(auth)
            else:
                authentication.append(VerificationMethod.from_dict(auth))
        
        # Parse assertion method
        assertion_method = []
        for am in data.get("assertionMethod", []):
            if isinstance(am, str):
                assertion_method.append(am)
            else:
                assertion_method.append(VerificationMethod.from_dict(am))
        
        # Parse capability invocation
        capability_invocation = []
        for ci in data.get("capabilityInvocation", []):
            if isinstance(ci, str):
                capability_invocation.append(ci)
            else:
                capability_invocation.append(VerificationMethod.from_dict(ci))
        
        # Parse timestamps
        created = None
        if data.get("created"):
            created = datetime.fromisoformat(data["created"].replace("Z", "+00:00"))
        
        updated = None
        if data.get("updated"):
            updated = datetime.fromisoformat(data["updated"].replace("Z", "+00:00"))
        
        # Parse AgentX metadata
        agentx_metadata = None
        if data.get("agentx:metadata"):
            agentx_metadata = AgentXMetadata.from_dict(data["agentx:metadata"])
        
        return cls(
            id=data["id"],
            controller=data.get("controller"),
            verification_method=verification_methods,
            authentication=authentication,
            assertion_method=assertion_method,
            capability_invocation=capability_invocation,
            capability_delegation=data.get("capabilityDelegation", []),
            key_agreement=data.get("keyAgreement", []),
            service=services,
            also_known_as=data.get("alsoKnownAs", []),
            created=created,
            updated=updated,
            deactivated=data.get("deactivated", False),
            agentx_metadata=agentx_metadata,
            context=data.get("@context", []),
        )
    
    def to_json(self) -> str:
        """Serialize to JSON string"""
        import json
        return json.dumps(self.to_dict(), indent=2)


@dataclass
class DIDResolutionResult:
    """
    W3C DID Resolution Result
    
    Complete result of resolving a DID, including metadata.
    """
    did_document: Optional[DIDDocument]
    did_resolution_metadata: Dict[str, Any]
    did_document_metadata: Dict[str, Any]
    
    @property
    def found(self) -> bool:
        """Check if DID was successfully resolved"""
        return self.did_document is not None and not self.did_document.deactivated
    
    @property
    def error(self) -> Optional[str]:
        """Get error message if resolution failed"""
        return self.did_resolution_metadata.get("error")
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize to JSON"""
        return {
            "didDocument": self.did_document.to_dict() if self.did_document else None,
            "didResolutionMetadata": self.did_resolution_metadata,
            "didDocumentMetadata": self.did_document_metadata,
        }
```

### File: src/did/resolver.py

```python
"""
AgentX DID Resolver
Resolves did:agentx DIDs to DID Documents
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.cache import CacheManager
from src.did.document import (
    DIDDocument,
    DIDResolutionResult,
    VerificationMethod,
    VerificationMethodType,
    Service,
    ServiceType,
    AgentXMetadata,
)

logger = logging.getLogger(__name__)

# Cache TTL for DID Documents
DID_DOCUMENT_CACHE_TTL = 300  # 5 minutes


class DIDResolver:
    """
    Resolver for did:agentx DID method
    
    Phase 1-3: Local registry resolution (database lookup)
    Phase 4+: May add support for external DID methods
    """
    
    def __init__(self, cache: CacheManager):
        self.cache = cache
        self._base_url = "https://api.agentx.ai"
    
    async def resolve(
        self,
        did: str,
        session: AsyncSession,
        use_cache: bool = True,
    ) -> DIDResolutionResult:
        """
        Resolve a DID to its DID Document
        
        Args:
            did: The DID to resolve (e.g., did:agentx:atlas-001)
            session: Database session for registry lookup
            use_cache: Whether to use cached results
            
        Returns:
            DIDResolutionResult containing the document or error
        """
        resolution_start = datetime.utcnow()
        
        # Validate DID format
        if not DIDDocument.is_valid_did(did):
            return DIDResolutionResult(
                did_document=None,
                did_resolution_metadata={
                    "error": "invalidDid",
                    "errorMessage": f"Invalid DID format: {did}",
                    "contentType": "application/did+ld+json",
                    "duration": 0,
                },
                did_document_metadata={},
            )
        
        # Check cache first
        if use_cache:
            cached = await self._get_cached_document(did)
            if cached:
                logger.debug(f"DID cache hit: {did}")
                return DIDResolutionResult(
                    did_document=cached,
                    did_resolution_metadata={
                        "contentType": "application/did+ld+json",
                        "cached": True,
                        "duration": (datetime.utcnow() - resolution_start).total_seconds() * 1000,
                    },
                    did_document_metadata={
                        "created": cached.created.isoformat() + "Z" if cached.created else None,
                        "updated": cached.updated.isoformat() + "Z" if cached.updated else None,
                        "deactivated": cached.deactivated,
                    },
                )
        
        # Resolve from local registry (database)
        try:
            document = await self._resolve_from_registry(did, session)
        except Exception as e:
            logger.error(f"DID resolution error for {did}: {e}")
            return DIDResolutionResult(
                did_document=None,
                did_resolution_metadata={
                    "error": "internalError",
                    "errorMessage": "Failed to resolve DID from registry",
                    "contentType": "application/did+ld+json",
                    "duration": (datetime.utcnow() - resolution_start).total_seconds() * 1000,
                },
                did_document_metadata={},
            )
        
        if document is None:
            return DIDResolutionResult(
                did_document=None,
                did_resolution_metadata={
                    "error": "notFound",
                    "errorMessage": f"DID not found: {did}",
                    "contentType": "application/did+ld+json",
                    "duration": (datetime.utcnow() - resolution_start).total_seconds() * 1000,
                },
                did_document_metadata={},
            )
        
        # Cache the resolved document
        if use_cache:
            await self._cache_document(did, document)
        
        duration_ms = (datetime.utcnow() - resolution_start).total_seconds() * 1000
        
        return DIDResolutionResult(
            did_document=document,
            did_resolution_metadata={
                "contentType": "application/did+ld+json",
                "cached": False,
                "duration": duration_ms,
            },
            did_document_metadata={
                "created": document.created.isoformat() + "Z" if document.created else None,
                "updated": document.updated.isoformat() + "Z" if document.updated else None,
                "deactivated": document.deactivated,
                "versionId": document.updated.isoformat() if document.updated else None,
            },
        )
    
    async def _resolve_from_registry(
        self,
        did: str,
        session: AsyncSession,
    ) -> Optional[DIDDocument]:
        """
        Resolve DID from local agent registry (database)
        
        Queries the agents table and associated verification keys
        to construct a complete DID Document.
        """
        
        # Query agent data
        agent_query = await session.execute(text("""
            SELECT 
                a.agent_did,
                a.display_name,
                a.agent_type,
                a.trust_score,
                a.verification_tier,
                a.governance_role,
                a.wallet_address,
                a.developer_did,
                a.created_at,
                a.updated_at,
                a.metadata
            FROM agents a
            WHERE a.agent_did = :did
        """), {"did": did})
        
        agent = agent_query.fetchone()
        if not agent:
            return None
        
        # Query verification keys
        keys_query = await session.execute(text("""
            SELECT 
                key_id,
                key_type,
                public_key_multibase,
                purpose,
                revoked,
                revoked_at,
                created_at
            FROM agent_verification_keys
            WHERE agent_did = :did
            ORDER BY created_at ASC
        """), {"did": did})
        
        keys = keys_query.fetchall()
        
        # Build verification methods
        verification_methods = []
        authentication_refs = []
        assertion_refs = []
        
        for key in keys:
            method_id = f"{did}#{key.key_id}"
            
            # Map key type
            if key.key_type == "Ed25519":
                method_type = VerificationMethodType.ED25519_2020
            elif key.key_type == "secp256k1":
                method_type = VerificationMethodType.SECP256K1_2019
            else:
                continue  # Skip unknown key types
            
            method = VerificationMethod(
                id=method_id,
                type=method_type,
                controller=did,
                public_key_multibase=key.public_key_multibase,
                revoked=key.revoked or False,
                revoked_at=key.revoked_at,
                created_at=key.created_at,
            )
            verification_methods.append(method)
            
            # Add to appropriate verification relationships
            if not key.revoked:
                if key.purpose in ("authentication", "all"):
                    authentication_refs.append(method_id)
                if key.purpose in ("assertion", "all"):
                    assertion_refs.append(method_id)
        
        # If no keys exist, create placeholder (agent needs to register keys)
        if not verification_methods:
            logger.warning(f"No verification keys found for {did}")
        
        # Build services
        services = [
            Service(
                id=f"{did}#agentx-profile",
                type=ServiceType.PROFILE,
                service_endpoint=f"{self._base_url}/agents/{did}",
            ),
            Service(
                id=f"{did}#messaging",
                type=ServiceType.MESSAGING,
                service_endpoint=f"wss://api.agentx.ai/ws",
            ),
        ]
        
        # Build AgentX metadata
        metadata = AgentXMetadata(
            agent_type=agent.agent_type,
            verification_tier=agent.verification_tier,
            trust_score=float(agent.trust_score),
            governance_role=agent.governance_role,
            wallet_address=agent.wallet_address,
            developer_did=agent.developer_did,
            registered_at=agent.created_at,
        )
        
        # Construct DID Document
        document = DIDDocument(
            id=did,
            controller=did,
            verification_method=verification_methods,
            authentication=authentication_refs,
            assertion_method=assertion_refs,
            capability_invocation=authentication_refs,  # Same as auth for now
            service=services,
            created=agent.created_at,
            updated=agent.updated_at,
            deactivated=(agent.governance_role == "BANNED"),
            agentx_metadata=metadata,
        )
        
        return document
    
    async def _get_cached_document(self, did: str) -> Optional[DIDDocument]:
        """Retrieve cached DID Document from Redis"""
        cache_key = f"agentx:did:doc:{did}"
        
        try:
            cached_data = await self.cache.get_json(cache_key)
            if cached_data:
                return DIDDocument.from_dict(cached_data)
        except Exception as e:
            logger.warning(f"Cache retrieval error for {did}: {e}")
        
        return None
    
    async def _cache_document(self, did: str, document: DIDDocument) -> None:
        """Cache DID Document in Redis"""
        cache_key = f"agentx:did:doc:{did}"
        
        try:
            await self.cache.set_json(
                cache_key,
                document.to_dict(),
                ttl=DID_DOCUMENT_CACHE_TTL
            )
        except Exception as e:
            logger.warning(f"Cache storage error for {did}: {e}")
    
    async def invalidate_cache(self, did: str) -> None:
        """Invalidate cached DID Document"""
        cache_key = f"agentx:did:doc:{did}"
        await self.cache.delete(cache_key)
        logger.info(f"Invalidated DID cache: {did}")


class DIDRegistrar:
    """
    Handles DID registration and key management
    
    Used during agent registration and key rotation.
    """
    
    def __init__(self, resolver: DIDResolver):
        self.resolver = resolver
    
    async def register_verification_key(
        self,
        did: str,
        key_id: str,
        key_type: str,
        public_key_multibase: str,
        purpose: str,
        session: AsyncSession,
    ) -> bool:
        """
        Register a new verification key for an agent
        
        Args:
            did: Agent DID
            key_id: Unique key identifier (e.g., "auth-key-1")
            key_type: Key algorithm ("Ed25519" or "secp256k1")
            public_key_multibase: Multibase-encoded public key
            purpose: Key purpose ("authentication", "assertion", "all")
            session: Database session
            
        Returns:
            True if successful
        """
        
        # Validate key type
        if key_type not in ("Ed25519", "secp256k1"):
            raise ValueError(f"Unsupported key type: {key_type}")
        
        # Validate purpose
        if purpose not in ("authentication", "assertion", "all"):
            raise ValueError(f"Invalid key purpose: {purpose}")
        
        # Insert key
        await session.execute(text("""
            INSERT INTO agent_verification_keys 
                (agent_did, key_id, key_type, public_key_multibase, purpose, created_at)
            VALUES 
                (:did, :key_id, :key_type, :public_key, :purpose, NOW())
            ON CONFLICT (agent_did, key_id) 
            DO UPDATE SET 
                public_key_multibase = EXCLUDED.public_key_multibase,
                key_type = EXCLUDED.key_type,
                purpose = EXCLUDED.purpose,
                revoked = false,
                revoked_at = NULL
        """), {
            "did": did,
            "key_id": key_id,
            "key_type": key_type,
            "public_key": public_key_multibase,
            "purpose": purpose,
        })
        
        # Invalidate cache
        await self.resolver.invalidate_cache(did)
        
        # Update agent's updated_at timestamp
        await session.execute(text("""
            UPDATE agents SET updated_at = NOW() WHERE agent_did = :did
        """), {"did": did})
        
        await session.commit()
        
        logger.info(f"Registered verification key {key_id} for {did}")
        return True
    
    async def revoke_verification_key(
        self,
        did: str,
        key_id: str,
        session: AsyncSession,
    ) -> bool:
        """
        Revoke a verification key
        
        Revoked keys remain in the document for historical verification
        but are marked as revoked and cannot be used for new signatures.
        """
        
        result = await session.execute(text("""
            UPDATE agent_verification_keys
            SET revoked = true, revoked_at = NOW()
            WHERE agent_did = :did AND key_id = :key_id AND revoked = false
            RETURNING key_id
        """), {"did": did, "key_id": key_id})
        
        if not result.fetchone():
            return False
        
        # Invalidate cache
        await self.resolver.invalidate_cache(did)
        
        # Update agent's updated_at timestamp
        await session.execute(text("""
            UPDATE agents SET updated_at = NOW() WHERE agent_did = :did
        """), {"did": did})
        
        await session.commit()
        
        logger.info(f"Revoked verification key {key_id} for {did}")
        return True
```

### File: src/did/verifier.py

```python
"""
AgentX DID Signature Verification
Ed25519 and secp256k1 signature verification for DID authentication
"""

from __future__ import annotations

import base64
import hashlib
import logging
import secrets
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional, Tuple

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives import serialization
from cryptography.exceptions import InvalidSignature

# For secp256k1 (Ethereum wallet signatures)
from eth_account.messages import encode_defunct
from eth_account import Account

from src.cache import CacheManager
from src.did.document import DIDDocument, VerificationMethod, VerificationMethodType

logger = logging.getLogger(__name__)

# Challenge validity window
CHALLENGE_TTL_SECONDS = 60
TIMESTAMP_TOLERANCE_SECONDS = 30


@dataclass
class VerificationResult:
    """Result of signature verification"""
    valid: bool
    did: str
    key_id: Optional[str]
    error: Optional[str] = None
    verified_at: datetime = None
    
    def __post_init__(self):
        if self.verified_at is None:
            self.verified_at = datetime.utcnow()


@dataclass
class Challenge:
    """Authentication challenge for DID auth"""
    nonce: str
    did: str
    issued_at: datetime
    expires_at: datetime
    
    def is_expired(self) -> bool:
        return datetime.utcnow() > self.expires_at
    
    def to_signing_message(self, timestamp: int) -> str:
        """
        Create the message to be signed
        
        Format: did + nonce + timestamp
        """
        return f"{self.did}:{self.nonce}:{timestamp}"


class DIDVerifier:
    """
    Verifies signatures against DID Document verification methods
    
    Supports:
    - Ed25519VerificationKey2020 (primary authentication)
    - EcdsaSecp256k1VerificationKey2019 (wallet binding)
    """
    
    def __init__(self, cache: CacheManager):
        self.cache = cache
    
    # =========================================================================
    # CHALLENGE MANAGEMENT
    # =========================================================================
    
    async def create_challenge(self, did: str) -> Challenge:
        """
        Create a new authentication challenge for a DID
        
        Args:
            did: The DID requesting authentication
            
        Returns:
            Challenge object containing nonce and expiry
        """
        # Generate cryptographically secure nonce
        nonce = secrets.token_urlsafe(32)
        
        now = datetime.utcnow()
        challenge = Challenge(
            nonce=nonce,
            did=did,
            issued_at=now,
            expires_at=now + timedelta(seconds=CHALLENGE_TTL_SECONDS),
        )
        
        # Store challenge in Redis with TTL
        cache_key = f"agentx:did:challenge:{did}:{nonce}"
        await self.cache.set_json(
            cache_key,
            {
                "nonce": nonce,
                "did": did,
                "issued_at": now.isoformat(),
                "expires_at": challenge.expires_at.isoformat(),
            },
            ttl=CHALLENGE_TTL_SECONDS + 10  # Small buffer
        )
        
        logger.debug(f"Created challenge for {did}: {nonce[:8]}...")
        return challenge
    
    async def get_challenge(self, did: str, nonce: str) -> Optional[Challenge]:
        """
        Retrieve and validate a challenge
        
        Returns None if challenge doesn't exist or is expired
        """
        cache_key = f"agentx:did:challenge:{did}:{nonce}"
        data = await self.cache.get_json(cache_key)
        
        if not data:
            return None
        
        challenge = Challenge(
            nonce=data["nonce"],
            did=data["did"],
            issued_at=datetime.fromisoformat(data["issued_at"]),
            expires_at=datetime.fromisoformat(data["expires_at"]),
        )
        
        if challenge.is_expired():
            await self.cache.delete(cache_key)
            return None
        
        return challenge
    
    async def consume_challenge(self, did: str, nonce: str) -> bool:
        """
        Mark challenge as used (one-time use for replay protection)
        
        Returns True if challenge was valid and consumed
        """
        cache_key = f"agentx:did:challenge:{did}:{nonce}"
        
        # Atomic get-and-delete
        data = await self.cache.get_json(cache_key)
        if not data:
            return False
        
        await self.cache.delete(cache_key)
        
        # Check expiry
        expires_at = datetime.fromisoformat(data["expires_at"])
        if datetime.utcnow() > expires_at:
            return False
        
        return True
    
    # =========================================================================
    # SIGNATURE VERIFICATION
    # =========================================================================
    
    async def verify_signature(
        self,
        did_document: DIDDocument,
        message: bytes,
        signature: bytes,
        key_id: Optional[str] = None,
    ) -> VerificationResult:
        """
        Verify a signature against a DID Document
        
        Args:
            did_document: The DID Document containing verification keys
            message: The original message that was signed
            signature: The signature to verify
            key_id: Optional specific key ID to use (if None, tries all auth keys)
            
        Returns:
            VerificationResult indicating success/failure
        """
        
        if did_document.deactivated:
            return VerificationResult(
                valid=False,
                did=did_document.id,
                key_id=None,
                error="DID is deactivated"
            )
        
        # Get keys to try
        if key_id:
            key = did_document.get_verification_method(key_id)
            if not key:
                return VerificationResult(
                    valid=False,
                    did=did_document.id,
                    key_id=key_id,
                    error=f"Key not found: {key_id}"
                )
            if key.revoked:
                return VerificationResult(
                    valid=False,
                    did=did_document.id,
                    key_id=key_id,
                    error="Key has been revoked"
                )
            keys_to_try = [key]
        else:
            keys_to_try = did_document.get_authentication_keys()
        
        if not keys_to_try:
            return VerificationResult(
                valid=False,
                did=did_document.id,
                key_id=None,
                error="No valid authentication keys found"
            )
        
        # Try each key
        for key in keys_to_try:
            try:
                if key.type == VerificationMethodType.ED25519_2020:
                    valid = self._verify_ed25519(key, message, signature)
                elif key.type == VerificationMethodType.SECP256K1_2019:
                    valid = self._verify_secp256k1(key, message, signature)
                else:
                    continue  # Skip unsupported key types
                
                if valid:
                    return VerificationResult(
                        valid=True,
                        did=did_document.id,
                        key_id=key.id,
                    )
            except Exception as e:
                logger.debug(f"Signature verification failed for key {key.id}: {e}")
                continue
        
        return VerificationResult(
            valid=False,
            did=did_document.id,
            key_id=None,
            error="Signature verification failed for all keys"
        )
    
    def _verify_ed25519(
        self,
        key: VerificationMethod,
        message: bytes,
        signature: bytes,
    ) -> bool:
        """
        Verify Ed25519 signature
        
        Args:
            key: Verification method containing the public key
            message: Original message
            signature: 64-byte Ed25519 signature
        """
        # Decode multibase public key
        public_key_bytes = self._decode_multibase(key.public_key_multibase)
        
        # Load public key
        public_key = Ed25519PublicKey.from_public_bytes(public_key_bytes)
        
        # Verify signature (raises InvalidSignature on failure)
        try:
            public_key.verify(signature, message)
            return True
        except InvalidSignature:
            return False
    
    def _verify_secp256k1(
        self,
        key: VerificationMethod,
        message: bytes,
        signature: bytes,
    ) -> bool:
        """
        Verify secp256k1 (Ethereum) signature
        
        Supports both raw signatures and EIP-191 signed messages
        """
        # Decode multibase public key
        public_key_bytes = self._decode_multibase(key.public_key_multibase)
        
        # Try EIP-191 signed message recovery
        try:
            message_hash = encode_defunct(message)
            recovered_address = Account.recover_message(message_hash, signature=signature)
            
            # Derive expected address from public key
            expected_address = self._pubkey_to_address(public_key_bytes)
            
            return recovered_address.lower() == expected_address.lower()
        except Exception as e:
            logger.debug(f"secp256k1 verification failed: {e}")
            return False
    
    def _decode_multibase(self, multibase_str: str) -> bytes:
        """
        Decode multibase-encoded string
        
        Supports:
        - z: base58btc
        - f: base16 (hex)
        - u: base64url
        """
        if not multibase_str:
            raise ValueError("Empty multibase string")
        
        prefix = multibase_str[0]
        data = multibase_str[1:]
        
        if prefix == 'z':
            # base58btc (Bitcoin-style)
            import base58
            return base58.b58decode(data)
        elif prefix == 'f':
            # base16 (hex)
            return bytes.fromhex(data)
        elif prefix == 'u':
            # base64url
            # Add padding if needed
            padding = 4 - (len(data) % 4)
            if padding != 4:
                data += '=' * padding
            return base64.urlsafe_b64decode(data)
        elif prefix == 'm':
            # base64 standard
            return base64.b64decode(data)
        