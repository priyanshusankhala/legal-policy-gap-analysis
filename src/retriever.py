"""
Hybrid Multilingual Neural + Compound-Aware Lexical Retriever.
Combines dense SentenceTransformer embeddings (paraphrase-multilingual-MiniLM-L12-v2)
with stopword-filtered word + character-ngram TF-IDF cosine similarity.
"""
from dataclasses import dataclass
import re
from typing import List, Optional, Set
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from src.corpus import EvidenceUnit

try:
    from sentence_transformers import SentenceTransformer
except ImportError:  # pragma: no cover
    SentenceTransformer = None


GENERIC_STOPWORDS: Set[str] = {
    "der", "die", "das", "und", "oder", "für", "von", "mit", "zur", "zum", "des", "den", "dem",
    "ein", "eine", "einer", "eines", "im", "in", "auf", "aus", "nach", "über", "unter", "als",
    "the", "and", "for", "with", "from", "into", "that", "this", "are", "was", "were",
    "informationssicherheit", "sicherheit", "bsig", "abs", "nis2", "status", "offen", "active",
    "legal", "area", "register", "obligations", "internal", "controls", "marenthal", "chemie", "ag",
}


def extract_specific_stems(text: str) -> Set[str]:
    """Extract informative domain stems (6-char prefixes) excluding generic boilerplate."""
    tokens = re.findall(r"[a-zäöüß]{5,}", text.lower())
    stems: Set[str] = set()
    for tok in tokens:
        if tok in GENERIC_STOPWORDS:
            continue
        stems.add(tok[:7])
    return stems


@dataclass
class ScoredEvidence:
    unit: EvidenceUnit
    score: float
    dense_score: float
    lexical_score: float
    stem_overlap: int


class HybridRetriever:
    """Indexes corpus evidence units once and performs hybrid semantic+lexical search."""

    DEFAULT_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"

    def __init__(
        self,
        units: List[EvidenceUnit],
        model_name: str = DEFAULT_MODEL,
        use_dense: bool = True,
    ):
        self.units = units
        self.texts = [u.text for u in units]
        self.unit_stems = [extract_specific_stems(u.text) for u in units]
        self.dense_enabled = False
        self._embedder = None
        self._doc_embeddings: Optional[np.ndarray] = None

        self._word_tfidf = TfidfVectorizer(
            ngram_range=(1, 2),
            sublinear_tf=True,
            stop_words=list(GENERIC_STOPWORDS),
            max_features=15000,
        )
        self._char_tfidf = TfidfVectorizer(
            analyzer="char_wb",
            ngram_range=(4, 6),
            sublinear_tf=True,
            max_features=25000,
        )

        if self.texts:
            try:
                self._word_matrix = self._word_tfidf.fit_transform(self.texts)
            except ValueError:
                self._word_matrix = None
            self._char_matrix = self._char_tfidf.fit_transform(self.texts)
        else:
            self._word_matrix = None
            self._char_matrix = None

        if use_dense and SentenceTransformer is not None and self.texts:
            try:
                self._embedder = SentenceTransformer(model_name, local_files_only=False)
                self._doc_embeddings = self._embedder.encode(
                    self.texts,
                    normalize_embeddings=True,
                    show_progress_bar=False,
                )
                self.dense_enabled = True
            except Exception:
                self.dense_enabled = False

    def search(self, query: str, top_k: int = 8) -> List[ScoredEvidence]:
        """Rank all evidence units for a requirement query."""
        if not self.units or self._char_matrix is None:
            return []

        q_stems = extract_specific_stems(query)
        char_scores = cosine_similarity(self._char_tfidf.transform([query]), self._char_matrix).ravel()
        if self._word_matrix is not None:
            word_scores = cosine_similarity(self._word_tfidf.transform([query]), self._word_matrix).ravel()
            lex_scores = 0.70 * word_scores + 0.30 * char_scores
        else:
            lex_scores = char_scores

        if self.dense_enabled and self._embedder is not None and self._doc_embeddings is not None:
            q_emb = self._embedder.encode([query], normalize_embeddings=True, show_progress_bar=False)
            dense_scores = np.dot(self._doc_embeddings, q_emb.T).ravel()
            dense_clipped = np.clip(dense_scores, 0.0, 1.0)
            combined = 0.60 * dense_clipped + 0.40 * lex_scores
        else:
            dense_clipped = np.zeros_like(lex_scores)
            combined = lex_scores

        ranked_indices = np.argsort(combined)[::-1][:top_k]
        results: List[ScoredEvidence] = []
        for idx in ranked_indices:
            i = int(idx)
            overlap = len(q_stems & self.unit_stems[i])
            results.append(
                ScoredEvidence(
                    unit=self.units[i],
                    score=float(combined[i]),
                    dense_score=float(dense_clipped[i]),
                    lexical_score=float(lex_scores[i]),
                    stem_overlap=overlap,
                )
            )
        return results