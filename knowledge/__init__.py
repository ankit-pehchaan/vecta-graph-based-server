"""
Australian Financial Knowledge Base for Vecta.

Uses LanceDB (serverless, file-based) + Agno's TextKnowledgeBase for
semantic retrieval of Australian financial context during goal exploration.

Graceful degradation: if LanceDB or knowledge files are unavailable,
the system continues without knowledge base augmentation.
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_knowledge_instance = None


def get_australian_knowledge():
    """
    Get or create the Australian financial knowledge base.

    Returns an Agno TextKnowledgeBase backed by LanceDB, or None
    if dependencies are missing.
    """
    global _knowledge_instance

    if _knowledge_instance is not None:
        return _knowledge_instance

    try:
        from agno.knowledge.text import TextKnowledgeBase
        from agno.vectordb.lancedb import LanceDb

        from config import Config

        knowledge_dir = Path(__file__).parent / "australian_context"
        if not knowledge_dir.exists() or not any(knowledge_dir.glob("*.txt")):
            logger.info(
                "No Australian context files found in %s; "
                "knowledge base will be empty.",
                knowledge_dir,
            )
            return None

        _knowledge_instance = TextKnowledgeBase(
            path=str(knowledge_dir),
            vector_db=LanceDb(
                table_name=Config.LANCEDB_TABLE,
                uri=Config.LANCEDB_URI,
            ),
        )
        logger.info("Australian knowledge base loaded from %s", knowledge_dir)
        return _knowledge_instance

    except ImportError as e:
        logger.info("Knowledge base dependencies not installed (%s); skipping.", e)
        return None
    except Exception as e:
        logger.warning("Failed to load knowledge base: %s", e)
        return None
