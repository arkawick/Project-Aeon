import os
import asyncio
from typing import Any


class ChromaStore:
    def __init__(self):
        self.host = os.getenv("CHROMA_HOST", "localhost")
        self.port = int(os.getenv("CHROMA_PORT", "8001"))
        self.collection = None
        self._connect()

    def _connect(self):
        try:
            import chromadb

            client = chromadb.HttpClient(host=self.host, port=self.port)
            self.collection = client.get_or_create_collection(
                name="incidents",
                metadata={"hnsw:space": "cosine"},
            )
            print(f"[ChromaStore] Connected at {self.host}:{self.port}")
        except Exception as exc:
            print(f"[ChromaStore] Connection failed: {exc}. Running in no-op mode.")
            self.collection = None

    # ------------------------------------------------------------------
    # Sync helpers (run inside asyncio.to_thread)
    # ------------------------------------------------------------------

    def _sync_upsert(self, incident_id: str, document: str, metadata: dict) -> bool:
        self.collection.upsert(
            ids=[incident_id],
            documents=[document],
            metadatas=[metadata],
        )
        return True

    def _sync_query(self, query_text: str, top_k: int) -> list[dict[str, Any]]:
        results = self.collection.query(
            query_texts=[query_text[:2000]],
            n_results=min(top_k, self.collection.count() or 1),
            include=["documents", "metadatas", "distances"],
        )
        similar = []
        for i, doc_id in enumerate(results["ids"][0]):
            similar.append({
                "id": doc_id,
                "document": results["documents"][0][i],
                "metadata": results["metadatas"][0][i],
                "similarity": round(1 - results["distances"][0][i], 4),
            })
        return similar

    def _sync_get(self, incident_id: str) -> dict[str, Any] | None:
        result = self.collection.get(ids=[incident_id], include=["documents", "metadatas"])
        if result["ids"]:
            return {
                "id": result["ids"][0],
                "document": result["documents"][0],
                "metadata": result["metadatas"][0],
            }
        return None

    def _sync_list(self, limit: int) -> list[dict[str, Any]]:
        result = self.collection.get(
            limit=limit,
            include=["documents", "metadatas"],
        )
        items = []
        for i, doc_id in enumerate(result["ids"]):
            items.append({
                "id": doc_id,
                "document": result["documents"][i],
                "metadata": result["metadatas"][i],
            })
        return items

    # ------------------------------------------------------------------
    # Public async API
    # ------------------------------------------------------------------

    async def store_incident(
        self,
        incident_id: str,
        description: str,
        logs: str,
        root_cause: str,
        fix: str,
        extra_metadata: dict | None = None,
    ) -> bool:
        if self.collection is None:
            return False
        try:
            document = (
                f"Description: {description}\n\n"
                f"Root cause: {root_cause}\n\n"
                f"Fix: {fix}\n\n"
                f"Log excerpt: {logs[:500]}"
            )
            metadata: dict[str, Any] = {
                "incident_id": incident_id,
                "root_cause": root_cause[:500],
                "fix": fix[:500],
                "logs_snippet": logs[:300],
            }
            if extra_metadata:
                metadata.update(extra_metadata)

            return await asyncio.to_thread(self._sync_upsert, incident_id, document, metadata)
        except Exception as exc:
            print(f"[ChromaStore] store_incident error: {exc}")
            return False

    async def search_similar(self, log_text: str, top_k: int = 3) -> list[dict[str, Any]]:
        if self.collection is None:
            return []
        try:
            count = await asyncio.to_thread(lambda: self.collection.count())
            if count == 0:
                return []
            return await asyncio.to_thread(self._sync_query, log_text, top_k)
        except Exception as exc:
            print(f"[ChromaStore] search_similar error: {exc}")
            return []

    async def get_incident(self, incident_id: str) -> dict[str, Any] | None:
        if self.collection is None:
            return None
        try:
            return await asyncio.to_thread(self._sync_get, incident_id)
        except Exception as exc:
            print(f"[ChromaStore] get_incident error: {exc}")
            return None

    async def list_incidents(self, limit: int = 20) -> list[dict[str, Any]]:
        if self.collection is None:
            return []
        try:
            return await asyncio.to_thread(self._sync_list, limit)
        except Exception as exc:
            print(f"[ChromaStore] list_incidents error: {exc}")
            return []

    async def count(self) -> int:
        if self.collection is None:
            return 0
        try:
            return await asyncio.to_thread(lambda: self.collection.count())
        except Exception:
            return 0
