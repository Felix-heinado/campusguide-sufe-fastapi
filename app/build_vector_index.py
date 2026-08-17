"""Build a small local document-vector index for optional hybrid retrieval."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from .config import get_settings
from .embeddings import create_embeddings, save_vector_index
from .knowledge_base import load_knowledge_base


def document_text(document: dict) -> str:
    """Use fields that describe meaning, while keeping one vector per document."""

    return "\n".join(str(document.get(key, "")) for key in (
        "title", "category", "issuer", "applies", "excerpt", "keywords", "note"
    ))


async def main() -> None:
    settings = get_settings()
    documents = load_knowledge_base().documents
    vectors: list[dict] = []
    batch_size = 20
    for start in range(0, len(documents), batch_size):
        batch = documents[start:start + batch_size]
        values = await create_embeddings([document_text(item) for item in batch], settings)
        vectors.extend(
            {"documentId": document["id"], "values": vector}
            for document, vector in zip(batch, values, strict=True)
        )
        print(f"embedded {min(start + batch_size, len(documents))}/{len(documents)} documents")

    save_vector_index(settings.embedding_index_path, {
        "model": settings.siliconflow_embedding_model,
        "createdAt": datetime.now(UTC).isoformat(),
        "documentCount": len(documents),
        "dimensions": len(vectors[0]["values"]) if vectors else 0,
        "vectors": vectors,
    })
    print(f"saved vector index: {settings.embedding_index_path}")


if __name__ == "__main__":
    asyncio.run(main())

