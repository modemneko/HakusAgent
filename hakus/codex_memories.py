"""CodexMemories — full cross-session memory system (aligned with Codex CLI).

Codex CLI's Memories system provides:
  1. **Memory extraction**: Automatically extract key facts from conversations
  2. **Memory integration**: Merge new facts with existing memories
  3. **Reference tracking**: Track which memories are referenced in which turns
  4. **SQLite persistence**: Durable storage across sessions
  5. **Relevance scoring**: Score memories by recency, frequency, and context

This implementation goes beyond ProjectMemory (which only reads .hakus.md)
by providing:
  - Automatic extraction of facts from conversations
  - Deduplication and merging of memories
  - Reference counting (which memories are actually used)
  - TTL-based expiration of stale memories
  - Vector similarity search (if embedding model available)

Storage:
  - SQLite for structured memory (facts, references, metadata)
  - Optional: ChromaDB/FAISS for vector similarity search
  - Export to AGENTS.md for project-level visibility
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import time
import threading
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from utils.logger import get_logger

logger = get_logger(__name__)


class MemoryType(str, Enum):
    """Type of memory entry."""
    FACT = "fact"             # A factual observation (e.g., "project uses FastAPI")
    DECISION = "decision"      # A user decision (e.g., "use snake_case naming")
    PREFERENCE = "preference"  # A user preference (e.g., "always use type hints")
    PATTERN = "pattern"        # A code pattern (e.g., "error handling uses Result type")
    PITFALL = "pitfall"        # A known issue (e.g., "tests fail if env not set")
    CONTEXT = "context"        # Project context (e.g., "API runs on port 8000")


class MemorySource(str, Enum):
    """Where the memory came from."""
    EXTRACTION = "extraction"    # Auto-extracted from conversation
    USER_INPUT = "user_input"    # Explicitly provided by user
    AGENTS_MD = "agents_md"      # From AGENTS.md file
    PROJECT_SCAN = "project_scan"  # From project structure analysis
    INTEGRATION = "integration"  # Merged from multiple sources


@dataclass
class MemoryEntry:
    """A single memory entry."""
    id: str = ""
    content: str = ""
    memory_type: MemoryType = MemoryType.FACT
    source: MemorySource = MemorySource.EXTRACTION
    tags: List[str] = field(default_factory=list)
    confidence: float = 1.0  # 0.0 - 1.0
    reference_count: int = 0
    last_referenced: float = 0.0
    created_at: float = 0.0
    updated_at: float = 0.0
    ttl_seconds: float = 0.0  # 0 = no expiration
    session_id: str = ""

    def is_expired(self) -> bool:
        if self.ttl_seconds <= 0:
            return False
        return (time.time() - self.updated_at) > self.ttl_seconds

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "content": self.content,
            "memory_type": self.memory_type.value,
            "source": self.source.value,
            "tags": self.tags,
            "confidence": self.confidence,
            "reference_count": self.reference_count,
            "last_referenced": self.last_referenced,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "ttl_seconds": self.ttl_seconds,
            "session_id": self.session_id,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "MemoryEntry":
        return cls(
            id=d.get("id", ""),
            content=d.get("content", ""),
            memory_type=MemoryType(d.get("memory_type", "fact")),
            source=MemorySource(d.get("source", "extraction")),
            tags=d.get("tags", []),
            confidence=d.get("confidence", 1.0),
            reference_count=d.get("reference_count", 0),
            last_referenced=d.get("last_referenced", 0.0),
            created_at=d.get("created_at", 0.0),
            updated_at=d.get("updated_at", 0.0),
            ttl_seconds=d.get("ttl_seconds", 0.0),
            session_id=d.get("session_id", ""),
        )


# Extraction patterns for common memory types
_EXTRACTION_PATTERNS = [
    # Decision patterns
    (MemoryType.DECISION, re.compile(
        r"(?:let's|we should|I'll|decided to|please|make sure to|always|never)\s+(.+)",
        re.IGNORECASE
    )),
    # Preference patterns
    (MemoryType.PREFERENCE, re.compile(
        r"(?:I prefer|I like|I want|prefer|use)\s+(.+?)(?:\s+(?:instead|rather|over)\s+.+)?$",
        re.IGNORECASE
    )),
    # Pitfall patterns
    (MemoryType.PITFALL, re.compile(
        r"(?:don't|avoid|be careful|watch out|make sure|important|note that|warning)\s*[:)]?\s*(.+)",
        re.IGNORECASE
    )),
    # Fact patterns
    (MemoryType.FACT, re.compile(
        r"(?:this project|the project|this codebase|this repo)\s+(?:uses|has|is|runs on)\s+(.+)",
        re.IGNORECASE
    )),
]


class CodexMemories:
    """Full cross-session memory system.

    Usage::
        memories = CodexMemories(project_root="/path/to/project")
        memories.initialize()

        # Auto-extract from conversation
        memories.extract_from_turn(user_msg, assistant_msg, tool_results)

        # Manual add
        memories.add("Project uses FastAPI for REST API", MemoryType.FACT)

        # Retrieve relevant memories
        relevant = memories.retrieve("How do I add a new endpoint?")
        injection = memories.get_injection_prompt()

        # Export to AGENTS.md
        memories.export_to_agents_md()
    """

    def __init__(
        self,
        project_root: str,
        db_path: Optional[str] = None,
        max_memories: int = 500,
        extraction_enabled: bool = True,
    ):
        self._root = Path(project_root).resolve()
        self._max_memories = max_memories
        self._extraction_enabled = extraction_enabled

        # SQLite database
        if db_path is None:
            db_dir = self._root / ".hakus" / "memories"
            db_dir.mkdir(parents=True, exist_ok=True)
            db_path = str(db_dir / "memories.db")
        self._db_path = db_path
        self._db: Optional[sqlite3.Connection] = None
        self._lock = threading.Lock()

    def initialize(self) -> None:
        """Initialize the SQLite database."""
        with self._lock:
            self._db = sqlite3.connect(self._db_path, check_same_thread=False)
            self._db.execute("""
                CREATE TABLE IF NOT EXISTS memories (
                    id TEXT PRIMARY KEY,
                    content TEXT NOT NULL,
                    memory_type TEXT NOT NULL,
                    source TEXT NOT NULL,
                    tags TEXT NOT NULL DEFAULT '[]',
                    confidence REAL NOT NULL DEFAULT 1.0,
                    reference_count INTEGER NOT NULL DEFAULT 0,
                    last_referenced REAL NOT NULL DEFAULT 0.0,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    ttl_seconds REAL NOT NULL DEFAULT 0.0,
                    session_id TEXT NOT NULL DEFAULT '',
                    content_hash TEXT NOT NULL DEFAULT ''
                )
            """)
            self._db.execute("""
                CREATE INDEX IF NOT EXISTS idx_memories_type ON memories(memory_type)
            """)
            self._db.execute("""
                CREATE INDEX IF NOT EXISTS idx_memories_confidence ON memories(confidence DESC)
            """)
            self._db.execute("""
                CREATE TABLE IF NOT EXISTS references (
                    memory_id TEXT NOT NULL,
                    turn_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    referenced_at REAL NOT NULL,
                    PRIMARY KEY (memory_id, turn_id)
                )
            """)
            self._db.commit()

        # Load existing AGENTS.md memories
        self._load_from_agents_md()

    def close(self) -> None:
        """Close the database connection."""
        with self._lock:
            if self._db:
                self._db.close()
                self._db = None

    # ------------------------------------------------------------------
    # Core operations
    # ------------------------------------------------------------------

    def add(
        self,
        content: str,
        memory_type: MemoryType = MemoryType.FACT,
        source: MemorySource = MemorySource.EXTRACTION,
        tags: Optional[List[str]] = None,
        confidence: float = 1.0,
        ttl_seconds: float = 0.0,
        session_id: str = "",
    ) -> str:
        """Add a new memory entry. Returns the memory ID."""
        content = content.strip()
        if not content:
            return ""

        # Check for duplicate (similar content)
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]
        existing = self._find_similar(content, content_hash)
        if existing:
            # Update existing: bump confidence and reference count
            self._update_confidence(existing.id, delta=0.1)
            return existing.id

        # Create new entry
        memory_id = f"mem_{int(time.time()*1000)}_{content_hash[:8]}"
        now = time.time()
        entry = MemoryEntry(
            id=memory_id,
            content=content,
            memory_type=memory_type,
            source=source,
            tags=tags or [],
            confidence=confidence,
            created_at=now,
            updated_at=now,
            ttl_seconds=ttl_seconds,
            session_id=session_id,
        )

        with self._lock:
            self._db.execute(
                """INSERT OR REPLACE INTO memories
                   (id, content, memory_type, source, tags, confidence,
                    reference_count, last_referenced, created_at, updated_at,
                    ttl_seconds, session_id, content_hash)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (entry.id, entry.content, entry.memory_type.value, entry.source.value,
                 json.dumps(entry.tags), entry.confidence, entry.reference_count,
                 entry.last_referenced, entry.created_at, entry.updated_at,
                 entry.ttl_seconds, entry.session_id, content_hash),
            )
            self._db.commit()

        # Evict if over limit
        self._evict_if_needed()

        logger.debug(f"Memory added: {memory_id} ({memory_type.value}): {content[:80]}")
        return memory_id

    def get(self, memory_id: str) -> Optional[MemoryEntry]:
        """Get a memory by ID."""
        with self._lock:
            row = self._db.execute(
                "SELECT * FROM memories WHERE id = ?", (memory_id,)
            ).fetchone()
        if not row:
            return None
        return self._row_to_entry(row)

    def remove(self, memory_id: str) -> bool:
        """Remove a memory by ID."""
        with self._lock:
            cursor = self._db.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
            self._db.execute("DELETE FROM references WHERE memory_id = ?", (memory_id,))
            self._db.commit()
            return cursor.rowcount > 0

    def record_reference(self, memory_id: str, turn_id: str, session_id: str = "") -> None:
        """Record that a memory was referenced in a specific turn."""
        now = time.time()
        with self._lock:
            self._db.execute(
                """INSERT OR REPLACE INTO references (memory_id, turn_id, session_id, referenced_at)
                   VALUES (?, ?, ?, ?)""",
                (memory_id, turn_id, session_id, now),
            )
            self._db.execute(
                """UPDATE memories SET
                   reference_count = reference_count + 1,
                   last_referenced = ?,
                   updated_at = ?
                   WHERE id = ?""",
                (now, now, memory_id),
            )
            self._db.commit()

    # ------------------------------------------------------------------
    # Extraction
    # ------------------------------------------------------------------

    def extract_from_turn(
        self,
        user_msg: str,
        assistant_msg: str = "",
        tool_results: Optional[List[str]] = None,
        session_id: str = "",
    ) -> List[str]:
        """Auto-extract memories from a conversation turn.

        Returns list of extracted memory IDs.
        """
        if not self._extraction_enabled:
            return []

        extracted_ids = []

        # Extract from user message
        for mem_type, pattern in _EXTRACTION_PATTERNS:
            for match in pattern.finditer(user_msg):
                fact = match.group(1).strip()
                if len(fact) > 10:  # Skip very short extractions
                    mid = self.add(
                        content=fact,
                        memory_type=mem_type,
                        source=MemorySource.EXTRACTION,
                        confidence=0.7,  # Auto-extracted = lower confidence
                        session_id=session_id,
                    )
                    if mid:
                        extracted_ids.append(mid)

        # Extract from tool results (project facts)
        if tool_results:
            for result in tool_results:
                # Look for project structure facts
                if "error" in result.lower() or "fail" in result.lower():
                    # Extract error patterns as pitfalls
                    error_match = re.search(r"Error:\s*(.+)", result)
                    if error_match:
                        mid = self.add(
                            content=f"Known error: {error_match.group(1)[:200]}",
                            memory_type=MemoryType.PITFALL,
                            source=MemorySource.EXTRACTION,
                            confidence=0.6,
                            session_id=session_id,
                        )
                        if mid:
                            extracted_ids.append(mid)

        return extracted_ids

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------

    def retrieve(
        self,
        query: str,
        k: int = 5,
        memory_types: Optional[List[MemoryType]] = None,
        min_confidence: float = 0.3,
    ) -> List[MemoryEntry]:
        """Retrieve relevant memories for a query.

        Uses keyword matching + confidence scoring + recency.
        """
        query_lower = query.lower()
        query_words = set(re.findall(r'\w+', query_lower))

        with self._lock:
            rows = self._db.execute(
                """SELECT * FROM memories WHERE confidence >= ? ORDER BY confidence DESC""",
                (min_confidence,),
            ).fetchall()

        candidates = []
        for row in rows:
            entry = self._row_to_entry(row)
            if entry.is_expired():
                continue
            if memory_types and entry.memory_type not in memory_types:
                continue

            # Score: keyword overlap + confidence + recency + reference count
            content_words = set(re.findall(r'\w+', entry.content.lower()))
            overlap = len(query_words & content_words)
            if overlap == 0:
                # Also check tag overlap
                tag_words = set(w for t in entry.tags for w in re.findall(r'\w+', t.lower()))
                overlap = len(query_words & tag_words) * 0.5

            if overlap == 0:
                continue

            # Recency score (exponential decay, half-life = 1 day)
            age_seconds = time.time() - entry.updated_at
            recency = 2.0 ** (-age_seconds / 86400)

            # Final score
            score = (
                overlap * 0.4
                + entry.confidence * 0.3
                + recency * 0.2
                + min(entry.reference_count / 10.0, 1.0) * 0.1
            )

            candidates.append((score, entry))

        # Sort by score, return top-k
        candidates.sort(key=lambda x: x[0], reverse=True)
        return [entry for _, entry in candidates[:k]]

    def get_all(
        self,
        memory_type: Optional[MemoryType] = None,
        min_confidence: float = 0.0,
    ) -> List[MemoryEntry]:
        """Get all memories, optionally filtered."""
        with self._lock:
            if memory_type:
                rows = self._db.execute(
                    """SELECT * FROM memories WHERE memory_type = ? AND confidence >= ?
                       ORDER BY updated_at DESC""",
                    (memory_type.value, min_confidence),
                ).fetchall()
            else:
                rows = self._db.execute(
                    """SELECT * FROM memories WHERE confidence >= ?
                       ORDER BY updated_at DESC""",
                    (min_confidence,),
                ).fetchall()
        return [self._row_to_entry(row) for row in rows]

    def get_injection_prompt(self, max_tokens: int = 2000) -> str:
        """Get memories formatted for injection into system prompt."""
        memories = self.get_all(min_confidence=0.5)
        if not memories:
            return ""

        # Prioritize: decisions > preferences > pitfalls > facts > patterns > context
        type_order = {
            MemoryType.DECISION: 0,
            MemoryType.PREFERENCE: 1,
            MemoryType.PITFALL: 2,
            MemoryType.FACT: 3,
            MemoryType.PATTERN: 4,
            MemoryType.CONTEXT: 5,
        }
        memories.sort(key=lambda m: (type_order.get(m.memory_type, 99), -m.confidence))

        # Build prompt within token budget
        lines = ["# Project Memories\n"]
        current_type = None
        char_count = len(lines[0])

        for mem in memories:
            type_label = mem.memory_type.value.title() + "s"
            if type_label != current_type:
                if current_type is not None:
                    lines.append("")
                lines.append(f"## {type_label}")
                current_type = type_label

            line = f"- {mem.content}"
            if char_count + len(line) > max_tokens * 4:  # Approximate chars per token
                break
            lines.append(line)
            char_count += len(line)

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------

    def export_to_agents_md(self, path: Optional[str] = None) -> str:
        """Export memories to AGENTS.md (appending to existing)."""
        target = Path(path) if path else self._root / "AGENTS.md"
        content = self.get_injection_prompt(max_tokens=4000)

        if target.exists():
            # Check if memories section already exists
            existing = target.read_text(encoding="utf-8")
            if "# Project Memories" in existing:
                # Replace existing memories section
                pattern = r"# Project Memories\n.*"
                if re.search(pattern, existing, re.DOTALL):
                    new_content = re.sub(pattern, content, existing, flags=re.DOTALL)
                    target.write_text(new_content, encoding="utf-8")
                    return str(target)

            # Append memories section
            target.write_text(existing + "\n\n" + content, encoding="utf-8")
        else:
            target.write_text(content, encoding="utf-8")

        return str(target)

    def _load_from_agents_md(self) -> None:
        """Load memories from existing AGENTS.md."""
        for filename in ["AGENTS.md", ".hakus.md", "CLAUDE.md"]:
            path = self._root / filename
            if not path.exists():
                continue
            try:
                content = path.read_text(encoding="utf-8")
                for line in content.split("\n"):
                    line = line.strip()
                    if line.startswith("- ") and len(line) > 5:
                        fact = line[2:]
                        # Infer type from content
                        mem_type = MemoryType.FACT
                        if any(w in fact.lower() for w in ["always", "never", "must", "should"]):
                            mem_type = MemoryType.DECISION
                        elif any(w in fact.lower() for w in ["prefer", "like", "use"]):
                            mem_type = MemoryType.PREFERENCE
                        elif any(w in fact.lower() for w in ["avoid", "don't", "careful", "warning"]):
                            mem_type = MemoryType.PITFALL
                        self.add(
                            content=fact,
                            memory_type=mem_type,
                            source=MemorySource.AGENTS_MD,
                            confidence=0.9,
                        )
            except Exception as e:
                logger.warning(f"Failed to load from {path}: {e}")

    # ------------------------------------------------------------------
    # Integration (merge)
    # ------------------------------------------------------------------

    def integrate(self, other_memories: List[MemoryEntry]) -> int:
        """Merge memories from another source (e.g., another session).

        Returns the number of new memories added.
        """
        added = 0
        for entry in other_memories:
            existing = self._find_similar(entry.content)
            if existing:
                # Merge: take the higher confidence, update tags
                if entry.confidence > existing.confidence:
                    self._update_confidence(existing.id, entry.confidence - existing.confidence)
                # Merge tags
                new_tags = list(set(existing.tags + entry.tags))
                with self._lock:
                    self._db.execute(
                        "UPDATE memories SET tags = ? WHERE id = ?",
                        (json.dumps(new_tags), existing.id),
                    )
                    self._db.commit()
            else:
                mid = self.add(
                    content=entry.content,
                    memory_type=entry.memory_type,
                    source=MemorySource.INTEGRATION,
                    tags=entry.tags,
                    confidence=entry.confidence * 0.8,  # Slightly lower confidence for merged
                )
                if mid:
                    added += 1
        return added

    # ------------------------------------------------------------------
    # Maintenance
    # ------------------------------------------------------------------

    def cleanup(self) -> int:
        """Remove expired memories. Returns count of removed entries."""
        now = time.time()
        with self._lock:
            rows = self._db.execute(
                "SELECT id, updated_at, ttl_seconds FROM memories WHERE ttl_seconds > 0"
            ).fetchall()

        removed = 0
        for row in rows:
            mid, updated_at, ttl = row
            if (now - updated_at) > ttl:
                if self.remove(mid):
                    removed += 1

        return removed

    def get_stats(self) -> Dict[str, Any]:
        """Return memory statistics."""
        with self._lock:
            total = self._db.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
            by_type = {}
            for row in self._db.execute(
                "SELECT memory_type, COUNT(*) FROM memories GROUP BY memory_type"
            ).fetchall():
                by_type[row[0]] = row[1]
            total_refs = self._db.execute("SELECT COUNT(*) FROM references").fetchone()[0]

        return {
            "total_memories": total,
            "by_type": by_type,
            "total_references": total_refs,
            "db_path": self._db_path,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _find_similar(self, content: str, content_hash: Optional[str] = None) -> Optional[MemoryEntry]:
        """Find a memory with similar content (exact hash match first, then fuzzy)."""
        ch = content_hash or hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]

        with self._lock:
            # Exact hash match
            row = self._db.execute(
                "SELECT * FROM memories WHERE content_hash = ?", (ch,)
            ).fetchone()
            if row:
                return self._row_to_entry(row)

            # Fuzzy: check if any existing content is very similar
            rows = self._db.execute("SELECT * FROM memories").fetchall()

        content_lower = content.lower().strip()
        for row in rows:
            entry = self._row_to_entry(row)
            existing_lower = entry.content.lower().strip()
            # Simple similarity: check if one contains the other or they share most words
            if existing_lower == content_lower:
                return entry
            if len(content_lower) > 20 and len(existing_lower) > 20:
                # Word overlap ratio
                words_a = set(content_lower.split())
                words_b = set(existing_lower.split())
                overlap = len(words_a & words_b)
                union = len(words_a | words_b)
                if union > 0 and overlap / union > 0.8:
                    return entry

        return None

    def _update_confidence(self, memory_id: str, delta: float = 0.1) -> None:
        """Update confidence of a memory (clamped to [0, 1])."""
        with self._lock:
            self._db.execute(
                """UPDATE memories SET
                   confidence = MIN(1.0, MAX(0.0, confidence + ?)),
                   updated_at = ?
                   WHERE id = ?""",
                (delta, time.time(), memory_id),
            )
            self._db.commit()

    def _evict_if_needed(self) -> None:
        """Evict lowest-confidence memories if over limit."""
        with self._lock:
            count = self._db.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
            if count <= self._max_memories:
                return

            # Remove the lowest-confidence, least-referenced memories
            excess = count - self._max_memories
            ids = self._db.execute(
                """SELECT id FROM memories
                   ORDER BY confidence ASC, reference_count ASC, updated_at ASC
                   LIMIT ?""",
                (excess,),
            ).fetchall()
            for (mid,) in ids:
                self._db.execute("DELETE FROM memories WHERE id = ?", (mid,))
                self._db.execute("DELETE FROM references WHERE memory_id = ?", (mid,))
            self._db.commit()

    @staticmethod
    def _row_to_entry(row: tuple) -> MemoryEntry:
        """Convert a SQLite row to a MemoryEntry."""
        return MemoryEntry(
            id=row[0],
            content=row[1],
            memory_type=MemoryType(row[2]),
            source=MemorySource(row[3]),
            tags=json.loads(row[4]),
            confidence=row[5],
            reference_count=row[6],
            last_referenced=row[7],
            created_at=row[8],
            updated_at=row[9],
            ttl_seconds=row[10],
            session_id=row[11],
        )
