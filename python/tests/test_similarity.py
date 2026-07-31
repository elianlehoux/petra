import pytest
from compiled_ai_router.similarity import compute_similarity, normalize_prompt, find_similar_artifact
from compiled_ai_router.models import CompiledArtifact

def test_normalize_prompt():
    p = "  Extract   Data  FROM   INVOICE!  "
    norm = normalize_prompt(p)
    assert norm == "extract data from invoice!"

def test_compute_similarity_high():
    p1 = "Extract total amount from invoice text"
    p2 = "Extract total amount from invoice document"
    sim = compute_similarity(p1, p2)
    assert sim > 0.7

def test_compute_similarity_low():
    p1 = "Extract invoice amount"
    p2 = "Clean CSV columns"
    sim = compute_similarity(p1, p2)
    assert sim < 0.3

def test_find_similar_artifact():
    art1 = CompiledArtifact(
        id="art1",
        prompt_hash="h1",
        original_prompt="Extract invoice number and date",
        script_content="pass",
        task_type="extraction"
    )
    artifacts = [art1]
    match = find_similar_artifact("Extract invoice number and payment date", artifacts, threshold=0.6)
    assert match is not None
    assert match.id == "art1"