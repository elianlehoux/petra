import re
from typing import Optional, List
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from .models import CompiledArtifact

def normalize_prompt(prompt: str) -> str:
    prompt = prompt.lower()
    prompt = re.sub(r'\s+', ' ', prompt)
    prompt = prompt.strip()
    return prompt

def compute_similarity(prompt1: str, prompt2: str) -> float:
    norm1 = normalize_prompt(prompt1)
    norm2 = normalize_prompt(prompt2)
    if not norm1 or not norm2:
        return 0.0
    
    vectorizer = TfidfVectorizer()
    try:
        tfidf_matrix = vectorizer.fit_transform([norm1, norm2])
        sim = cosine_similarity(tfidf_matrix[0:1], tfidf_matrix[1:2])[0][0]
        return float(sim)
    except ValueError:
        return 0.0

def find_similar_artifact(prompt: str, artifacts: List[CompiledArtifact], threshold: float) -> Optional[CompiledArtifact]:
    best_artifact = None
    best_score = -1.0
    
    for artifact in artifacts:
        score = compute_similarity(prompt, artifact.original_prompt)
        if score > best_score and score >= threshold:
            best_score = score
            best_artifact = artifact
            
    return best_artifact
