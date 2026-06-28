"""
Shared singleton instances for all services and memory stores.
Import from here instead of instantiating inside each module — avoids
creating duplicate connections on every request.
"""
from services.github_service import GitHubService
from services.jenkins_service import JenkinsService
from services.n8n_service import N8nService
from services.odysseus_service import OdysseusService
from memory.chroma_store import ChromaStore
from memory.neo4j_store import Neo4jStore

github = GitHubService()
jenkins = JenkinsService()
n8n = N8nService()
odysseus = OdysseusService()
chroma = ChromaStore()
neo4j = Neo4jStore()
