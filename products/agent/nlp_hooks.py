"""Tiny NLP pre-hooks for agent optimization.

This module lazily loads Hugging Face transformers pipelines to categorize tasks,
summarize large logs, and semantically retrieve tools before the primary model acts.
"""

from __future__ import annotations

import logging
from typing import Any

# Global singletons for lazy loading
_intent_classifier: Any = None
_summarizer: Any = None
_embedder: Any = None

logger = logging.getLogger(__name__)


def _get_intent_classifier() -> Any:
    global _intent_classifier
    if _intent_classifier is None:
        try:
            from transformers import pipeline
            # BART Large MNLI is much more robust for zero-shot classification
            _intent_classifier = pipeline(
                "zero-shot-classification",
                model="facebook/bart-large-mnli"
            )
        except ImportError:
            logger.warning("transformers not installed; NLP hooks disabled.")
            return None
    return _intent_classifier


def _get_summarizer() -> Any:
    global _summarizer
    if _summarizer is None:
        try:
            from transformers import pipeline
            _summarizer = pipeline(
                "summarization",
                model="sshleifer/distilbart-cnn-12-6"
            )
        except ImportError:
            return None
    return _summarizer


def _get_embedder() -> Any:
    global _embedder
    if _embedder is None:
        try:
            from transformers import pipeline
            _embedder = pipeline(
                "feature-extraction",
                model="sentence-transformers/all-MiniLM-L6-v2"
            )
        except ImportError:
            return None
    return _embedder


async def classify_intent(task: str) -> str | None:
    """Classify the user's task into a category."""
    classifier = _get_intent_classifier()
    if classifier is None:
        return None
    
    candidate_labels = [
        "debugging and fixing errors",
        "feature addition and coding",
        "refactoring code",
        "answering a question",
        "writing documentation"
    ]
    
    # Run synchronously in a thread to avoid blocking async loop
    import anyio
    def _run():
        return classifier(task, candidate_labels)
        
    result = await anyio.to_thread.run_sync(_run)
    return result["labels"][0]


async def summarize_context(text: str) -> str | None:
    """Summarize a large context block (e.g. huge stack trace)."""
    summarizer = _get_summarizer()
    if summarizer is None:
        return None
        
    if len(text) < 1000:
        return text  # Too short to summarize
        
    # Cap input to avoid breaking the model's max token length
    # Distilbart usually takes ~1024 tokens. We'll give it roughly 4000 chars.
    truncated_text = text[:4000]
    
    import anyio
    def _run():
        return summarizer(truncated_text, max_length=130, min_length=30, do_sample=False)
        
    try:
        result = await anyio.to_thread.run_sync(_run)
        return result[0]["summary_text"]
    except Exception as exc:
        logger.warning(f"Summarization failed: {exc}")
        return None

async def retrieve_skills(task: str, registry: Any) -> list[str]:
    """Retrieve the top 3 relevant skills from the registry based on semantic similarity."""
    embedder = _get_embedder()
    if embedder is None:
        return []
        
    skills = registry.by_kind("skill")
    if not skills:
        return []
        
    import anyio
    
    def _run():
        import torch
        # We use pipeline("feature-extraction") which returns a nested list of embeddings
        # shape: [batch, sequence_length, hidden_size]. We mean pool it.
        
        def mean_pooling(model_output):
            if isinstance(model_output, list):
                # Just take the mean of the tokens
                tensor = torch.tensor(model_output[0])
                return torch.mean(tensor, dim=0)
            return torch.mean(model_output, dim=0)

        # 1. Embed task
        task_out = embedder(task)
        task_emb = mean_pooling(task_out)

        # 2. Embed skills
        scored_skills = []
        for skill in skills:
            desc = skill.description or skill.name
            skill_out = embedder(f"{skill.name}: {desc}")
            skill_emb = mean_pooling(skill_out)
            
            # Cosine similarity
            cos_sim = torch.nn.functional.cosine_similarity(task_emb.unsqueeze(0), skill_emb.unsqueeze(0))
            scored_skills.append((cos_sim.item(), skill))
            
        # 3. Sort and return top 3
        scored_skills.sort(key=lambda x: x[0], reverse=True)
        top_skills = scored_skills[:3]
        return [f"- {s.name}: {s.description}" for score, s in top_skills]
        
    try:
        return await anyio.to_thread.run_sync(_run)
    except Exception as exc:
        logger.warning(f"Semantic retrieval failed: {exc}")
        return []
