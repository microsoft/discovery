"""
State-of-the-art Discovery Documentation Retrieval System (v2)

This module provides high-quality retrieval for the Discovery documentation with:

1. **Hierarchical Structure-Aware Chunking**
   - Respects markdown heading hierarchy
   - Preserves semantic boundaries (doesn't cut mid-paragraph)
   - Maintains full heading path as metadata for context
   - Smart overlap that preserves meaning

2. **Hybrid Retrieval**
   - BM25 for lexical matching (exact terms, error messages, API names)
   - Dense embeddings for semantic matching (paraphrased queries)
   - Reciprocal Rank Fusion (RRF) to combine rankings

3. **Persistent Index**
   - Save/load index to disk for fast startup
   - Automatic staleness detection based on source file modification
   - Separate caches for BM25 terms and embeddings

4. **Intelligent Reranking**
   - LLM-based cross-encoder style reranking for final selection
   - Intent-aware boosting (how-to vs concept vs troubleshooting)

5. **Query Understanding**
   - Query expansion with synonyms/related terms
   - Intent classification to adjust retrieval strategy

Usage:
    from discovery_docs_retriever import DiscoveryRetriever
    
    retriever = DiscoveryRetriever(docs_path="prompts/combined-discovery-docs.md")
    results = retriever.retrieve(query="How do I create a supercomputer?", top_k=10)
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import pickle
import re
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple, Set
from abc import ABC, abstractmethod


# ==============================================================================
# Constants and Configuration
# ==============================================================================

DEFAULT_CHUNK_TARGET_TOKENS = 800
DEFAULT_CHUNK_OVERLAP_TOKENS = 150
DEFAULT_BM25_K1 = 1.4
DEFAULT_BM25_B = 0.75
DEFAULT_TOP_K = 12
DEFAULT_RERANK_CANDIDATES = 30

# Index file names
INDEX_METADATA_FILE = "index_metadata.json"
INDEX_CHUNKS_FILE = "chunks.pkl"
INDEX_BM25_FILE = "bm25_index.pkl"
INDEX_EMBEDDINGS_FILE = "embeddings.pkl"

# Stopwords optimized for technical documentation
STOPWORDS = frozenset({
    "a", "an", "and", "are", "as", "at", "be", "but", "by", "for", "from",
    "has", "have", "how", "i", "if", "in", "into", "is", "it", "its", "of",
    "on", "or", "our", "so", "that", "the", "their", "then", "there", "these",
    "this", "to", "was", "we", "what", "when", "where", "which", "who", "will",
    "with", "you", "your", "can", "do", "does", "did", "should", "would", "could",
    # Domain-specific common terms (appear everywhere, not discriminative)
    "microsoft", "discovery", "azure", "resource", "resources",
})

# Query intent patterns
INTENT_PATTERNS = {
    "definition": [
        r"^what\s+is\s+",
        r"^what's\s+",
        r"^define\s+",
        r"^explain\s+",
        r"meaning\s+of",
        r"definition\s+of",
    ],
    "how_to": [
        r"^how\s+(do|can|to|should)\s+",
        r"^steps?\s+to",
        r"^guide\s+to",
        r"^tutorial",
        r"^create\s+",
        r"^deploy\s+",
        r"^configure\s+",
        r"^set\s*up\s+",
    ],
    "troubleshooting": [
        r"error",
        r"fail(ed|ing|s)?",
        r"not\s+working",
        r"issue",
        r"problem",
        r"fix\s+",
        r"debug",
        r"troubleshoot",
    ],
    "reference": [
        r"^list\s+(of\s+)?",
        r"^what\s+are\s+(the\s+)?",
        r"types?\s+of",
        r"options?\s+for",
        r"parameters?",
        r"properties",
        r"schema",
    ],
}

# Synonym expansions for query understanding
SYNONYMS = {
    "supercomputer": ["compute", "cluster", "hpc", "compute cluster"],
    "bookshelf": ["knowledge base", "kb", "document store", "rag"],
    "tool": ["action", "capability", "function"],
    "agent": ["assistant", "bot", "ai agent"],
    "workspace": ["project", "environment"],
    "deploy": ["publish", "create", "provision"],
    "rbac": ["role", "permission", "access control", "authorization"],
    "storage": ["blob", "data container", "data asset"],
}


# ==============================================================================
# Data Structures
# ==============================================================================

@dataclass
class ChunkMetadata:
    """Rich metadata for each chunk."""
    source_file: str = ""
    heading_path: List[str] = field(default_factory=list)
    heading_levels: List[int] = field(default_factory=list)
    start_line: int = 0
    end_line: int = 0
    section_type: str = "content"  # content, code, table, list
    has_code_block: bool = False
    has_table: bool = False
    word_count: int = 0


@dataclass
class DocChunk:
    """A chunk of documentation with full context."""
    chunk_id: int
    content: str
    title_path: str  # Human-readable heading path
    metadata: ChunkMetadata
    
    # Computed fields for retrieval
    tokens: List[str] = field(default_factory=list)
    token_count: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "content": self.content,
            "title_path": self.title_path,
            "metadata": asdict(self.metadata),
            "token_count": self.token_count,
        }


@dataclass
class RetrievalResult:
    """A single retrieval result with scoring details."""
    chunk: DocChunk
    score: float
    bm25_score: float = 0.0
    embedding_score: float = 0.0
    rerank_score: float = 0.0
    matched_terms: List[str] = field(default_factory=list)


@dataclass  
class QueryAnalysis:
    """Analysis of user query for retrieval optimization."""
    original_query: str
    normalized_query: str
    tokens: List[str]
    intent: str  # definition, how_to, troubleshooting, reference, general
    expanded_terms: List[str] = field(default_factory=list)
    key_entities: List[str] = field(default_factory=list)


# ==============================================================================
# Tokenization and Text Processing
# ==============================================================================

_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9_-]*|[0-9]+(?:\.[0-9]+)?", re.UNICODE)
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$", re.MULTILINE)
_CODE_BLOCK_RE = re.compile(r"```[\s\S]*?```", re.MULTILINE)
_INLINE_CODE_RE = re.compile(r"`[^`]+`")
_TABLE_RE = re.compile(r"^\|.*\|$", re.MULTILINE)
_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]+\)")


def tokenize(text: str, remove_stopwords: bool = True) -> List[str]:
    """Tokenize text for indexing/search with optional stopword removal."""
    if not text:
        return []
    
    # Normalize text
    text = text.lower()
    
    # Extract tokens
    tokens = _WORD_RE.findall(text)
    
    # Filter
    result = []
    for t in tokens:
        if len(t) < 2 and not t.isdigit():
            continue
        if remove_stopwords and t in STOPWORDS:
            continue
        # Basic stemming for plurals
        if len(t) > 3 and t.endswith("s") and not t.endswith("ss"):
            t = t[:-1]
        result.append(t)
    
    return result


def estimate_tokens(text: str) -> int:
    """Estimate token count (rough approximation for budget)."""
    if not text:
        return 0
    # ~4 characters per token on average for English
    return max(1, len(text) // 4)


def extract_text_content(markdown: str) -> str:
    """Extract plain text from markdown, removing formatting."""
    text = markdown
    # Remove code blocks
    text = _CODE_BLOCK_RE.sub(" [code] ", text)
    # Remove inline code
    text = _INLINE_CODE_RE.sub(lambda m: m.group(0)[1:-1], text)
    # Extract link text
    text = _LINK_RE.sub(r"\1", text)
    # Remove remaining markdown syntax
    text = re.sub(r"[#*_~`|>-]+", " ", text)
    # Normalize whitespace
    text = " ".join(text.split())
    return text


# ==============================================================================
# Hierarchical Chunking
# ==============================================================================

class HierarchicalChunker:
    """Structure-aware markdown chunker that respects document hierarchy."""
    
    def __init__(
        self,
        target_tokens: int = DEFAULT_CHUNK_TARGET_TOKENS,
        overlap_tokens: int = DEFAULT_CHUNK_OVERLAP_TOKENS,
        token_counter: Callable[[str], int] = estimate_tokens,
    ):
        self.target_tokens = target_tokens
        self.overlap_tokens = overlap_tokens
        self.token_counter = token_counter
    
    def chunk(self, markdown: str, source_file: str = "") -> List[DocChunk]:
        """Split markdown into semantically coherent chunks."""
        if not markdown:
            return []
        
        # Parse document structure
        sections = self._parse_sections(markdown)
        
        # Convert sections to chunks with proper sizing
        chunks = self._sections_to_chunks(sections, source_file)
        
        return chunks
    
    def _parse_sections(self, markdown: str) -> List[Dict[str, Any]]:
        """Parse markdown into hierarchical sections."""
        lines = markdown.splitlines()
        sections = []
        
        heading_stack: List[Tuple[int, str]] = []  # (level, title)
        current_content: List[str] = []
        current_start_line = 0
        
        for line_num, line in enumerate(lines):
            heading_match = _HEADING_RE.match(line.strip())
            
            if heading_match:
                # Save current section
                if current_content or heading_stack:
                    content = "\n".join(current_content).strip()
                    if content or heading_stack:
                        sections.append({
                            "heading_stack": list(heading_stack),
                            "content": content,
                            "start_line": current_start_line,
                            "end_line": line_num - 1,
                        })
                
                # Update heading stack
                level = len(heading_match.group(1))
                title = heading_match.group(2).strip()
                
                # Pop headings at same or higher level
                while heading_stack and heading_stack[-1][0] >= level:
                    heading_stack.pop()
                
                heading_stack.append((level, title))
                current_content = []
                current_start_line = line_num + 1
            else:
                current_content.append(line)
        
        # Don't forget last section
        if current_content:
            content = "\n".join(current_content).strip()
            if content:
                sections.append({
                    "heading_stack": list(heading_stack),
                    "content": content,
                    "start_line": current_start_line,
                    "end_line": len(lines) - 1,
                })
        
        return sections
    
    def _sections_to_chunks(
        self, 
        sections: List[Dict[str, Any]], 
        source_file: str
    ) -> List[DocChunk]:
        """Convert sections to properly sized chunks."""
        chunks = []
        chunk_id = 0
        
        for section in sections:
            heading_stack = section["heading_stack"]
            content = section["content"]
            
            # Skip empty or TOC sections
            if not content.strip():
                continue
            title = heading_stack[-1][1] if heading_stack else ""
            if title.lower() in {"table of contents", "toc", "contents"}:
                continue
            
            # Build title path
            title_path = " / ".join(h[1] for h in heading_stack) or "(untitled)"
            
            # Analyze content
            has_code = "```" in content
            has_table = bool(_TABLE_RE.search(content))
            section_type = self._classify_section(content, has_code, has_table)
            
            # Create metadata
            metadata = ChunkMetadata(
                source_file=source_file,
                heading_path=[h[1] for h in heading_stack],
                heading_levels=[h[0] for h in heading_stack],
                start_line=section["start_line"],
                end_line=section["end_line"],
                section_type=section_type,
                has_code_block=has_code,
                has_table=has_table,
                word_count=len(content.split()),
            )
            
            # Split into appropriately sized chunks
            content_tokens = self.token_counter(content)
            
            if content_tokens <= self.target_tokens:
                # Content fits in one chunk
                chunk = DocChunk(
                    chunk_id=chunk_id,
                    content=content,
                    title_path=title_path,
                    metadata=metadata,
                    tokens=tokenize(f"{title_path}\n{content}"),
                    token_count=content_tokens,
                )
                chunks.append(chunk)
                chunk_id += 1
            else:
                # Need to split content
                sub_chunks = self._split_large_section(
                    content, title_path, metadata, chunk_id
                )
                chunks.extend(sub_chunks)
                chunk_id += len(sub_chunks)
        
        return chunks
    
    def _split_large_section(
        self,
        content: str,
        title_path: str,
        base_metadata: ChunkMetadata,
        start_id: int,
    ) -> List[DocChunk]:
        """Split large section into smaller chunks with overlap."""
        chunks = []
        
        # Split by paragraphs (double newline)
        paragraphs = re.split(r"\n\s*\n", content)
        paragraphs = [p.strip() for p in paragraphs if p.strip()]
        
        current_parts: List[str] = []
        current_tokens = 0
        chunk_id = start_id
        
        for para in paragraphs:
            para_tokens = self.token_counter(para)
            
            # If single paragraph exceeds target, split it further
            if para_tokens > self.target_tokens:
                # Flush current
                if current_parts:
                    chunk_content = "\n\n".join(current_parts)
                    chunks.append(self._create_chunk(
                        chunk_id, chunk_content, title_path, base_metadata
                    ))
                    chunk_id += 1
                    current_parts = []
                    current_tokens = 0
                
                # Split large paragraph by sentences or lines
                sub_parts = self._split_paragraph(para)
                for sub in sub_parts:
                    sub_tokens = self.token_counter(sub)
                    if current_tokens + sub_tokens > self.target_tokens and current_parts:
                        chunk_content = "\n\n".join(current_parts)
                        chunks.append(self._create_chunk(
                            chunk_id, chunk_content, title_path, base_metadata
                        ))
                        chunk_id += 1
                        # Keep overlap
                        current_parts = self._get_overlap(current_parts)
                        current_tokens = sum(self.token_counter(p) for p in current_parts)
                    current_parts.append(sub)
                    current_tokens += sub_tokens
            else:
                # Check if adding this paragraph exceeds target
                if current_tokens + para_tokens > self.target_tokens and current_parts:
                    chunk_content = "\n\n".join(current_parts)
                    chunks.append(self._create_chunk(
                        chunk_id, chunk_content, title_path, base_metadata
                    ))
                    chunk_id += 1
                    # Keep overlap from end of previous chunk
                    current_parts = self._get_overlap(current_parts)
                    current_tokens = sum(self.token_counter(p) for p in current_parts)
                
                current_parts.append(para)
                current_tokens += para_tokens
        
        # Don't forget last chunk
        if current_parts:
            chunk_content = "\n\n".join(current_parts)
            chunks.append(self._create_chunk(
                chunk_id, chunk_content, title_path, base_metadata
            ))
        
        return chunks
    
    def _split_paragraph(self, para: str) -> List[str]:
        """Split a large paragraph into smaller pieces."""
        # Try splitting by sentences first
        sentences = re.split(r"(?<=[.!?])\s+", para)
        if len(sentences) > 1:
            return sentences
        
        # Fall back to splitting by lines
        lines = para.splitlines()
        if len(lines) > 1:
            return lines
        
        # Last resort: split by words
        words = para.split()
        chunk_size = self.target_tokens // 2
        result = []
        for i in range(0, len(words), chunk_size):
            result.append(" ".join(words[i:i+chunk_size]))
        return result
    
    def _get_overlap(self, parts: List[str]) -> List[str]:
        """Get overlap portion from end of parts list."""
        if not parts or self.overlap_tokens <= 0:
            return []
        
        overlap_parts = []
        overlap_tokens = 0
        
        for part in reversed(parts):
            part_tokens = self.token_counter(part)
            if overlap_tokens + part_tokens > self.overlap_tokens:
                break
            overlap_parts.insert(0, part)
            overlap_tokens += part_tokens
        
        return overlap_parts
    
    def _create_chunk(
        self,
        chunk_id: int,
        content: str,
        title_path: str,
        base_metadata: ChunkMetadata,
    ) -> DocChunk:
        """Create a DocChunk with computed fields."""
        return DocChunk(
            chunk_id=chunk_id,
            content=content,
            title_path=title_path,
            metadata=base_metadata,
            tokens=tokenize(f"{title_path}\n{content}"),
            token_count=self.token_counter(content),
        )
    
    def _classify_section(
        self, 
        content: str, 
        has_code: bool, 
        has_table: bool
    ) -> str:
        """Classify section type for retrieval optimization."""
        content_lower = content.lower()
        
        if has_code and len(re.findall(r"```", content)) >= 2:
            return "code"
        if has_table:
            return "table"
        if content.strip().startswith(("-", "*", "1.")):
            return "list"
        if any(kw in content_lower for kw in ["step ", "steps:", "procedure"]):
            return "procedure"
        
        return "content"


# ==============================================================================
# BM25 Index
# ==============================================================================

class BM25Index:
    """Optimized BM25 index with IDF caching."""
    
    def __init__(
        self,
        chunks: List[DocChunk],
        k1: float = DEFAULT_BM25_K1,
        b: float = DEFAULT_BM25_B,
    ):
        self.k1 = k1
        self.b = b
        self.chunks = chunks
        
        # Build index
        self._doc_freqs: Dict[str, int] = {}
        self._term_freqs: List[Dict[str, int]] = []
        self._doc_lengths: List[int] = []
        self._idf_cache: Dict[str, float] = {}
        
        for chunk in chunks:
            tf: Dict[str, int] = {}
            for term in chunk.tokens:
                tf[term] = tf.get(term, 0) + 1
            self._term_freqs.append(tf)
            self._doc_lengths.append(len(chunk.tokens))
            
            for term in tf:
                self._doc_freqs[term] = self._doc_freqs.get(term, 0) + 1
        
        self._N = len(chunks)
        self._avgdl = sum(self._doc_lengths) / self._N if self._N else 1.0
        
        # Pre-compute IDF for all terms
        for term, df in self._doc_freqs.items():
            self._idf_cache[term] = math.log((self._N - df + 0.5) / (df + 0.5) + 1.0)
    
    def search(
        self, 
        query_tokens: List[str], 
        top_k: int = DEFAULT_TOP_K
    ) -> List[Tuple[int, float, List[str]]]:
        """Search index, returns (chunk_id, score, matched_terms) tuples."""
        if not query_tokens:
            return []
        
        scores: List[Tuple[int, float, List[str]]] = []
        
        for idx, chunk in enumerate(self.chunks):
            tf = self._term_freqs[idx]
            dl = self._doc_lengths[idx] or 1
            
            score = 0.0
            matched_terms = []
            
            for term in query_tokens:
                f = tf.get(term, 0)
                if f == 0:
                    continue
                
                matched_terms.append(term)
                idf = self._idf_cache.get(term, 0.0)
                
                # BM25 formula
                numerator = f * (self.k1 + 1)
                denominator = f + self.k1 * (1 - self.b + self.b * (dl / self._avgdl))
                score += idf * (numerator / denominator)
            
            if score > 0:
                # Boost for matches in title
                title_tokens = set(tokenize(chunk.title_path))
                title_matches = len(set(query_tokens) & title_tokens)
                score += title_matches * 1.5
                
                scores.append((idx, score, matched_terms))
        
        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[:top_k]
    
    def get_state(self) -> Dict[str, Any]:
        """Get serializable state for persistence."""
        return {
            "k1": self.k1,
            "b": self.b,
            "doc_freqs": self._doc_freqs,
            "term_freqs": self._term_freqs,
            "doc_lengths": self._doc_lengths,
            "idf_cache": self._idf_cache,
            "N": self._N,
            "avgdl": self._avgdl,
        }
    
    @classmethod
    def from_state(cls, state: Dict[str, Any], chunks: List[DocChunk]) -> "BM25Index":
        """Reconstruct index from saved state."""
        obj = cls.__new__(cls)
        obj.k1 = state["k1"]
        obj.b = state["b"]
        obj.chunks = chunks
        obj._doc_freqs = state["doc_freqs"]
        obj._term_freqs = state["term_freqs"]
        obj._doc_lengths = state["doc_lengths"]
        obj._idf_cache = state["idf_cache"]
        obj._N = state["N"]
        obj._avgdl = state["avgdl"]
        return obj


# ==============================================================================
# Embedding Index (Optional - for hybrid retrieval)
# ==============================================================================

class EmbeddingIndex:
    """Dense embedding index for semantic search."""
    
    def __init__(
        self,
        chunks: List[DocChunk],
        embeddings: Optional[List[List[float]]] = None,
        embedding_fn: Optional[Callable[[List[str]], List[List[float]]]] = None,
    ):
        self.chunks = chunks
        self.embeddings = embeddings or []
        self.embedding_fn = embedding_fn
        self._embedding_dim = len(embeddings[0]) if embeddings else 0
    
    def build_embeddings(self, batch_size: int = 32) -> bool:
        """Build embeddings for all chunks using the embedding function."""
        if not self.embedding_fn:
            return False
        
        texts = [f"{c.title_path}\n{c.content[:1500]}" for c in self.chunks]
        
        all_embeddings = []
        for i in range(0, len(texts), batch_size):
            batch = texts[i:i+batch_size]
            try:
                batch_embs = self.embedding_fn(batch)
                all_embeddings.extend(batch_embs)
            except Exception as e:
                print(f"[WARN] Embedding error: {e}")
                return False
        
        self.embeddings = all_embeddings
        self._embedding_dim = len(all_embeddings[0]) if all_embeddings else 0
        return True
    
    def search(
        self, 
        query_embedding: List[float], 
        top_k: int = DEFAULT_TOP_K
    ) -> List[Tuple[int, float]]:
        """Search by cosine similarity, returns (chunk_id, score) tuples."""
        if not self.embeddings or not query_embedding:
            return []
        
        scores = []
        for idx, emb in enumerate(self.embeddings):
            sim = self._cosine_similarity(query_embedding, emb)
            scores.append((idx, sim))
        
        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[:top_k]
    
    @staticmethod
    def _cosine_similarity(a: List[float], b: List[float]) -> float:
        """Compute cosine similarity between two vectors."""
        if len(a) != len(b) or not a:
            return 0.0
        
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(x * x for x in b))
        
        if norm_a == 0 or norm_b == 0:
            return 0.0
        
        return dot / (norm_a * norm_b)
    
    def has_embeddings(self) -> bool:
        return bool(self.embeddings)
    
    def get_state(self) -> Dict[str, Any]:
        return {
            "embeddings": self.embeddings,
            "dim": self._embedding_dim,
        }
    
    @classmethod
    def from_state(
        cls, 
        state: Dict[str, Any], 
        chunks: List[DocChunk],
        embedding_fn: Optional[Callable] = None,
    ) -> "EmbeddingIndex":
        return cls(
            chunks=chunks,
            embeddings=state.get("embeddings", []),
            embedding_fn=embedding_fn,
        )


# ==============================================================================
# Query Analyzer
# ==============================================================================

class QueryAnalyzer:
    """Analyze and enhance queries for better retrieval."""
    
    def analyze(self, query: str) -> QueryAnalysis:
        """Analyze query to determine intent and expand terms."""
        normalized = query.strip().lower()
        tokens = tokenize(query, remove_stopwords=True)
        
        # Detect intent
        intent = self._detect_intent(normalized)
        
        # Extract key entities
        entities = self._extract_entities(normalized, tokens)
        
        # Expand query with synonyms
        expanded = self._expand_query(tokens)
        
        return QueryAnalysis(
            original_query=query,
            normalized_query=normalized,
            tokens=tokens,
            intent=intent,
            expanded_terms=expanded,
            key_entities=entities,
        )
    
    def _detect_intent(self, query: str) -> str:
        """Classify query intent."""
        for intent, patterns in INTENT_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, query, re.IGNORECASE):
                    return intent
        return "general"
    
    def _extract_entities(self, query: str, tokens: List[str]) -> List[str]:
        """Extract key entities from query."""
        entities = []
        
        # Common Discovery entities
        entity_patterns = [
            r"supercomputer",
            r"bookshelf",
            r"workspace",
            r"tool",
            r"agent",
            r"model",
            r"storage",
            r"data\s*container",
            r"data\s*asset",
            r"subscription",
            r"resource\s*group",
            r"acr",
            r"container\s*registry",
        ]
        
        for pattern in entity_patterns:
            if re.search(pattern, query, re.IGNORECASE):
                entities.append(pattern.replace(r"\s*", " "))
        
        return entities
    
    def _expand_query(self, tokens: List[str]) -> List[str]:
        """Expand query with synonyms and related terms."""
        expanded = set(tokens)
        
        for token in tokens:
            if token in SYNONYMS:
                for syn in SYNONYMS[token]:
                    expanded.update(tokenize(syn, remove_stopwords=False))
        
        return list(expanded)


# ==============================================================================
# Reranker
# ==============================================================================

class Reranker(ABC):
    """Abstract base class for rerankers."""
    
    @abstractmethod
    def rerank(
        self,
        query: str,
        candidates: List[Tuple[DocChunk, float]],
        top_k: int,
    ) -> List[Tuple[DocChunk, float]]:
        """Rerank candidates based on query relevance."""
        pass


class HeuristicReranker(Reranker):
    """Rule-based reranker using intent and content analysis."""
    
    def rerank(
        self,
        query: str,
        candidates: List[Tuple[DocChunk, float]],
        top_k: int,
        query_analysis: Optional[QueryAnalysis] = None,
    ) -> List[Tuple[DocChunk, float]]:
        if not candidates:
            return []
        
        if query_analysis is None:
            analyzer = QueryAnalyzer()
            query_analysis = analyzer.analyze(query)
        
        reranked = []
        
        for chunk, base_score in candidates:
            boost = 1.0
            
            # Intent-based boosting
            intent = query_analysis.intent
            title_lower = chunk.title_path.lower()
            content_lower = (chunk.content or "")[:500].lower()
            
            if intent == "definition":
                if any(kw in title_lower for kw in ["overview", "concept", "what is", "introduction"]):
                    boost *= 1.4
                if any(kw in title_lower for kw in ["deploy", "create", "step", "how to"]):
                    boost *= 0.7
                    
            elif intent == "how_to":
                if any(kw in title_lower for kw in ["how to", "guide", "tutorial", "create", "deploy"]):
                    boost *= 1.5
                if chunk.metadata.section_type == "procedure":
                    boost *= 1.3
                    
            elif intent == "troubleshooting":
                if any(kw in title_lower for kw in ["troubleshoot", "debug", "error", "issue", "faq"]):
                    boost *= 1.5
                    
            elif intent == "reference":
                if chunk.metadata.has_table:
                    boost *= 1.3
                if any(kw in title_lower for kw in ["reference", "schema", "parameter", "option"]):
                    boost *= 1.2
            
            # Penalize code-heavy chunks for conceptual queries
            if intent in ("definition", "reference"):
                if chunk.metadata.has_code_block:
                    boost *= 0.8
            
            # Boost chunks that contain key entities in title
            for entity in query_analysis.key_entities:
                entity_tokens = tokenize(entity, remove_stopwords=False)
                if any(t in title_lower for t in entity_tokens):
                    boost *= 1.2
                    break
            
            # Penalize very short or very long chunks
            if chunk.token_count < 50:
                boost *= 0.7
            elif chunk.token_count > 1500:
                boost *= 0.9
            
            final_score = base_score * boost
            reranked.append((chunk, final_score))
        
        reranked.sort(key=lambda x: x[1], reverse=True)
        return reranked[:top_k]


class LLMReranker(Reranker):
    """LLM-based cross-encoder style reranker."""
    
    def __init__(self, llm_fn: Callable[[str, str], str]):
        """
        Args:
            llm_fn: Function that takes (system_prompt, user_prompt) and returns response.
        """
        self.llm_fn = llm_fn
    
    def rerank(
        self,
        query: str,
        candidates: List[Tuple[DocChunk, float]],
        top_k: int,
    ) -> List[Tuple[DocChunk, float]]:
        if not candidates or len(candidates) <= 2:
            return candidates[:top_k]
        
        # Prepare candidates for LLM
        candidate_list = []
        for idx, (chunk, score) in enumerate(candidates[:min(len(candidates), 20)]):
            snippet = (chunk.content or "")[:400].replace("\n", " ").strip()
            candidate_list.append({
                "id": idx,
                "title": chunk.title_path,
                "snippet": snippet[:350] + "..." if len(snippet) > 350 else snippet,
            })
        
        system_prompt = """You are a search result ranking system. Given a user query and candidate document excerpts, rank the candidates from most to least relevant for answering the query.

Return ONLY a JSON array of candidate IDs in order from most relevant to least relevant.
Example: [3, 0, 5, 1, 4, 2]

Consider:
- How directly the excerpt answers the query
- Whether the excerpt contains the specific information requested
- The specificity and relevance of the content
- Prefer procedural content for "how to" questions
- Prefer overview/conceptual content for "what is" questions"""

        user_prompt = f"""Query: {query}

Candidates:
{json.dumps(candidate_list, indent=2)}

Return the IDs in relevance order as a JSON array:"""

        try:
            response = self.llm_fn(system_prompt, user_prompt)
            
            # Parse response
            match = re.search(r"\[[\d,\s]+\]", response)
            if match:
                ranked_ids = json.loads(match.group())
                
                # Rebuild results in new order
                id_to_result = {idx: (chunk, score) for idx, (chunk, score) in enumerate(candidates)}
                reranked = []
                seen = set()
                
                for rank, idx in enumerate(ranked_ids):
                    if idx in id_to_result and idx not in seen:
                        chunk, _ = id_to_result[idx]
                        # Assign new score based on rank
                        new_score = 1.0 - (rank * 0.05)
                        reranked.append((chunk, new_score))
                        seen.add(idx)
                
                # Add any missing candidates at the end
                for idx, (chunk, score) in enumerate(candidates):
                    if idx not in seen:
                        reranked.append((chunk, score * 0.5))
                
                return reranked[:top_k]
                
        except Exception as e:
            print(f"[WARN] LLM rerank failed: {e}")
        
        return candidates[:top_k]


# ==============================================================================
# Main Retriever Class
# ==============================================================================

class DiscoveryRetriever:
    """
    State-of-the-art retriever for Discovery documentation.
    
    Features:
    - Hybrid BM25 + embedding retrieval
    - Persistent index with staleness detection
    - Query analysis and expansion
    - Multi-stage reranking
    """
    
    def __init__(
        self,
        docs_path: str,
        index_dir: Optional[str] = None,
        embedding_fn: Optional[Callable[[List[str]], List[List[float]]]] = None,
        llm_rerank_fn: Optional[Callable[[str, str], str]] = None,
        chunk_target_tokens: int = DEFAULT_CHUNK_TARGET_TOKENS,
        chunk_overlap_tokens: int = DEFAULT_CHUNK_OVERLAP_TOKENS,
        use_embeddings: bool = True,
        use_llm_rerank: bool = True,
    ):
        self.docs_path = Path(docs_path)
        self.index_dir = Path(index_dir) if index_dir else self.docs_path.parent / ".retrieval_index"
        self.embedding_fn = embedding_fn
        self.llm_rerank_fn = llm_rerank_fn
        self.chunk_target_tokens = chunk_target_tokens
        self.chunk_overlap_tokens = chunk_overlap_tokens
        self.use_embeddings = use_embeddings and embedding_fn is not None
        self.use_llm_rerank = use_llm_rerank and llm_rerank_fn is not None
        
        # Components
        self.chunker = HierarchicalChunker(
            target_tokens=chunk_target_tokens,
            overlap_tokens=chunk_overlap_tokens,
        )
        self.query_analyzer = QueryAnalyzer()
        self.heuristic_reranker = HeuristicReranker()
        self.llm_reranker = LLMReranker(llm_rerank_fn) if llm_rerank_fn else None
        
        # Index state
        self.chunks: List[DocChunk] = []
        self.bm25_index: Optional[BM25Index] = None
        self.embedding_index: Optional[EmbeddingIndex] = None
        self._index_loaded = False
        
        # Load or build index
        self._ensure_index()
    
    def _ensure_index(self) -> None:
        """Ensure index is loaded, building if necessary."""
        if self._index_loaded:
            return
        
        # Try loading from disk
        if self._load_index():
            self._index_loaded = True
            return
        
        # Build fresh index
        self._build_index()
        self._index_loaded = True
    
    def _get_docs_hash(self) -> str:
        """Get hash of source document for staleness detection."""
        if not self.docs_path.exists():
            return ""
        
        stat = self.docs_path.stat()
        content_sample = ""
        try:
            with open(self.docs_path, "r", encoding="utf-8") as f:
                content_sample = f.read(10000)
        except Exception:
            pass
        
        hash_input = f"{stat.st_mtime}:{stat.st_size}:{content_sample[:1000]}"
        return hashlib.md5(hash_input.encode()).hexdigest()
    
    def _load_index(self) -> bool:
        """Try to load index from disk. Returns True if successful."""
        if not self.index_dir.exists():
            return False
        
        metadata_path = self.index_dir / INDEX_METADATA_FILE
        if not metadata_path.exists():
            return False
        
        try:
            with open(metadata_path, "r", encoding="utf-8") as f:
                metadata = json.load(f)
            
            # Check staleness
            current_hash = self._get_docs_hash()
            if metadata.get("docs_hash") != current_hash:
                print("[INDEX] Source docs changed, rebuilding index...")
                return False
            
            # Load chunks
            chunks_path = self.index_dir / INDEX_CHUNKS_FILE
            with open(chunks_path, "rb") as f:
                self.chunks = pickle.load(f)
            
            # Load BM25 index
            bm25_path = self.index_dir / INDEX_BM25_FILE
            with open(bm25_path, "rb") as f:
                bm25_state = pickle.load(f)
            self.bm25_index = BM25Index.from_state(bm25_state, self.chunks)
            
            # Load embeddings if available
            emb_path = self.index_dir / INDEX_EMBEDDINGS_FILE
            if emb_path.exists():
                with open(emb_path, "rb") as f:
                    emb_state = pickle.load(f)
                self.embedding_index = EmbeddingIndex.from_state(
                    emb_state, self.chunks, self.embedding_fn
                )
            else:
                self.embedding_index = EmbeddingIndex(
                    self.chunks, embedding_fn=self.embedding_fn
                )
            
            print(f"[OK] Loaded index: {len(self.chunks)} chunks")
            return True
            
        except Exception as e:
            print(f"[WARN] Failed to load index: {e}")
            return False
    
    def _build_index(self) -> None:
        """Build index from source document."""
        print(f"[INDEX] Building index from {self.docs_path}...")
        start_time = time.time()
        
        # Read source
        if not self.docs_path.exists():
            raise FileNotFoundError(f"Docs not found: {self.docs_path}")
        
        with open(self.docs_path, "r", encoding="utf-8") as f:
            markdown = f.read()
        
        # Chunk
        self.chunks = self.chunker.chunk(markdown, str(self.docs_path))
        print(f"  [OK] Created {len(self.chunks)} chunks")
        
        # Build BM25 index
        self.bm25_index = BM25Index(self.chunks)
        print(f"  [OK] Built BM25 index")
        
        # Build embeddings if available
        self.embedding_index = EmbeddingIndex(
            self.chunks, embedding_fn=self.embedding_fn
        )
        if self.use_embeddings and self.embedding_fn:
            print("  [INFO] Building embeddings...")
            if self.embedding_index.build_embeddings():
                print(f"  [OK] Built embeddings")
            else:
                print(f"  [WARN] Embeddings unavailable")
        
        # Save to disk
        self._save_index()
        
        elapsed = time.time() - start_time
        print(f"[OK] Index built in {elapsed:.1f}s")
    
    def _save_index(self) -> None:
        """Save index to disk for fast loading."""
        try:
            self.index_dir.mkdir(parents=True, exist_ok=True)
            
            # Save metadata
            metadata = {
                "docs_hash": self._get_docs_hash(),
                "docs_path": str(self.docs_path),
                "chunk_count": len(self.chunks),
                "created_at": time.time(),
                "chunk_target_tokens": self.chunk_target_tokens,
                "chunk_overlap_tokens": self.chunk_overlap_tokens,
            }
            with open(self.index_dir / INDEX_METADATA_FILE, "w", encoding="utf-8") as f:
                json.dump(metadata, f, indent=2)
            
            # Save chunks
            with open(self.index_dir / INDEX_CHUNKS_FILE, "wb") as f:
                pickle.dump(self.chunks, f)
            
            # Save BM25
            with open(self.index_dir / INDEX_BM25_FILE, "wb") as f:
                pickle.dump(self.bm25_index.get_state(), f)
            
            # Save embeddings if available
            if self.embedding_index and self.embedding_index.has_embeddings():
                with open(self.index_dir / INDEX_EMBEDDINGS_FILE, "wb") as f:
                    pickle.dump(self.embedding_index.get_state(), f)
            
            print(f"  [OK] Saved index to {self.index_dir}")
            
        except Exception as e:
            print(f"  [WARN] Failed to save index: {e}")
    
    def retrieve(
        self,
        query: str,
        top_k: int = DEFAULT_TOP_K,
        rerank_candidates: int = DEFAULT_RERANK_CANDIDATES,
    ) -> List[RetrievalResult]:
        """
        Retrieve relevant chunks for a query.
        
        Args:
            query: User query string
            top_k: Number of final results to return
            rerank_candidates: Number of candidates to consider for reranking
            
        Returns:
            List of RetrievalResult with chunks and scores
        """
        if not query or not self.bm25_index:
            return []
        
        # Analyze query
        analysis = self.query_analyzer.analyze(query)
        
        # Get expanded query tokens
        search_tokens = list(set(analysis.tokens + analysis.expanded_terms))
        
        # BM25 retrieval
        bm25_results = self.bm25_index.search(search_tokens, top_k=rerank_candidates)
        
        # Combine with embedding results if available
        if self.use_embeddings and self.embedding_index and self.embedding_index.has_embeddings():
            query_embedding = self._get_query_embedding(query)
            if query_embedding:
                emb_results = self.embedding_index.search(query_embedding, top_k=rerank_candidates)
                combined = self._reciprocal_rank_fusion(bm25_results, emb_results)
            else:
                combined = [(idx, score, terms) for idx, score, terms in bm25_results]
        else:
            combined = [(idx, score, terms) for idx, score, terms in bm25_results]
        
        # Convert to candidates
        candidates = []
        for item in combined[:rerank_candidates]:
            if len(item) == 3:
                idx, score, matched_terms = item
            else:
                idx, score = item
                matched_terms = []
            
            if 0 <= idx < len(self.chunks):
                chunk = self.chunks[idx]
                candidates.append((chunk, score))
        
        # Apply heuristic reranking
        reranked = self.heuristic_reranker.rerank(
            query, candidates, rerank_candidates, analysis
        )
        
        # Apply LLM reranking if available
        if self.use_llm_rerank and self.llm_reranker and len(reranked) > 3:
            reranked = self.llm_reranker.rerank(query, reranked, top_k)
        else:
            reranked = reranked[:top_k]
        
        # Build results
        results = []
        for chunk, score in reranked:
            result = RetrievalResult(
                chunk=chunk,
                score=score,
                matched_terms=analysis.tokens,
            )
            results.append(result)
        
        return results
    
    def _get_query_embedding(self, query: str) -> Optional[List[float]]:
        """Get embedding for query."""
        if not self.embedding_fn:
            return None
        try:
            embeddings = self.embedding_fn([query])
            return embeddings[0] if embeddings else None
        except Exception:
            return None
    
    def _reciprocal_rank_fusion(
        self,
        bm25_results: List[Tuple[int, float, List[str]]],
        emb_results: List[Tuple[int, float]],
        k: int = 60,
        bm25_weight: float = 0.5,
        emb_weight: float = 0.5,
    ) -> List[Tuple[int, float, List[str]]]:
        """Combine BM25 and embedding results using reciprocal rank fusion."""
        scores: Dict[int, float] = {}
        matched_terms: Dict[int, List[str]] = {}
        
        # BM25 contribution
        for rank, (idx, _, terms) in enumerate(bm25_results):
            scores[idx] = scores.get(idx, 0) + bm25_weight / (k + rank + 1)
            matched_terms[idx] = terms
        
        # Embedding contribution
        for rank, (idx, _) in enumerate(emb_results):
            scores[idx] = scores.get(idx, 0) + emb_weight / (k + rank + 1)
            if idx not in matched_terms:
                matched_terms[idx] = []
        
        # Sort by combined score
        combined = [(idx, score, matched_terms.get(idx, [])) for idx, score in scores.items()]
        combined.sort(key=lambda x: x[1], reverse=True)
        
        return combined
    
    def rebuild_index(self) -> None:
        """Force rebuild of the index."""
        self._index_loaded = False
        self._build_index()
        self._index_loaded = True
    
    @property
    def chunk_count(self) -> int:
        return len(self.chunks)


# ==============================================================================
# Context Builder for LLM
# ==============================================================================

def build_context_block(
    results: List[RetrievalResult],
    token_budget: int,
    token_counter: Callable[[str], int] = estimate_tokens,
) -> str:
    """
    Build context block from retrieval results within token budget.
    
    Args:
        results: Retrieval results to include
        token_budget: Maximum tokens for the context block
        token_counter: Function to count tokens
        
    Returns:
        Formatted context block string
    """
    if not results or token_budget <= 0:
        return ""
    
    header = """# Relevant Documentation Excerpts

The following excerpts were automatically retrieved from Microsoft Discovery documentation based on the user's question.

**Instructions for answering:**
- Use ONLY these excerpts as your source of truth
- If the excerpts don't contain the answer, say so explicitly
- Do not substitute information from other Microsoft products
- Cite the section title when referencing specific information

---
"""
    
    header_tokens = token_counter(header)
    if header_tokens >= token_budget:
        return ""
    
    remaining = token_budget - header_tokens
    parts = [header]
    
    for result in results:
        chunk = result.chunk
        
        section = f"\n## {chunk.title_path}\n\n{chunk.content.strip()}\n"
        section_tokens = token_counter(section)
        
        if section_tokens <= remaining:
            parts.append(section)
            remaining -= section_tokens
        elif remaining > 100:
            # Try to fit partial content
            prefix = f"\n## {chunk.title_path}\n\n"
            prefix_tokens = token_counter(prefix)
            
            available = remaining - prefix_tokens - 10
            if available > 50:
                # Truncate content
                content_lines = chunk.content.split("\n")
                kept_lines = []
                used = 0
                
                for line in content_lines:
                    line_tokens = token_counter(line + "\n")
                    if used + line_tokens > available:
                        break
                    kept_lines.append(line)
                    used += line_tokens
                
                if kept_lines:
                    parts.append(prefix + "\n".join(kept_lines) + "\n...[truncated]\n")
                    remaining -= prefix_tokens + used + 20
        
        if remaining < 50:
            break
    
    return "".join(parts).strip()


# ==============================================================================
# Convenience function for web_server.py integration
# ==============================================================================

_global_retriever: Optional[DiscoveryRetriever] = None


def get_retriever(
    docs_path: str,
    embedding_fn: Optional[Callable] = None,
    llm_rerank_fn: Optional[Callable] = None,
    force_rebuild: bool = False,
    **kwargs,
) -> DiscoveryRetriever:
    """
    Get or create the global retriever instance.
    
    Args:
        docs_path: Path to combined docs markdown file
        embedding_fn: Optional function to get embeddings
        llm_rerank_fn: Optional function for LLM reranking
        force_rebuild: Force index rebuild
        **kwargs: Additional arguments for DiscoveryRetriever
        
    Returns:
        DiscoveryRetriever instance
    """
    global _global_retriever
    
    if _global_retriever is None or force_rebuild:
        _global_retriever = DiscoveryRetriever(
            docs_path=docs_path,
            embedding_fn=embedding_fn,
            llm_rerank_fn=llm_rerank_fn,
            **kwargs,
        )
        if force_rebuild:
            _global_retriever.rebuild_index()
    
    return _global_retriever


def retrieve_docs(
    query: str,
    docs_path: str,
    top_k: int = DEFAULT_TOP_K,
    token_budget: int = 8000,
    embedding_fn: Optional[Callable] = None,
    llm_rerank_fn: Optional[Callable] = None,
    **kwargs,
) -> str:
    """
    High-level retrieval function for easy integration.
    
    Args:
        query: User query
        docs_path: Path to docs
        top_k: Number of chunks to retrieve
        token_budget: Max tokens for context
        embedding_fn: Optional embedding function
        llm_rerank_fn: Optional rerank function
        
    Returns:
        Formatted context block string
    """
    retriever = get_retriever(
        docs_path=docs_path,
        embedding_fn=embedding_fn,
        llm_rerank_fn=llm_rerank_fn,
        **kwargs,
    )
    
    results = retriever.retrieve(query, top_k=top_k)
    
    return build_context_block(results, token_budget)
