"""Tiny NLP pre-hooks for agent optimization.

This module lazily loads Hugging Face transformers pipelines to categorize tasks,
summarize large logs, and semantically retrieve tools before the primary model acts.
Optimized to prioritize the local Ollama deepseek-r1:8b model if available.
"""

from __future__ import annotations

import logging
import urllib.request
import json
from typing import Any

# Global singletons for lazy loading
_intent_classifier: Any = None
_summarizer: Any = None
_embedder: Any = None
_skill_embeddings_cache: dict[str, Any] = {}

logger = logging.getLogger(__name__)


_resolved_ollama_model: str | None = None


def _resolve_ollama_model() -> str:
    """Resolve the best available local Ollama model from active tags."""
    global _resolved_ollama_model
    if _resolved_ollama_model is not None:
        return _resolved_ollama_model
    
    default_model = "deepseek-r1:8b"
    try:
        url = "http://localhost:11434/api/tags"
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=1.5) as response:
            data = json.loads(response.read().decode("utf-8"))
            models = [m.get("name", "") for m in data.get("models", [])]
            
            # 1. Prioritize Gemma-4 12B/8B Agentic/Coder models (fits within memory threshold)
            for m in models:
                m_lower = m.lower()
                if "gemma-4" in m_lower and ("agentic" in m_lower or "coder" in m_lower) and "31b" not in m_lower:
                    _resolved_ollama_model = m
                    return m
            # 2. General agentic models
            for m in models:
                if "gemma-agentic" in m.lower():
                    _resolved_ollama_model = m
                    return m
            # 3. DeepSeek-R1 (default fallback reasoning model)
            for m in models:
                if "deepseek-r1" in m.lower():
                    _resolved_ollama_model = m
                    return m
            # 4. Any other non-embedding models
            for m in models:
                m_lower = m.lower()
                if m and "embed" not in m_lower and "bge" not in m_lower:
                    _resolved_ollama_model = m
                    return m
    except Exception:
        pass
    
    _resolved_ollama_model = default_model
    return default_model


def _query_ollama(prompt: str, system_prompt: str = "") -> str | None:
    """Synchronously query the local Ollama API with the resolved model."""
    try:
        url = "http://localhost:11434/api/chat"
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        
        data = {
            "model": _resolve_ollama_model(),
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": 0.1
            }
        }
        req = urllib.request.Request(
            url,
            data=json.dumps(data).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        # 4-second timeout for quick pre-hook checks
        with urllib.request.urlopen(req, timeout=4.0) as response:
            res_data = json.loads(response.read().decode("utf-8"))
            content = res_data.get("message", {}).get("content", "")
            
            # Strip <think>...</think> reasoning blocks if outputted by DeepSeek-R1
            if "<think>" in content:
                parts = content.split("</think>")
                if len(parts) > 1:
                    content = parts[1]
                else:
                    content = content.replace("<think>", "").replace("</think>", "")
            return content.strip()
    except Exception as e:
        logger.debug(f"Ollama local query bypassed: {e}")
        return None


async def _query_ollama_async(prompt: str, system_prompt: str = "") -> str | None:
    """Asynchronously query the local Ollama model using thread dispatch."""
    import anyio
    def _run():
        return _query_ollama(prompt, system_prompt)
    try:
        return await anyio.to_thread.run_sync(_run)
    except Exception:
        return None


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
    candidate_labels = [
        "debugging and fixing errors",
        "feature addition and coding",
        "refactoring code",
        "answering a question",
        "writing documentation"
    ]
    
    # Prioritize local Ollama deepseek-r1:8b
    system_prompt = (
        "You are an intent classifier. Categorize the user's task into EXACTLY one of the candidate labels. "
        "Do not invent new labels. Reply with ONLY the exact matching label string, no explanation, no markdown, and no extra text."
    )
    prompt = (
        f"Candidate labels:\n"
        f"- \"debugging and fixing errors\"\n"
        f"- \"feature addition and coding\"\n"
        f"- \"refactoring code\"\n"
        f"- \"answering a question\"\n"
        f"- \"writing documentation\"\n\n"
        f"Task:\n{task}"
    )
    ollama_res = await _query_ollama_async(prompt, system_prompt)
    if ollama_res:
        cleaned = ollama_res.lower().strip().strip('"').strip("'")
        for label in candidate_labels:
            if cleaned == label or cleaned in label or label in cleaned:
                return label

    classifier = _get_intent_classifier()
    if classifier is None:
        return None
    
    import anyio
    def _run():
        return classifier(task, candidate_labels)
        
    result = await anyio.to_thread.run_sync(_run)
    return result["labels"][0]


async def summarize_context(text: str) -> str | None:
    """Summarize a large context block (e.g. huge stack trace)."""
    if len(text) < 1000:
        return text  # Too short to summarize
        
    # Prioritize local Ollama deepseek-r1:8b
    prompt = (
        "Summarize the following context block (e.g. log files or stack trace) concisely. "
        "Focus on key error messages, line numbers, and actionable details. Keep the summary under 150 words.\n\n"
        f"Context:\n{text}"
    )
    ollama_res = await _query_ollama_async(prompt)
    if ollama_res:
        return ollama_res

    summarizer = _get_summarizer()
    if summarizer is None:
        return None
        
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
        
        def mean_pooling(model_output):
            if isinstance(model_output, list):
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
            
            cache_key = f"{skill.name}:{desc}"
            if cache_key in _skill_embeddings_cache:
                skill_emb = _skill_embeddings_cache[cache_key]
            else:
                skill_out = embedder(f"{skill.name}: {desc}")
                skill_emb = mean_pooling(skill_out)
                _skill_embeddings_cache[cache_key] = skill_emb
            
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
