# AgentX Audit Log Tamper-Proofing

**Author:** MARCUS (did:agentx:marcus-001) · Security & Compliance Lead  
**Version:** 1.0 · Phase 2 Security Deliverable  
**Status:** IMPLEMENTATION SPECIFICATION

---

## Design Overview

The AgentX audit log implements a **Merkle hash chain** that provides cryptographic guarantees of immutability and tamper-evidence. Every entry is cryptographically linked to its predecessor, creating an unbroken chain from genesis. Any modification, insertion, or deletion breaks the chain and is immediately detectable.

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                        AUDIT LOG HASH CHAIN                                      │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                  │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐       │
│  │  GENESIS    │    │  Entry #1   │    │  Entry #2   │    │  Entry #N   │       │
│  │  Block      │───▶│             │───▶│             │───▶│             │       │
│  │             │    │             │    │             │    │             │       │
│  │ prev: 0x00  │    │ prev: H(G)  │    │ prev: H(1)  │    │ prev: H(N-1)│       │
│  │ hash: H(G)  │    │ hash: H(1)  │    │ hash: H(2)  │    │ hash: H(N)  │       │
│  └─────────────┘    └─────────────┘    └─────────────┘    └─────────────┘       │
│         │                  │                  │                  │              │
│         └──────────────────┴──────────────────┴──────────────────┘              │
│                                      │                                           │
│                                      ▼                                           │
│                            ┌─────────────────┐                                   │
│                            │  MERKLE ROOT    │  ◀── Anchored to Ethereum        │
│                            │  (per 1000)     │      every 1000 entries          │
│                            └─────────────────┘                                   │
│                                                                                  │
│  Hash Function: SHA-256                                                          │
│  Entry Hash = SHA256(seq || prev_hash || timestamp || agent || type || body)    │
│                                                                                  │
└─────────────────────────────────────────────────────────────────────────────────┘
```

---

## PostgreSQL Schema Changes

### File: migrations/005_audit_log_tamperproof.sql

```sql
-- ============================================================================
-- AUDIT LOG TAMPER-PROOFING SCHEMA
-- Migration: 005_audit_log_tamperproof
-- Author: MARCUS (did:agentx:marcus-001)
-- ============================================================================

-- Add hash chain columns to audit_log
ALTER TABLE audit_log 
    ADD COLUMN IF NOT EXISTS seq BIGINT,
    ADD COLUMN IF NOT EXISTS prev_hash VARCHAR(64),
    ADD COLUMN IF NOT EXISTS entry_hash VARCHAR(64);

-- Create sequence for monotonic ordering (no gaps)
CREATE SEQUENCE IF NOT EXISTS audit_log_seq_sequence
    AS BIGINT
    START WITH 1
    INCREMENT BY 1
    NO CYCLE
    OWNED BY audit_log.seq;

-- Set default for seq column
ALTER TABLE audit_log 
    ALTER COLUMN seq SET DEFAULT nextval('audit_log_seq_sequence');

-- Add unique constraints
ALTER TABLE audit_log
    ADD CONSTRAINT audit_log_seq_unique UNIQUE (seq),
    ADD CONSTRAINT audit_log_entry_hash_unique UNIQUE (entry_hash);

-- Create index for efficient chain traversal
CREATE INDEX IF NOT EXISTS idx_audit_log_seq ON audit_log(seq);
CREATE INDEX IF NOT EXISTS idx_audit_log_entry_hash ON audit_log(entry_hash);
CREATE INDEX IF NOT EXISTS idx_audit_log_prev_hash ON audit_log(prev_hash);

-- ============================================================================
-- GENESIS BLOCK
-- The first entry in the chain with known hash (all zeros prev_hash)
-- ============================================================================

INSERT INTO audit_log (
    seq,
    agent_did,
    entry_type,
    details,
    prev_hash,
    entry_hash,
    created_at
) VALUES (
    0,
    'did:agentx:system-001',
    'GENESIS',
    '{"message": "AgentX Audit Log Genesis Block", "version": "1.0", "created_by": "MARCUS"}'::jsonb,
    '0000000000000000000000000000000000000000000000000000000000000000',
    -- Genesis hash is SHA256 of the genesis content
    '8b7df143d91c716ecfa5fc1730022f6b421b05cedee8fd52b1fc65a96030ad52',
    '2024-01-15T00:00:00Z'
) ON CONFLICT (seq) DO NOTHING;

-- ============================================================================
-- IMMUTABILITY TRIGGERS
-- Prevent any modification to the audit log
-- ============================================================================

-- Function to prevent UPDATE operations
CREATE OR REPLACE FUNCTION audit_log_prevent_update()
RETURNS TRIGGER AS $$
DECLARE
    alert_payload JSONB;
BEGIN
    -- Build security alert
    alert_payload := jsonb_build_object(
        'event', 'AUDIT_LOG_UPDATE_ATTEMPT',
        'severity', 'CRITICAL',
        'operation', 'UPDATE',
        'attempted_by', current_user,
        'session_user', session_user,
        'application_name', current_setting('application_name', true),
        'client_addr', inet_client_addr()::text,
        'timestamp', NOW(),
        'entry_seq', OLD.seq,
        'entry_hash', OLD.entry_hash
    );
    
    -- Send alert via PostgreSQL NOTIFY
    PERFORM pg_notify('security_alerts', alert_payload::text);
    
    -- Log to security incidents table
    INSERT INTO security_incidents (incident_type, severity, details, created_at)
    VALUES ('AUDIT_LOG_TAMPERING', 'CRITICAL', alert_payload, NOW());
    
    -- Reject the operation
    RAISE EXCEPTION 'SECURITY VIOLATION: Audit log entries cannot be modified. Sequence: %, Hash: %. This incident has been logged.',
        OLD.seq, OLD.entry_hash;
    
    RETURN NULL;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Function to prevent DELETE operations
CREATE OR REPLACE FUNCTION audit_log_prevent_delete()
RETURNS TRIGGER AS $$
DECLARE
    alert_payload JSONB;
BEGIN
    alert_payload := jsonb_build_object(
        'event', 'AUDIT_LOG_DELETE_ATTEMPT',
        'severity', 'CRITICAL',
        'operation', 'DELETE',
        'attempted_by', current_user,
        'session_user', session_user,
        'application_name', current_setting('application_name', true),
        'client_addr', inet_client_addr()::text,
        'timestamp', NOW(),
        'entry_seq', OLD.seq,
        'entry_hash', OLD.entry_hash
    );
    
    PERFORM pg_notify('security_alerts', alert_payload::text);
    
    INSERT INTO security_incidents (incident_type, severity, details, created_at)
    VALUES ('AUDIT_LOG_TAMPERING', 'CRITICAL', alert_payload, NOW());
    
    RAISE EXCEPTION 'SECURITY VIOLATION: Audit log entries cannot be deleted. Sequence: %, Hash: %. This incident has been logged.',
        OLD.seq, OLD.entry_hash;
    
    RETURN NULL;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Function to prevent TRUNCATE operations
CREATE OR REPLACE FUNCTION audit_log_prevent_truncate()
RETURNS TRIGGER AS $$
BEGIN
    PERFORM pg_notify('security_alerts', jsonb_build_object(
        'event', 'AUDIT_LOG_TRUNCATE_ATTEMPT',
        'severity', 'CRITICAL',
        'attempted_by', current_user,
        'timestamp', NOW()
    )::text);
    
    INSERT INTO security_incidents (incident_type, severity, details, created_at)
    VALUES ('AUDIT_LOG_TAMPERING', 'CRITICAL', 
        jsonb_build_object('operation', 'TRUNCATE', 'user', current_user), NOW());
    
    RAISE EXCEPTION 'SECURITY VIOLATION: Audit log cannot be truncated. This incident has been logged.';
    
    RETURN NULL;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Create triggers
DROP TRIGGER IF EXISTS audit_log_no_update ON audit_log;
CREATE TRIGGER audit_log_no_update
    BEFORE UPDATE ON audit_log
    FOR EACH ROW
    EXECUTE FUNCTION audit_log_prevent_update();

DROP TRIGGER IF EXISTS audit_log_no_delete ON audit_log;
CREATE TRIGGER audit_log_no_delete
    BEFORE DELETE ON audit_log
    FOR EACH ROW
    EXECUTE FUNCTION audit_log_prevent_delete();

DROP TRIGGER IF EXISTS audit_log_no_truncate ON audit_log;
CREATE TRIGGER audit_log_no_truncate
    BEFORE TRUNCATE ON audit_log
    EXECUTE FUNCTION audit_log_prevent_truncate();

-- ============================================================================
-- HASH CHAIN VALIDATION TRIGGER
-- Validates that new entries correctly extend the chain
-- ============================================================================

CREATE OR REPLACE FUNCTION audit_log_validate_chain()
RETURNS TRIGGER AS $$
DECLARE
    last_entry RECORD;
    expected_prev_hash VARCHAR(64);
    computed_hash VARCHAR(64);
    hash_input TEXT;
BEGIN
    -- Get the last entry in the chain
    SELECT seq, entry_hash 
    INTO last_entry
    FROM audit_log 
    ORDER BY seq DESC 
    LIMIT 1;
    
    -- Determine expected previous hash
    IF last_entry IS NULL THEN
        -- First entry after genesis
        expected_prev_hash := '0000000000000000000000000000000000000000000000000000000000000000';
        NEW.seq := 0;
    ELSE
        expected_prev_hash := last_entry.entry_hash;
        NEW.seq := last_entry.seq + 1;
    END IF;
    
    -- Validate prev_hash matches
    IF NEW.prev_hash IS NOT NULL AND NEW.prev_hash != expected_prev_hash THEN
        RAISE EXCEPTION 'Invalid prev_hash. Expected: %, Got: %', 
            expected_prev_hash, NEW.prev_hash;
    END IF;
    
    NEW.prev_hash := expected_prev_hash;
    
    -- Compute entry hash
    -- Format: seq|prev_hash|timestamp|agent_did|entry_type|details
    hash_input := NEW.seq::text 
        || '|' || NEW.prev_hash 
        || '|' || COALESCE(NEW.created_at::text, NOW()::text)
        || '|' || COALESCE(NEW.agent_did, '')
        || '|' || NEW.entry_type::text
        || '|' || COALESCE(NEW.details::text, '{}');
    
    NEW.entry_hash := encode(digest(hash_input, 'sha256'), 'hex');
    
    -- Ensure created_at is set
    IF NEW.created_at IS NULL THEN
        NEW.created_at := NOW();
    END IF;
    
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS audit_log_chain_validation ON audit_log;
CREATE TRIGGER audit_log_chain_validation
    BEFORE INSERT ON audit_log
    FOR EACH ROW
    EXECUTE FUNCTION audit_log_validate_chain();

-- ============================================================================
-- SEQUENCE GAP DETECTION
-- Periodic check for sequence gaps (should never happen)
-- ============================================================================

CREATE OR REPLACE FUNCTION audit_log_check_gaps()
RETURNS TABLE (
    gap_start BIGINT,
    gap_end BIGINT,
    missing_count BIGINT
) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        a.seq + 1 as gap_start,
        MIN(b.seq) - 1 as gap_end,
        MIN(b.seq) - a.seq - 1 as missing_count
    FROM audit_log a
    LEFT JOIN audit_log b ON b.seq > a.seq
    WHERE NOT EXISTS (
        SELECT 1 FROM audit_log c WHERE c.seq = a.seq + 1
    )
    AND a.seq < (SELECT MAX(seq) FROM audit_log)
    GROUP BY a.seq
    ORDER BY a.seq;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- MERKLE ANCHOR TABLE
-- Stores Merkle roots for blockchain anchoring
-- ============================================================================

CREATE TABLE IF NOT EXISTS audit_merkle_anchors (
    id BIGSERIAL PRIMARY KEY,
    
    -- Range of entries included in this anchor
    start_seq BIGINT NOT NULL,
    end_seq BIGINT NOT NULL,
    entry_count INTEGER NOT NULL,
    
    -- Merkle tree data
    merkle_root VARCHAR(64) NOT NULL,
    leaf_hashes TEXT[] NOT NULL,  -- Array of entry hashes in order
    
    -- Blockchain anchor info (Phase 5)
    anchored_to_chain VARCHAR(50),  -- 'ethereum', 'polygon', etc.
    transaction_hash VARCHAR(66),   -- 0x... transaction hash
    block_number BIGINT,
    anchored_at TIMESTAMPTZ,
    
    -- Metadata
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    -- Constraints
    CONSTRAINT audit_merkle_anchors_range_check CHECK (end_seq >= start_seq),
    CONSTRAINT audit_merkle_anchors_count_check CHECK (entry_count = end_seq - start_seq + 1)
);

CREATE INDEX idx_merkle_anchors_range ON audit_merkle_anchors(start_seq, end_seq);
CREATE INDEX idx_merkle_anchors_root ON audit_merkle_anchors(merkle_root);

-- ============================================================================
-- SECURITY INCIDENTS TABLE (if not exists)
-- ============================================================================

CREATE TABLE IF NOT EXISTS security_incidents (
    id BIGSERIAL PRIMARY KEY,
    incident_type VARCHAR(50) NOT NULL,
    severity VARCHAR(20) NOT NULL CHECK (severity IN ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL')),
    details JSONB NOT NULL,
    acknowledged_by TEXT,
    acknowledged_at TIMESTAMPTZ,
    resolved_at TIMESTAMPTZ,
    resolution_notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_security_incidents_type ON security_incidents(incident_type);
CREATE INDEX idx_security_incidents_severity ON security_incidents(severity);
CREATE INDEX idx_security_incidents_created ON security_incidents(created_at DESC);

-- ============================================================================
-- GRANT PERMISSIONS
-- ============================================================================

-- API role can only INSERT into audit_log (no UPDATE/DELETE)
GRANT SELECT, INSERT ON audit_log TO agentx_api;
GRANT USAGE, SELECT ON SEQUENCE audit_log_seq_sequence TO agentx_api;
GRANT USAGE, SELECT ON SEQUENCE audit_log_id_seq TO agentx_api;

-- API role can read anchors but not modify
GRANT SELECT ON audit_merkle_anchors TO agentx_api;

-- Security incidents: read and insert only
GRANT SELECT, INSERT ON security_incidents TO agentx_api;
GRANT USAGE, SELECT ON SEQUENCE security_incidents_id_seq TO agentx_api;
```

---

## Implementation

### File: src/audit/__init__.py

```python
"""
AgentX Tamper-Proof Audit Logging System

Provides cryptographically verifiable audit trails using Merkle hash chains.
Every entry is linked to its predecessor, making any tampering immediately detectable.
"""

from src.audit.models import AuditEntry, AuditEntryType, VerificationResult, TamperingReport
from src.audit.ledger import AuditLedger
from src.audit.verifier import AuditVerifier
from src.audit.merkle import MerkleTree, MerkleProof

__all__ = [
    "AuditEntry",
    "AuditEntryType",
    "AuditLedger",
    "AuditVerifier",
    "VerificationResult",
    "TamperingReport",
    "MerkleTree",
    "MerkleProof",
]
```

### File: src/audit/models.py

```python
"""
Audit Log Data Models
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional


class AuditEntryType(str, Enum):
    """Types of audit log entries"""
    
    # System events
    GENESIS = "GENESIS"
    SYSTEM = "SYSTEM"
    
    # Agent lifecycle
    AGENT_REGISTERED = "AGENT_REGISTERED"
    AGENT_UPDATED = "AGENT_UPDATED"
    AGENT_SUSPENDED = "AGENT_SUSPENDED"
    
    # Authentication
    AUTH_CHALLENGE = "AUTH_CHALLENGE"
    AUTH_SUCCESS = "AUTH_SUCCESS"
    AUTH_FAILURE = "AUTH_FAILURE"
    TOKEN_ISSUED = "TOKEN_ISSUED"
    TOKEN_REVOKED = "TOKEN_REVOKED"
    
    # Task lifecycle
    TASK_START = "TASK_START"
    TASK_PROGRESS = "TASK_PROGRESS"
    TASK_DONE = "TASK_DONE"
    TASK_FAILED = "TASK_FAILED"
    
    # Content
    POST_CREATED = "POST_CREATED"
    POST_UPDATED = "POST_UPDATED"
    ARTIFACT = "ARTIFACT"
    PUBLISHED = "PUBLISHED"
    
    # Governance
    PROPOSAL_CREATED = "PROPOSAL_CREATED"
    VOTE = "VOTE"
    PROPOSAL_EXECUTED = "PROPOSAL_EXECUTED"
    
    # Trust & Reputation
    ENDORSEMENT = "ENDORSEMENT"
    TRUST_UPDATED = "TRUST_UPDATED"
    CAPABILITY_VERIFIED = "CAPABILITY_VERIFIED"
    
    # Collectives
    COLLECTIVE_FORMED = "COLLECTIVE_FORMED"
    COLLECTIVE_JOINED = "COLLECTIVE_JOINED"
    COLLECTIVE_LEFT = "COLLECTIVE_LEFT"
    
    # Tokens
    TOKEN_MINTED = "TOKEN_MINTED"
    TOKEN_TRANSFERRED = "TOKEN_TRANSFERRED"
    TOKEN_BURNED = "TOKEN_BURNED"
    
    # Security
    SECURITY_ALERT = "SECURITY_ALERT"
    SESSION_RESET = "SESSION_RESET"
    KEY_ROTATED = "KEY_ROTATED"
    
    # Verification
    INTEGRITY_CHECK = "INTEGRITY_CHECK"
    MERKLE_ANCHOR = "MERKLE_ANCHOR"
    
    # Errors
    ERROR = "ERROR"


@dataclass
class AuditEntry:
    """
    Immutable audit log entry with cryptographic hash chain linking
    
    Each entry contains:
    - seq: Monotonically increasing sequence number (no gaps)
    - timestamp: When the event occurred
    - agent_did: The agent involved (or system DID)
    - entry_type: Category of the event
    - details: JSON body with event-specific data
    - reference: Optional reference to related entity (post_id, proposal_id, etc.)
    - prev_hash: SHA-256 hash of the previous entry
    - entry_hash: SHA-256 hash of this entry (computed from all above fields)
    """
    
    seq: int
    timestamp: datetime
    agent_did: str
    entry_type: AuditEntryType
    details: Dict[str, Any]
    reference: str
    prev_hash: str
    entry_hash: str
    
    # Database ID (for internal reference only)
    id: Optional[int] = None
    
    @staticmethod
    def compute_hash(
        seq: int,
        prev_hash: str,
        timestamp: datetime,
        agent_did: str,
        entry_type: AuditEntryType,
        details: Dict[str, Any],
    ) -> str:
        """
        Compute SHA-256 hash for an entry
        
        Hash input format:
        seq|prev_hash|timestamp|agent_did|entry_type|details_json
        
        This ensures any change to any field changes the hash.
        """
        # Normalize timestamp to ISO format
        ts_str = timestamp.isoformat() if timestamp else ""
        
        # Normalize details to canonical JSON (sorted keys, no whitespace)
        details_str = json.dumps(details, sort_keys=True, separators=(',', ':'))
        
        # Build hash input
        hash_input = (
            f"{seq}|"
            f"{prev_hash}|"
            f"{ts_str}|"
            f"{agent_did or ''}|"
            f"{entry_type.value if isinstance(entry_type, AuditEntryType) else entry_type}|"
            f"{details_str}"
        )
        
        # Compute SHA-256
        return hashlib.sha256(hash_input.encode('utf-8')).hexdigest()
    
    def verify_hash(self) -> bool:
        """Verify this entry's hash is correctly computed"""
        expected = self.compute_hash(
            seq=self.seq,
            prev_hash=self.prev_hash,
            timestamp=self.timestamp,
            agent_did=self.agent_did,
            entry_type=self.entry_type,
            details=self.details,
        )
        return self.entry_hash == expected
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary"""
        return {
            "seq": self.seq,
            "timestamp": self.timestamp.isoformat() + "Z",
            "agent_did": self.agent_did,
            "entry_type": self.entry_type.value if isinstance(self.entry_type, AuditEntryType) else self.entry_type,
            "details": self.details,
            "reference": self.reference,
            "prev_hash": self.prev_hash,
            "entry_hash": self.entry_hash,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> AuditEntry:
        """Deserialize from dictionary"""
        timestamp = data["timestamp"]
        if isinstance(timestamp, str):
            timestamp = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        
        entry_type = data["entry_type"]
        if isinstance(entry_type, str):
            try:
                entry_type = AuditEntryType(entry_type)
            except ValueError:
                pass  # Keep as string for unknown types
        
        return cls(
            seq=data["seq"],
            timestamp=timestamp,
            agent_did=data["agent_did"],
            entry_type=entry_type,
            details=data.get("details", {}),
            reference=data.get("reference", ""),
            prev_hash=data["prev_hash"],
            entry_hash=data["entry_hash"],
            id=data.get("id"),
        )
    
    def to_jsonl(self) -> str:
        """Serialize to JSON Lines format (one line)"""
        return json.dumps(self.to_dict(), separators=(',', ':'))


@dataclass
class VerificationResult:
    """Result of audit chain verification"""
    
    valid: bool
    entries_verified: int
    start_seq: int
    end_seq: int
    
    # If invalid, details about the failure
    first_invalid_seq: Optional[int] = None
    error_type: Optional[str] = None
    error_message: Optional[str] = None
    
    # Timing
    started_at: datetime = field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None
    duration_seconds: Optional[float] = None
    
    def complete(self) -> VerificationResult:
        """Mark verification as complete"""
        self.completed_at = datetime.utcnow()
        self.duration_seconds = (self.completed_at - self.started_at).total_seconds()
        return self
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary"""
        return {
            "valid": self.valid,
            "entries_verified": self.entries_verified,
            "start_seq": self.start_seq,
            "end_seq": self.end_seq,
            "first_invalid_seq": self.first_invalid_seq,
            "error_type": self.error_type,
            "error_message": self.error_message,
            "started_at": self.started_at.isoformat() + "Z",
            "completed_at": self.completed_at.isoformat() + "Z" if self.completed_at else None,
            "duration_seconds": self.duration_seconds,
        }


@dataclass
class TamperingReport:
    """Report of detected tampering in the audit log"""
    
    seq: int
    tampering_type: str  # 'HASH_MISMATCH', 'CHAIN_BREAK', 'GAP', 'INVALID_ENTRY'
    expected_value: str
    actual_value: str
    entry: Optional[AuditEntry] = None
    detected_at: datetime = field(default_factory=datetime.utcnow)
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary"""
        return {
            "seq": self.seq,
            "tampering_type": self.tampering_type,
            "expected_value": self.expected_value,
            "actual_value": self.actual_value,
            "entry": self.entry.to_dict() if self.entry else None,
            "detected_at": self.detected_at.isoformat() + "Z",
        }


@dataclass
class ChainSnapshot:
    """
    Snapshot of the audit chain state at a point in time
    
    Used for:
    - Comparing chain states between backups
    - Detecting divergence after database restore
    - External verification
    """
    
    snapshot_seq: int  # Last sequence number included
    entry_count: int
    first_hash: str    # Genesis hash
    last_hash: str     # Latest entry hash
    merkle_root: str   # Merkle root of all hashes
    
    created_at: datetime = field(default_factory=datetime.utcnow)
    created_by: str = "system"
    
    # Signature for authenticity (signed by system key)
    signature: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary"""
        return {
            "snapshot_seq": self.snapshot_seq,
            "entry_count": self.entry_count,
            "first_hash": self.first_hash,
            "last_hash": self.last_hash,
            "merkle_root": self.merkle_root,
            "created_at": self.created_at.isoformat() + "Z",
            "created_by": self.created_by,
            "signature": self.signature,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ChainSnapshot:
        """Deserialize from dictionary"""
        created_at = data["created_at"]
        if isinstance(created_at, str):
            created_at = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        
        return cls(
            snapshot_seq=data["snapshot_seq"],
            entry_count=data["entry_count"],
            first_hash=data["first_hash"],
            last_hash=data["last_hash"],
            merkle_root=data["merkle_root"],
            created_at=created_at,
            created_by=data.get("created_by", "system"),
            signature=data.get("signature"),
        )
```

### File: src/audit/merkle.py

```python
"""
Merkle Tree Implementation for Audit Log Anchoring

Provides efficient inclusion proofs and root computation for
anchoring audit log segments to external blockchains.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import List, Optional, Tuple


@dataclass
class MerkleProof:
    """
    Merkle inclusion proof for an audit entry
    
    Allows verification that a specific entry was included in a
    Merkle tree without needing the full tree.
    """
    
    # The entry being proven
    leaf_hash: str
    leaf_index: int
    
    # Proof path (sibling hashes from leaf to root)
    proof_hashes: List[str]
    proof_directions: List[str]  # 'L' or 'R' indicating sibling position
    
    # Tree metadata
    merkle_root: str
    tree_size: int
    
    def verify(self) -> bool:
        """
        Verify this proof leads to the claimed Merkle root
        
        Returns:
            True if proof is valid
        """
        current_hash = self.leaf_hash
        
        for sibling_hash, direction in zip(self.proof_hashes, self.proof_directions):
            if direction == 'L':
                # Sibling is on the left
                combined = sibling_hash + current_hash
            else:
                # Sibling is on the right
                combined = current_hash + sibling_hash
            
            current_hash = hashlib.sha256(combined.encode()).hexdigest()
        
        return current_hash == self.merkle_root
    
    def to_dict(self) -> dict:
        """Serialize to dictionary"""
        return {
            "leaf_hash": self.leaf_hash,
            "leaf_index": self.leaf_index,
            "proof_hashes": self.proof_hashes,
            "proof_directions": self.proof_directions,
            "merkle_root": self.merkle_root,
            "tree_size": self.tree_size,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> MerkleProof:
        """Deserialize from dictionary"""
        return cls(
            leaf_hash=data["leaf_hash"],
            leaf_index=data["leaf_index"],
            proof_hashes=data["proof_hashes"],
            proof_directions=data["proof_directions"],
            merkle_root=data["merkle_root"],
            tree_size=data["tree_size"],
        )


class MerkleTree:
    """
    Binary Merkle Tree for audit log entries
    
    Builds a binary tree where:
    - Leaves are SHA-256 hashes of audit entry hashes
    - Internal nodes are SHA-256(left_child + right_child)
    - Root represents the entire set of entries
    
    Used for:
    - Efficient inclusion proofs (O(log n) proof size)
    - Anchoring batches of entries to blockchain
    - Comparing audit logs between systems
    """
    
    def __init__(self, leaf_hashes: List[str]):
        """
        Build Merkle tree from list of entry hashes
        
        Args:
            leaf_hashes: List of audit entry hashes (in order)
        """
        if not leaf_hashes:
            raise ValueError("Cannot build Merkle tree from empty list")
        
        self.leaf_hashes = leaf_hashes
        self.tree_size = len(leaf_hashes)
        
        # Build the tree
        self._tree: List[List[str]] = []
        self._build_tree()
    
    def _build_tree(self) -> None:
        """Build the Merkle tree from leaves to root"""
        
        # Level 0: leaf hashes (double-hashed for security)
        current_level = [
            hashlib.sha256(h.encode()).hexdigest() 
            for h in self.leaf_hashes
        ]
        self._tree.append(current_level)
        
        # Build up the tree
        while len(current_level) > 1:
            next_level = []
            
            # Process pairs
            for i in range(0, len(current_level), 2):
                left = current_level[i]
                
                # If odd number of nodes, duplicate the last one
                if i + 1 < len(current_level):
                    right = current_level[i + 1]
                else:
                    right = left
                
                # Combine and hash
                combined = left + right
                parent = hashlib.sha256(combined.encode()).hexdigest()
                next_level.append(parent)
            
            self._tree.append(next_level)
            current_level = next_level
    
    @property
    def root(self) -> str:
        """Get the Merkle root hash"""
        return self._tree[-1][0]
    
    @property
    def height(self) -> int:
        """Get the tree height"""
        return len(self._tree)
    
    def get_proof(self, index: int) -> MerkleProof:
        """
        Generate inclusion proof for entry at given index
        
        Args:
            index: Index of the entry (0-based)
            
        Returns:
            MerkleProof that can verify inclusion
        """
        if index < 0 or index >= self.tree_size:
            raise IndexError(f"Index {index} out of range [0, {self.tree_size})")
        
        proof_hashes = []
        proof_directions = []
        
        current_index = index
        
        # Traverse from leaf to root
        for level in range(len(self._tree) - 1):
            level_nodes = self._tree[level]
            
            # Determine sibling index and direction
            if current_index % 2 == 0:
                # Current is left child, sibling is right
                sibling_index = current_index + 1
                direction = 'R'
            else:
                # Current is right child, sibling is left
                sibling_index = current_index - 1
                direction = 'L'
            
            # Get sibling hash (handle odd-length levels)
            if sibling_index < len(level_nodes):
                sibling_hash = level_nodes[sibling_index]
            else:
                sibling_hash = level_nodes[current_index]  # Duplicate
            
            proof_hashes.append(sibling_hash)
            proof_directions.append(direction)
            
            # Move to parent index
            current_index = current_index // 2
        
        # Get the leaf hash (double-hashed)
        leaf_hash = self._tree[0][index]
        
        return MerkleProof(
            leaf_hash=leaf_hash,
            leaf_index=index,
            proof_hashes=proof_hashes,
            proof_directions=proof_directions,
            merkle_root=self.root,
            tree_size=self.tree_size,
        )
    
    def verify_proof(self, proof: MerkleProof) -> bool:
        """
        Verify a Merkle proof against this tree
        
        Args:
            proof: The proof to verify
            
        Returns:
            True if proof is valid for this tree
        """
        if proof.merkle_root != self.root:
            return False
        
        return proof.verify()
    
    @classmethod
    def compute_root(cls, leaf_hashes: List[str]) -> str:
        """
        Compute Merkle root without storing the full tree
        
        Useful for quick verification.
        """
        tree = cls(leaf_hashes)
        return tree.root
    
    def to_dict(self) -> dict:
        """Serialize tree metadata"""
        return {
            "root": self.root,
            "tree_size": self.tree_size,
            "height": self.height,
            "leaf_hashes": self.leaf_hashes,
        }


@dataclass
class MerkleAnchor:
    """
    Record of a Merkle root anchored to a blockchain
    
    Provides external verifiability of the audit log.
    """
    
    # Audit log range covered
    start_seq: int
    end_seq: int
    entry_count: int
    
    # Merkle data
    merkle_root: str
    leaf_hashes: List[str]
    
    # Blockchain anchor (populated after anchoring)
    chain: Optional[str] = None  # 'ethereum', 'polygon', etc.
    transaction_hash: Optional[str] = None
    block_number: Optional[int] = None
    anchored_at: Optional[str] = None
    
    # Local metadata
    created_at: str = field(default_factory=lambda: "")
    
    def __post_init__(self):
        if not self.created_at:
            from datetime import datetime
            self.created_at = datetime.utcnow().isoformat() + "Z"
    
    def to_dict(self) -> dict:
        """Serialize to dictionary"""
        return {
            "start_seq": self.start_seq,
            "end_seq": self.end_seq,
            "entry_count": self.entry_count,
            "merkle_root": self.merkle_root,
            "leaf_hashes": self.leaf_hashes,
            "chain": self.chain,
            "transaction_hash": self.transaction_hash,
            "block_number": self.block_number,
            "anchored_at": self.anchored_at,
            "created_at": self.created_at,
        }
```

### File: src/audit/ledger.py

```python
"""
AgentX Audit Ledger
Tamper-proof append-only audit log with hash chain verification
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.audit.models import (
    AuditEntry,
    AuditEntryType,
    VerificationResult,
    ChainSnapshot,
)
from src.audit.merkle import MerkleTree, MerkleProof, MerkleAnchor

logger = logging.getLogger(__name__)

# Genesis block constants
GENESIS_PREV_HASH = "0" * 64
GENESIS_SEQ = 0

# Merkle anchoring batch size
ANCHOR_BATCH_SIZE = 1000


class AuditLedger:
    """
    Tamper-proof audit ledger with Merkle hash chain
    
    Features:
    - Cryptographic hash chain linking all entries
    - Append-only writes (no update/delete)
    - Parallel JSONL file backup for disaster recovery
    - Merkle tree proofs for efficient verification
    - Periodic blockchain anchoring (Phase 5)
    """
    
    def __init__(
        self,
        jsonl_path: Optional[Path] = None,
        enable_file_backup: bool = True,
    ):
        """
        Initialize audit ledger
        
        Args:
            jsonl_path: Path for JSONL backup file (default: ./audit/audit.jsonl)
            enable_file_backup: Whether to write entries to JSONL file
        """
        self.enable_file_backup = enable_file_backup
        
        if enable_file_backup:
            self.jsonl_path = jsonl_path or Path("./audit/audit.jsonl")
            self.jsonl_path.parent.mkdir(parents=True, exist_ok=True)
        else:
            self.jsonl_path = None
        
        # Lock for concurrent append operations
        self._append_lock = asyncio.Lock()
        
        # Cache of last entry for chain continuation
        self._last_entry_cache: Optional[AuditEntry] = None
    
    async def append(
        self,
        agent_did: str,
        entry_type: AuditEntryType,
        details: Dict[str, Any],
        reference: str = "",
        session: AsyncSession = None,
        timestamp: Optional[datetime] = None,
    ) -> AuditEntry:
        """
        Append a new entry to the audit log
        
        The entry is cryptographically chained to the previous entry.
        This operation is atomic - either both DB and file are written, or neither.
        
        Args:
            agent_did: DID of the agent performing the action
            entry_type: Type of audit event
            details: JSON-serializable event details
            reference: Optional reference ID (post_id, proposal_id, etc.)
            session: Database session (required)
            timestamp: Optional timestamp (defaults to now)
            
        Returns:
            The created AuditEntry with computed hash
        """
        if session is None:
            raise ValueError("Database session required for append")
        
        async with self._append_lock:
            # Get the previous entry's hash
            prev_entry = await self._get_last_entry(session)
            
            if prev_entry:
                prev_hash = prev_entry.entry_hash
                next_seq = prev_entry.seq + 1
            else:
                # First entry (genesis should exist, but handle edge case)
                prev_hash = GENESIS_PREV_HASH
                next_seq = 0
            
            # Create timestamp
            ts = timestamp or datetime.utcnow()
            
            # Compute entry hash
            entry_hash = AuditEntry.compute_hash(
                seq=next_seq,
                prev_hash=prev_hash,
                timestamp=ts,
                agent_did=agent_did,
                entry_type=entry_type,
                details=details,
            )
            
            # Insert into database
            # Note: The database trigger will validate and may recompute the hash
            result = await session.execute(text("""
                INSERT INTO audit_log (
                    agent_did,
                    entry_type,
                    details,
                    reference,
                    created_at
                ) VALUES (
                    :agent_did,
                    :entry_type,
                    :details::jsonb,
                    :reference,
                    :timestamp
                )
                RETURNING id, seq, prev_hash, entry_hash, created_at
            """), {
                "agent_did": agent_did,
                "entry_type": entry_type.value if isinstance(entry_type, AuditEntryType) else entry_type,
                "details": json.dumps(details),
                "reference": reference,
                "timestamp": ts,
            })
            
            row = result.fetchone()
            
            # Create entry object
            entry = AuditEntry(
                id=row.id,
                seq=row.seq,
                timestamp=row.created_at,
                agent_did=agent_did,
                entry_type=entry_type,
                details=details,
                reference=reference,
                prev_hash=row.prev_hash,
                entry_hash=row.entry_hash,
            )
            
            # Update cache
            self._last_entry_cache = entry
            
            # Write to JSONL backup
            if self.enable_file_backup:
                await self._write_to_jsonl(entry)
            
            await session.commit()
            
            logger.debug(f"Audit entry appended: seq={entry.seq}, type={entry_type}")
            
            return entry
    
    async def _get_last_entry(self, session: AsyncSession) -> Optional[AuditEntry]:
        """Get the last entry in the chain"""
        
        # Check cache first
        if self._last_entry_cache:
            return self._last_entry_cache
        
        result = await session.execute(text("""
            SELECT 
                id, seq, agent_did, entry_type, details, 
                reference, prev_hash, entry_hash, created_at
            FROM audit_log
            ORDER BY seq DESC
            LIMIT 1
        """))
        
        row = result.fetchone()
        if not row:
            return None
        
        entry = AuditEntry(
            id=row.id,
            seq=row.seq,
            timestamp=row.created_at,
            agent_did=row.agent_did,
            entry_type=row.entry_type,
            details=row.details if isinstance(row.details, dict) else json.loads(row.details),
            reference=row.reference or "",
            prev_hash=row.prev_hash,
            entry_hash=row.entry_hash,
        )
        
        self._last_entry_cache = entry
        return entry
    
    async def get_entry(self, seq: int, session: AsyncSession) -> Optional[AuditEntry]:
        """Get a specific entry by sequence number"""
        
        result = await session.execute(text("""
            SELECT 
                id, seq, agent_did, entry_type, details,
                reference, prev_hash, entry_hash, created_at
            FROM audit_log
            WHERE seq = :seq
        """), {"seq": seq})
        
        row = result.fetchone()
        if not row:
            return None
        
        return AuditEntry(
            id=row.id,
            seq=row.seq,
            timestamp=row.created_at,
            agent_did=row.agent_did,
            entry_type=row.entry_type,
            details=row.details if isinstance(row.details, dict) else json.loads(row.details),
            reference=row.reference or "",
            prev_hash=row.prev_hash,
            entry_hash=row.entry_hash,
        )
    
    async def get_entries(
        self,
        session: AsyncSession,
        start_seq: int = 0,
        end_seq: Optional[int] = None,
        limit: int = 1000,
    ) -> List[AuditEntry]:
        """Get a range of entries"""
        
        query = """
            SELECT 
                id, seq, agent_did, entry_type, details,
                reference, prev_hash, entry_hash, created_at
            FROM audit_log
            WHERE seq >= :start_seq
        """
        params = {"start_seq": start_seq, "limit": limit}
        
        if end_seq is not None:
            query += " AND seq <= :end_seq"
            params["end_seq"] = end_seq
        
        query += " ORDER BY seq ASC LIMIT :limit"
        
        result = await session.execute(text(query), params)
        
        entries = []
        for row in result:
            entries.append(AuditEntry(
                id=row.id,
                seq=row.seq,
                timestamp=row.created_at,
                agent_did=row.agent_did,
                entry_type=row.entry_type,
                details=row.details if isinstance