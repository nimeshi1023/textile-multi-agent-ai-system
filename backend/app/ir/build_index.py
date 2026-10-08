"""
Build the knowledge-base vector index from scratch.

Run from the backend folder:
    cd backend
    python -m app.ir.build_index

Reads knowledge_base/docs/ (read-only), embeds every document with the local
sentence-transformers model all-MiniLM-L6-v2 (downloaded once, then offline) and
stores the vectors in ChromaDB at knowledge_base/chroma/. Never runs on API start.
"""
import json
from datetime import datetime, timezone

from app.ir.kb_loader import DOCS_DIR, chunk_id, embedding_text, load_documents
from app.ir.retriever import COLLECTION_NAME, EMBEDDING_MODEL, INDEX_DIR


def build_index() -> int:
    documents = load_documents()
    print(f"Loaded {len(documents)} documents from {DOCS_DIR}")

    try:
        import chromadb
        from sentence_transformers import SentenceTransformer
    except ImportError as e:
        print(f"Cannot build the vector index ({e}).")
        print("The API will use the TF-IDF fallback retriever, which needs no index.")
        return 0

    model = SentenceTransformer(EMBEDDING_MODEL)   # downloads on first run only
    embeddings = model.encode([embedding_text(d) for d in documents], normalize_embeddings=True)

    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(INDEX_DIR))
    if COLLECTION_NAME in [c.name for c in client.list_collections()]:
        client.delete_collection(COLLECTION_NAME)   # rebuild from scratch
    collection = client.create_collection(COLLECTION_NAME, metadata={"hnsw:space": "cosine"})
    collection.add(
        ids=[chunk_id(d) for d in documents],
        embeddings=embeddings.tolist(),
        documents=[embedding_text(d) for d in documents],
        metadatas=[
            {
                "document_id": d["document_id"],
                "title": d["title"],
                "category": d["category"],
                "tags": ", ".join(d["tags"]),
                "source_file": d["source_file"],
                "chunk_index": d["chunk_index"],
            }
            for d in documents
        ],
    )

    manifest = {
        "collection": COLLECTION_NAME,
        "embedding_model": EMBEDDING_MODEL,
        "documents_indexed": collection.count(),
        "document_ids": [chunk_id(d) for d in documents],
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    (INDEX_DIR / "index_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Indexed {collection.count()} documents into ChromaDB at {INDEX_DIR} (model: {EMBEDDING_MODEL})")
    return collection.count()


if __name__ == "__main__":
    build_index()
