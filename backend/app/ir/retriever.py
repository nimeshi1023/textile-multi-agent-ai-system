"""
Information Retrieval over the SOP knowledge base. No LLM, no API key.

Two backends behind one interface, search(query, top_k, category):
  1. "chroma+minilm" - ChromaDB vector store (persistent, knowledge_base/chroma/)
                       + local sentence-transformers model all-MiniLM-L6-v2.
                       The model is loaded with local_files_only=True, so the API
                       never goes online (it is downloaded once by build_index).
  2. "tfidf"         - scikit-learn TF-IDF + cosine similarity, built in memory
                       from the same documents. Used automatically if chromadb /
                       sentence-transformers / the model cannot be loaded.
Scores are cosine similarities clipped to 0..1. Results below the backend's
minimum score are dropped, so unrelated documents are never returned.
"""
import logging
import os
from pathlib import Path
from typing import Dict, List, Optional

from app.ir.kb_loader import chunk_id, embedding_text, load_documents

logger = logging.getLogger(__name__)


# ---- Retrieval settings ----
DEFAULT_TOP_K = 3
# Minimum scores, tuned on the Phase 4 test queries plus unrelated control queries:
#   MiniLM: relevant top hits scored >= 0.41, unrelated controls <= 0.17
#   TF-IDF: scores are lower (exact word overlap only); controls reached 0.11
MIN_SCORE_MINILM = 0.30
MIN_SCORE_TFIDF = 0.12

EMBEDDING_MODEL = "all-MiniLM-L6-v2"
COLLECTION_NAME = "fabricflow_sops"
INDEX_DIR = Path(__file__).resolve().parents[1] / "knowledge_base" / "chroma"
BUILD_COMMAND = "cd backend && python -m app.ir.build_index"

# Set FABRICFLOW_RETRIEVER=tfidf to force the TF-IDF backend (tests, demos)
FORCE_BACKEND_ENV = "FABRICFLOW_RETRIEVER"


class IndexNotBuiltError(RuntimeError):
    def __init__(self):
        super().__init__(f"Knowledge-base index not built. Run: {BUILD_COMMAND}")


def _result(doc: Dict, score: float) -> Dict:
    return {
        "document_id": doc["document_id"],
        "title": doc["title"],
        "category": doc["category"],
        "tags": doc["tags"],
        "text": doc["body"],
        "score": round(max(0.0, min(1.0, float(score))), 4),
        "source_file": doc["source_file"],
    }


def _dedupe_by_document(results: List[Dict], top_k: int) -> List[Dict]:
    """Keep the best chunk per document (documents are one chunk today)."""
    seen, unique = set(), []
    for r in sorted(results, key=lambda r: -r["score"]):
        if r["document_id"] not in seen:
            seen.add(r["document_id"])
            unique.append(r)
    return unique[:top_k]


class TfidfRetriever:
    name = "tfidf"
    min_score = MIN_SCORE_TFIDF

    def __init__(self, documents: Optional[List[Dict]] = None):
        from sklearn.feature_extraction.text import TfidfVectorizer

        self.documents = documents or load_documents()
        self.vectorizer = TfidfVectorizer(stop_words="english", ngram_range=(1, 2), sublinear_tf=True)
        self.matrix = self.vectorizer.fit_transform([embedding_text(d) for d in self.documents])

    def search(self, query: str, top_k: int = DEFAULT_TOP_K, category: Optional[str] = None) -> List[Dict]:
        from sklearn.metrics.pairwise import cosine_similarity

        scores = cosine_similarity(self.vectorizer.transform([query]), self.matrix)[0]
        results = [
            _result(doc, score)
            for doc, score in zip(self.documents, scores)
            if score >= self.min_score and (category is None or doc["category"].lower() == category.lower())
        ]
        return _dedupe_by_document(results, top_k)

    def list_documents(self) -> List[Dict]:
        return self.documents


class ChromaRetriever:
    name = "chroma+minilm"
    min_score = MIN_SCORE_MINILM

    def __init__(self, index_dir: Path = INDEX_DIR):
        import chromadb
        from sentence_transformers import SentenceTransformer

        if not (Path(index_dir) / "chroma.sqlite3").exists():
            raise IndexNotBuiltError()
        client = chromadb.PersistentClient(path=str(index_dir))
        try:
            self.collection = client.get_collection(COLLECTION_NAME)
        except Exception as e:
            raise IndexNotBuiltError() from e
        if self.collection.count() == 0:
            raise IndexNotBuiltError()
        # Offline: only use the locally cached model (downloaded by build_index)
        self.model = SentenceTransformer(EMBEDDING_MODEL, local_files_only=True)
        self.documents = {chunk_id(d): d for d in load_documents()}

    def search(self, query: str, top_k: int = DEFAULT_TOP_K, category: Optional[str] = None) -> List[Dict]:
        embedding = self.model.encode([query], normalize_embeddings=True).tolist()
        n = min(self.collection.count(), max(top_k * 3, top_k))
        found = self.collection.query(
            query_embeddings=embedding,
            n_results=n,
            where={"category": category} if category else None,
            include=["distances"],
        )
        results = []
        for cid, distance in zip(found["ids"][0], found["distances"][0]):
            doc = self.documents.get(cid)
            if doc is None:
                continue  # index is older than the docs; rebuild it
            score = 1.0 - float(distance)        # cosine distance -> cosine similarity
            if score >= self.min_score:
                results.append(_result(doc, score))
        return _dedupe_by_document(results, top_k)

    def list_documents(self) -> List[Dict]:
        return list(self.documents.values())


_retriever = None


def get_retriever():
    """Pick and cache the retrieval backend (see module docstring)."""
    global _retriever
    if _retriever is not None:
        return _retriever

    if os.getenv(FORCE_BACKEND_ENV, "").strip().lower() == "tfidf":
        _retriever = TfidfRetriever()
    else:
        try:
            _retriever = ChromaRetriever()
        except IndexNotBuiltError:
            raise
        except Exception as e:   # ImportError, model not cached, ...
            logger.warning(f"Vector retriever unavailable ({type(e).__name__}: {e}); using TF-IDF fallback")
            _retriever = TfidfRetriever()
    logger.info(f"Knowledge-base retrieval backend: {_retriever.name}")
    return _retriever


def reset_retriever() -> None:
    global _retriever
    _retriever = None


def search(query: str, top_k: int = DEFAULT_TOP_K, category: Optional[str] = None) -> List[Dict]:
    return get_retriever().search(query, top_k=top_k, category=category)


def backend_name() -> str:
    return get_retriever().name
