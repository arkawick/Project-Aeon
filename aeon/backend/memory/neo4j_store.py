import os
import time
import asyncio
from typing import Any


class Neo4jStore:
    def __init__(self):
        self.uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
        self.user = os.getenv("NEO4J_USER", "neo4j")
        self.password = os.getenv("NEO4J_PASSWORD", "aeon_neo4j")
        self.driver = None
        self._last_connect_attempt = 0.0
        self._reconnect_cooldown = 5.0  # seconds between reconnect attempts
        self._connect()

    def _connect(self):
        self._last_connect_attempt = time.monotonic()
        try:
            from neo4j import GraphDatabase

            self.driver = GraphDatabase.driver(
                self.uri, auth=(self.user, self.password)
            )
            self.driver.verify_connectivity()
            print(f"[Neo4jStore] Connected at {self.uri}")
        except Exception as exc:
            print(f"[Neo4jStore] Connection failed: {exc}. Running in no-op mode.")
            self.driver = None

    def _ensure_driver(self) -> bool:
        """Self-heal the cold-start race: if the driver never came up (Neo4j's
        bolt port lagged the backend at boot), retry the connection here instead
        of no-op'ing for the rest of the process life. Throttled so a genuinely
        down Neo4j isn't hammered on every call. Returns True if usable."""
        if self.driver is not None:
            return True
        if time.monotonic() - self._last_connect_attempt < self._reconnect_cooldown:
            return False
        self._connect()
        return self.driver is not None

    # ------------------------------------------------------------------
    # Sync helpers (run inside asyncio.to_thread)
    # ------------------------------------------------------------------

    def _run_query(self, cypher: str, **params) -> list[dict[str, Any]]:
        with self.driver.session() as session:
            result = session.run(cypher, **params)
            return [dict(r) for r in result]

    def _sync_store_incident(
        self,
        incident_id: str,
        pipeline_id: str,
        error_type: str,
        fix_description: str,
        severity: str = "medium",
    ) -> bool:
        with self.driver.session() as session:
            session.run(
                """
                MERGE (i:Incident {id: $incident_id})
                  SET i.severity = $severity, i.updated = timestamp()
                MERGE (p:Pipeline {id: $pipeline_id})
                MERGE (i)-[:CAUSED_BY]->(p)
                MERGE (e:ErrorType {name: $error_type})
                MERGE (i)-[:HAS_ERROR]->(e)
                MERGE (f:Fix {description: $fix_description})
                  ON CREATE SET f.created = timestamp()
                MERGE (i)-[:RESOLVED_BY]->(f)
                MERGE (e)-[:FIXED_BY]->(f)
                  ON MATCH SET f.use_count = coalesce(f.use_count, 0) + 1
                """,
                incident_id=incident_id,
                pipeline_id=pipeline_id,
                error_type=error_type,
                fix_description=fix_description,
                severity=severity,
            )
        return True

    def _sync_find_similar_errors(self, error_type: str) -> dict[str, Any]:
        records = self._run_query(
            """
            MATCH (e:ErrorType {name: $error_type})-[:FIXED_BY]->(f:Fix)
            OPTIONAL MATCH (i:Incident)-[:HAS_ERROR]->(e)
            RETURN e.name AS error_type,
                   collect(DISTINCT f.description) AS fixes,
                   count(DISTINCT i) AS occurrence_count
            """,
            error_type=error_type,
        )
        return {"error_type": error_type, "records": records}

    def _sync_get_error_fix_history(self, error_type: str) -> list[dict[str, Any]]:
        """Return all incidents + their fixes for a given error type."""
        return self._run_query(
            """
            MATCH (i:Incident)-[:HAS_ERROR]->(e:ErrorType {name: $error_type})
            OPTIONAL MATCH (i)-[:RESOLVED_BY]->(f:Fix)
            OPTIONAL MATCH (i)-[:CAUSED_BY]->(p:Pipeline)
            RETURN i.id AS incident_id,
                   i.severity AS severity,
                   p.id AS pipeline_id,
                   f.description AS fix,
                   f.use_count AS fix_use_count
            ORDER BY i.id DESC
            LIMIT 10
            """,
            error_type=error_type,
        )

    def _sync_get_incident_graph(self, incident_id: str) -> dict[str, Any]:
        rows = self._run_query(
            """
            MATCH (i:Incident {id: $incident_id})-[r]->(n)
            RETURN labels(i)[0] AS from_label, i.id AS from_id,
                   type(r) AS relationship,
                   labels(n)[0] AS to_label,
                   coalesce(n.id, n.name, n.description) AS to_id
            """,
            incident_id=incident_id,
        )
        nodes: list[dict] = [{"id": incident_id, "label": "Incident"}]
        edges: list[dict] = []
        seen: set[str] = {incident_id}

        for row in rows:
            to_id = str(row["to_id"])
            if to_id not in seen:
                nodes.append({"id": to_id, "label": row["to_label"]})
                seen.add(to_id)
            edges.append({
                "from": incident_id,
                "to": to_id,
                "type": row["relationship"],
            })
        return {"nodes": nodes, "edges": edges}

    def _sync_get_full_graph(self) -> dict[str, Any]:
        rows = self._run_query(
            """
            MATCH (n)-[r]->(m)
            RETURN labels(n)[0] AS from_label,
                   coalesce(n.id, n.name, n.description) AS from_id,
                   type(r) AS relationship,
                   labels(m)[0] AS to_label,
                   coalesce(m.id, m.name, m.description) AS to_id
            """
        )
        nodes: dict[str, dict] = {}
        edges: list[dict] = []
        for row in rows:
            from_id = str(row["from_id"])
            to_id = str(row["to_id"])
            if from_id not in nodes:
                nodes[from_id] = {"id": from_id, "label": row["from_label"]}
            if to_id not in nodes:
                nodes[to_id] = {"id": to_id, "label": row["to_label"]}
            edges.append({"source": from_id, "target": to_id, "type": row["relationship"]})
        return {"nodes": list(nodes.values()), "edges": edges}

    def _sync_get_top_errors(self, limit: int = 10) -> list[dict[str, Any]]:
        return self._run_query(
            """
            MATCH (i:Incident)-[:HAS_ERROR]->(e:ErrorType)
            RETURN e.name AS error_type, count(i) AS occurrence_count
            ORDER BY occurrence_count DESC
            LIMIT $limit
            """,
            limit=limit,
        )

    # ------------------------------------------------------------------
    # Public async API
    # ------------------------------------------------------------------

    async def store_incident(
        self,
        incident_id: str,
        pipeline_id: str,
        error_type: str,
        fix_description: str,
        severity: str = "medium",
    ) -> bool:
        if self.driver is None and not await asyncio.to_thread(self._ensure_driver):
            return False
        try:
            return await asyncio.to_thread(
                self._sync_store_incident,
                incident_id, pipeline_id, error_type, fix_description, severity,
            )
        except Exception as exc:
            print(f"[Neo4jStore] store_incident error: {exc}")
            return False

    async def find_similar_errors(self, error_type: str) -> dict[str, Any]:
        if self.driver is None and not await asyncio.to_thread(self._ensure_driver):
            return {"error_type": error_type, "records": []}
        try:
            return await asyncio.to_thread(self._sync_find_similar_errors, error_type)
        except Exception as exc:
            print(f"[Neo4jStore] find_similar_errors error: {exc}")
            return {"error_type": error_type, "records": []}

    async def get_error_fix_history(self, error_type: str) -> list[dict[str, Any]]:
        if self.driver is None and not await asyncio.to_thread(self._ensure_driver):
            return []
        try:
            return await asyncio.to_thread(self._sync_get_error_fix_history, error_type)
        except Exception as exc:
            print(f"[Neo4jStore] get_error_fix_history error: {exc}")
            return []

    async def get_incident_graph(self, incident_id: str) -> dict[str, Any]:
        if self.driver is None and not await asyncio.to_thread(self._ensure_driver):
            return {"nodes": [], "edges": []}
        try:
            return await asyncio.to_thread(self._sync_get_incident_graph, incident_id)
        except Exception as exc:
            print(f"[Neo4jStore] get_incident_graph error: {exc}")
            return {"nodes": [], "edges": []}

    async def get_full_graph(self) -> dict[str, Any]:
        if self.driver is None and not await asyncio.to_thread(self._ensure_driver):
            return {"nodes": [], "edges": []}
        try:
            return await asyncio.to_thread(self._sync_get_full_graph)
        except Exception as exc:
            print(f"[Neo4jStore] get_full_graph error: {exc}")
            return {"nodes": [], "edges": []}

    async def get_top_errors(self, limit: int = 10) -> list[dict[str, Any]]:
        if self.driver is None and not await asyncio.to_thread(self._ensure_driver):
            return []
        try:
            return await asyncio.to_thread(self._sync_get_top_errors, limit)
        except Exception as exc:
            print(f"[Neo4jStore] get_top_errors error: {exc}")
            return []

    # ------------------------------------------------------------------
    # Provenance graph
    # ------------------------------------------------------------------

    def _sync_store_provenance_graph(
        self, repo: str, file_path: str, nodes: list[dict], edges: list[dict]
    ) -> bool:
        with self.driver.session() as session:
            for n in nodes:
                props = {k: v for k, v in n.items() if k not in ("color",)}
                session.run(
                    """
                    MERGE (n:ProvenanceNode {id: $id})
                    SET n += $props, n.repo = $repo, n.file_path = $file_path
                    """,
                    id=n["id"], props=props, repo=repo, file_path=file_path,
                )
            for e in edges:
                session.run(
                    f"""
                    MATCH (a:ProvenanceNode {{id: $source}})
                    MATCH (b:ProvenanceNode {{id: $target}})
                    MERGE (a)-[r:{e['type']}]->(b)
                    """,
                    source=e["source"], target=e["target"],
                )
        return True

    def _sync_get_provenance_graph(self, repo: str, file_path: str) -> dict:
        nodes_raw = self._run_query(
            """
            MATCH (n:ProvenanceNode {repo: $repo, file_path: $file_path})
            RETURN n
            """,
            repo=repo, file_path=file_path,
        )
        if not nodes_raw:
            return {"nodes": [], "edges": [], "cached": False}

        node_ids = {row["n"]["id"] for row in nodes_raw}
        edges_raw = self._run_query(
            """
            MATCH (a:ProvenanceNode {repo: $repo})-[r]->(b:ProvenanceNode {repo: $repo})
            WHERE a.file_path = $file_path
            RETURN a.id AS source, type(r) AS type, b.id AS target
            """,
            repo=repo, file_path=file_path,
        )

        NODE_COLORS = {
            "File": "#9cdef2", "Commit": "#64748b", "PullRequest": "#22c55e",
            "Issue": "#f59e0b", "Developer": "#a855f7",
        }
        nodes = []
        for row in nodes_raw:
            n = dict(row["n"])
            n["color"] = NODE_COLORS.get(n.get("type", ""), "#64748b")
            nodes.append(n)

        edges = [{"source": r["source"], "target": r["target"], "type": r["type"]} for r in edges_raw]
        return {"nodes": nodes, "edges": edges, "cached": True}

    async def store_provenance_graph(
        self, repo: str, file_path: str, nodes: list[dict], edges: list[dict]
    ) -> bool:
        if self.driver is None and not await asyncio.to_thread(self._ensure_driver):
            return False
        try:
            return await asyncio.to_thread(
                self._sync_store_provenance_graph, repo, file_path, nodes, edges
            )
        except Exception as exc:
            print(f"[Neo4jStore] store_provenance_graph error: {exc}")
            return False

    async def get_provenance_graph(self, repo: str, file_path: str) -> dict:
        if self.driver is None and not await asyncio.to_thread(self._ensure_driver):
            return {"nodes": [], "edges": [], "cached": False}
        try:
            return await asyncio.to_thread(self._sync_get_provenance_graph, repo, file_path)
        except Exception as exc:
            print(f"[Neo4jStore] get_provenance_graph error: {exc}")
            return {"nodes": [], "edges": [], "cached": False}

    def __del__(self):
        if self.driver:
            try:
                self.driver.close()
            except Exception:
                pass
