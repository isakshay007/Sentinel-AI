"""
SentinelAI — ChromaDB Past Incident Store
Stores and retrieves past incidents using vector embeddings
for similar-incident retrieval during diagnosis.

Usage:
  python -m rag.chroma_store --seed     # Seed with synthetic past incidents
  python -m rag.chroma_store --query "memory usage climbing steadily"
"""

import json
import uuid
import chromadb
from pathlib import Path
from typing import List, Dict, Optional

# =============================================================================
# SYNTHETIC PAST INCIDENTS — Seeds the knowledge base
# =============================================================================

PAST_INCIDENTS = [
    {
        "id": "hist-001",
        "title": "Memory leak in user-service connection pool",
        "service": "user-service",
        "type": "memory_leak",
        "severity": "critical",
        "symptoms": "Memory usage climbing steadily from 45% to 98% over 40 minutes. GC pauses increasing. Response times degrading. OOM kills in logs.",
        "root_cause": "Database connections were not being released after timeout in the session handler. Each timed-out request leaked one connection object (~2MB). Under normal load of 200 req/s, this accumulated ~400MB/hour.",
        "resolution": "Restart service to clear leaked connections. Deploy hotfix to add connection.close() in the finally block of SessionHandler.process(). Add connection pool max-age of 300s.",
        "time_to_resolve_minutes": 45,
        "prevention": "Add connection pool monitoring. Set memory alerts at 75%. Add max-age to connection pool config.",
    },
    {
        "id": "hist-002",
        "title": "Memory leak from unclosed HTTP client responses",
        "service": "api-gateway",
        "type": "memory_leak",
        "severity": "high",
        "symptoms": "Gradual memory increase over 2 hours. No sudden spike. GC unable to reclaim memory. Heap dumps show large number of HttpResponse objects.",
        "root_cause": "HTTP client responses from upstream calls were not being closed after reading. The response body stream held references to large byte buffers.",
        "resolution": "Added try-with-resources pattern to all upstream HTTP calls. Deployed fix and restarted service.",
        "time_to_resolve_minutes": 60,
        "prevention": "Static analysis rule to detect unclosed HTTP responses. Code review checklist item.",
    },
    {
        "id": "hist-003",
        "title": "Bad deployment caused payment processing failures",
        "service": "payment-service",
        "type": "bad_deployment",
        "severity": "critical",
        "symptoms": "Error rate jumped from 0.1% to 35% exactly 4 minutes after deployment v3.8.13. Response times increased from 200ms to 5000ms+. Throughput dropped 40%.",
        "root_cause": "Async database driver migration in v3.8.13 was incompatible with the existing connection pool configuration. The pool was configured for sync connections with max-wait of 5s, but async driver used different timeout semantics.",
        "resolution": "Rolled back to v3.8.12. Updated connection pool config to support async driver. Redeployed with fix in v3.8.14.",
        "time_to_resolve_minutes": 25,
        "prevention": "Canary deployments with automatic rollback on error rate threshold. Pre-deployment integration tests with actual database.",
    },
    {
        "id": "hist-004",
        "title": "Deployment broke database schema compatibility",
        "service": "inventory-service",
        "type": "bad_deployment",
        "severity": "high",
        "symptoms": "500 errors on all inventory queries after deploy. Logs show 'column not found: reserved_count'. No gradual degradation — immediate failure.",
        "root_cause": "Migration in v1.9.22 renamed column 'reserved' to 'reserved_count' but the ORM model still referenced the old column name. Migration ran successfully but application code was incompatible.",
        "resolution": "Rolled back deployment. Fixed ORM model to use new column name. Added migration test that validates ORM compatibility.",
        "time_to_resolve_minutes": 15,
        "prevention": "Run ORM validation against migrated schema in CI pipeline before deployment.",
    },
    {
        "id": "hist-005",
        "title": "Redis cache failure caused cascading timeouts",
        "service": "api-gateway",
        "type": "api_timeout",
        "severity": "critical",
        "symptoms": "Response times jumped from 150ms to 25s+. Error rate reached 25%. Multiple services affected: api-gateway, user-service, inventory-service. CPU normal, memory normal.",
        "root_cause": "Redis cache server experienced a network partition. All cache-dependent services fell back to direct database queries, overwhelming the database and causing connection pool exhaustion.",
        "resolution": "Restored Redis network connectivity. Restarted affected services to clear stale connections. Added circuit breaker for cache calls with fallback to stale cache data.",
        "time_to_resolve_minutes": 35,
        "prevention": "Redis sentinel for automatic failover. Circuit breaker pattern with graceful degradation. Cache-aside pattern with TTL-based staleness tolerance.",
    },
    {
        "id": "hist-006",
        "title": "Upstream API timeout from third-party payment provider",
        "service": "payment-service",
        "type": "api_timeout",
        "severity": "high",
        "symptoms": "Payment processing timeouts. 30s+ response times on payment endpoints only. Other endpoints unaffected. Error logs show 'TimeoutError: stripe-client did not respond within 30s'.",
        "root_cause": "Third-party payment provider (Stripe) experienced degraded performance due to their own infrastructure issue. Our timeout was set to 30s which caused thread pool exhaustion.",
        "resolution": "Reduced timeout to 5s with retry. Enabled circuit breaker for Stripe calls. Queued failed payments for retry.",
        "time_to_resolve_minutes": 50,
        "prevention": "Reduce external API timeouts. Implement bulkhead pattern to isolate external call thread pools. Add payment queue for async processing.",
    },
    {
        "id": "hist-007",
        "title": "CPU spike from infinite loop in request parser",
        "service": "api-gateway",
        "type": "cpu_spike",
        "severity": "high",
        "symptoms": "CPU at 100% on all cores. Response times extremely high. Memory stable. Triggered by specific malformed request pattern.",
        "root_cause": "Regex in request parser had catastrophic backtracking on certain input patterns. A single malformed request could pin one CPU core indefinitely.",
        "resolution": "Identified the problematic regex. Deployed fix with non-backtracking regex pattern. Added request timeout at the parser level.",
        "time_to_resolve_minutes": 30,
        "prevention": "Regex complexity analysis in CI. Request parser timeout. Rate limiting per IP.",
    },
    {
        "id": "hist-008",
        "title": "Disk space exhaustion from log rotation failure",
        "service": "user-service",
        "type": "disk_full",
        "severity": "medium",
        "symptoms": "Service started returning 500 errors. Disk usage at 100%. Application logs stopped writing. Database write operations failed with 'no space left on device'.",
        "root_cause": "Log rotation cron job had been silently failing for 2 weeks. Debug logging was accidentally left enabled, generating 50GB of logs per day.",
        "resolution": "Manually cleared old logs. Fixed log rotation cron. Disabled debug logging in production.",
        "time_to_resolve_minutes": 20,
        "prevention": "Disk usage alerting at 80%. Log rotation monitoring. Enforce log level configuration per environment.",
    },
    {
        "id": "hist-009",
        "title": "SSL certificate expiry caused connection failures",
        "service": "api-gateway",
        "type": "ssl_expiry",
        "severity": "critical",
        "symptoms": "All HTTPS connections failing. Clients receiving SSL handshake errors. Internal service-to-service calls also failing where mTLS was enabled.",
        "root_cause": "SSL certificate expired. Auto-renewal had been disabled during a infrastructure migration 3 months prior and was never re-enabled.",
        "resolution": "Issued emergency certificate via Let's Encrypt. Re-enabled auto-renewal. Restarted all affected services.",
        "time_to_resolve_minutes": 15,
        "prevention": "Certificate expiry monitoring with 30-day advance alerting. Automated renewal with verification.",
    },
    {
        "id": "hist-010",
        "title": "Connection pool exhaustion under load spike",
        "service": "user-service",
        "type": "connection_pool",
        "severity": "high",
        "symptoms": "Intermittent 503 errors during peak traffic. Logs show 'ConnectionPoolExhausted: all 50 connections in use, 200 waiting'. Response times variable — either fast or 30s timeout.",
        "root_cause": "Marketing campaign drove 3x normal traffic. Connection pool was sized for normal load (50 connections). Slow queries during peak held connections longer, causing cascading pool exhaustion.",
        "resolution": "Increased connection pool to 150. Optimized the two slowest queries. Added connection pool queue timeout of 5s instead of 30s.",
        "time_to_resolve_minutes": 40,
        "prevention": "Auto-scaling connection pool based on load. Query performance monitoring with alerting on p99 degradation. Load testing before campaigns.",
    },
    {
        "id": "hist-011",
        "title": "Memory leak from event listener accumulation",
        "service": "inventory-service",
        "type": "memory_leak",
        "severity": "medium",
        "symptoms": "Memory growing slowly over days. Not visible in hourly monitoring. Weekly restart masked the issue. GC logs show increasing old-gen heap usage.",
        "root_cause": "Event listeners were being registered on each request but never unregistered. Over 7 days, millions of listener objects accumulated in the old generation heap.",
        "resolution": "Fixed listener lifecycle to unregister on request completion. Added WeakReference for event listeners as defense in depth.",
        "time_to_resolve_minutes": 120,
        "prevention": "Memory trend monitoring over 7-day windows. Heap dump analysis as part of weekly ops review.",
    },
    {
        "id": "hist-012",
        "title": "Database replica lag caused stale reads",
        "service": "payment-service",
        "type": "data_consistency",
        "severity": "high",
        "symptoms": "Users seeing inconsistent data. Payment status showing as 'pending' after successful completion. No errors in application logs. Metrics look normal.",
        "root_cause": "Read replica fell 45 seconds behind primary due to a long-running analytics query holding a lock. Application was reading from replica for payment status checks.",
        "resolution": "Killed the blocking analytics query. Configured critical payment reads to use primary. Added replica lag monitoring.",
        "time_to_resolve_minutes": 30,
        "prevention": "Route critical reads to primary. Replica lag alerting at 5s threshold. Separate analytics database.",
    },
    {
        "id": "hist-013",
        "title": "Rate limiting misconfiguration blocked legitimate traffic",
        "service": "api-gateway",
        "type": "misconfiguration",
        "severity": "medium",
        "symptoms": "Sudden drop in successful requests. 429 Too Many Requests errors for legitimate users. Traffic volume normal but success rate dropped to 60%.",
        "root_cause": "Rate limit configuration was updated to use per-IP limits but the load balancer was forwarding all requests with the same internal IP, making all traffic appear to come from one source.",
        "resolution": "Updated rate limiter to use X-Forwarded-For header. Reverted to previous rate limit config as interim fix.",
        "time_to_resolve_minutes": 20,
        "prevention": "Rate limit config changes require load test validation. Monitor 429 rate as percentage of total requests.",
    },
    {
        "id": "hist-014",
        "title": "Cascading failure from circuit breaker misconfiguration",
        "service": "api-gateway",
        "type": "cascading_failure",
        "severity": "critical",
        "symptoms": "All downstream services returning errors. Circuit breakers tripping for every service. Even healthy services being blocked. Complete system outage.",
        "root_cause": "Shared circuit breaker state across all downstream services. When payment-service failed, the shared failure count exceeded the threshold and opened circuits for all services.",
        "resolution": "Deployed emergency fix with per-service circuit breakers. Restarted api-gateway to clear shared state.",
        "time_to_resolve_minutes": 20,
        "prevention": "Per-service circuit breaker isolation. Circuit breaker configuration review. Chaos engineering testing of circuit breaker behavior.",
    },
    {
        "id": "hist-015",
        "title": "Memory pressure from large response payload caching",
        "service": "api-gateway",
        "type": "memory_leak",
        "severity": "high",
        "symptoms": "Memory usage growing during business hours, stable at night. GC frequency increasing. Response cache hit rate very high but memory climbing.",
        "root_cause": "Response cache had no size limit. Large product catalog responses (5MB each) were being cached. During business hours, cache grew to consume 80% of heap.",
        "resolution": "Added LRU eviction policy with 500MB max cache size. Configured TTL of 5 minutes for large responses.",
        "time_to_resolve_minutes": 35,
        "prevention": "Cache size limits on all caching layers. Memory budget per cache. Monitor cache size alongside memory usage.",
    },
]


# =============================================================================
# CHROMA STORE
# =============================================================================

class IncidentKnowledgeBase:
    """
    ChromaDB-backed knowledge base for similar incident retrieval.
    Uses sentence-transformers embeddings for semantic search.
    """

    def __init__(self, persist_dir: str = None):
        if persist_dir:
            self.client = chromadb.PersistentClient(path=persist_dir)
        else:
            self.client = chromadb.PersistentClient(
                path=str(Path(__file__).parent.parent / "data" / "chromadb")
            )

        self.collection = self.client.get_or_create_collection(
            name="past_incidents",
            metadata={"hnsw:space": "cosine"},
        )

    def seed(self, incidents: List[Dict] = None):
        """Seed the knowledge base with past incidents."""
        incidents = incidents or PAST_INCIDENTS

        # Check if already seeded
        existing = self.collection.count()
        if existing >= len(incidents):
            print(f"  Knowledge base already has {existing} incidents. Skipping seed.")
            return

        ids = []
        documents = []
        metadatas = []

        for inc in incidents:
            # Create a rich text document for embedding
            doc = (
                f"Incident: {inc['title']}\n"
                f"Service: {inc['service']}\n"
                f"Type: {inc['type']}\n"
                f"Severity: {inc['severity']}\n"
                f"Symptoms: {inc['symptoms']}\n"
                f"Root Cause: {inc['root_cause']}\n"
                f"Resolution: {inc['resolution']}\n"
                f"Prevention: {inc['prevention']}"
            )

            ids.append(inc["id"])
            documents.append(doc)
            metadatas.append({
                "title": inc["title"],
                "service": inc["service"],
                "type": inc["type"],
                "severity": inc["severity"],
                "time_to_resolve": inc["time_to_resolve_minutes"],
            })

        self.collection.upsert(
            ids=ids,
            documents=documents,
            metadatas=metadatas,
        )
        print(f"  Seeded {len(incidents)} past incidents into ChromaDB")

    def query(self, symptoms: str, n_results: int = 3,
              service_filter: str = None,
              type_filter: str = None) -> List[Dict]:
        """
        Find similar past incidents based on symptom description.

        Args:
            symptoms: Description of current symptoms
            n_results: Number of similar incidents to return
            service_filter: Optional filter by service name
            type_filter: Optional filter by incident type

        Returns:
            List of similar incidents with similarity scores
        """
        where_filter = None
        if service_filter and type_filter:
            where_filter = {
                "$and": [
                    {"service": service_filter},
                    {"type": type_filter},
                ]
            }
        elif service_filter:
            where_filter = {"service": service_filter}
        elif type_filter:
            where_filter = {"type": type_filter}

        try:
            results = self.collection.query(
                query_texts=[symptoms],
                n_results=n_results,
                where=where_filter,
                include=["documents", "metadatas", "distances"],
            )
        except Exception:
            # If filter returns no results, try without filter
            results = self.collection.query(
                query_texts=[symptoms],
                n_results=n_results,
                include=["documents", "metadatas", "distances"],
            )

        similar_incidents = []
        if results and results["ids"] and results["ids"][0]:
            for i, doc_id in enumerate(results["ids"][0]):
                distance = results["distances"][0][i] if results["distances"] else None
                similarity = round(1 - distance, 4) if distance is not None else None

                similar_incidents.append({
                    "id": doc_id,
                    "similarity": similarity,
                    "metadata": results["metadatas"][0][i] if results["metadatas"] else {},
                    "document": results["documents"][0][i] if results["documents"] else "",
                })

        return similar_incidents

    def get_incident(self, incident_id: str) -> Optional[Dict]:
        """Retrieve a specific incident by ID."""
        try:
            result = self.collection.get(
                ids=[incident_id],
                include=["documents", "metadatas"],
            )
            if result and result["ids"]:
                return {
                    "id": result["ids"][0],
                    "metadata": result["metadatas"][0] if result["metadatas"] else {},
                    "document": result["documents"][0] if result["documents"] else "",
                }
        except Exception:
            pass
        return None

    def count(self) -> int:
        return self.collection.count()


# =============================================================================
# CLI
# =============================================================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="SentinelAI Incident Knowledge Base")
    parser.add_argument("--seed", action="store_true", help="Seed with past incidents")
    parser.add_argument("--query", type=str, help="Search for similar incidents")
    parser.add_argument("--service", type=str, help="Filter by service")
    parser.add_argument("--type", type=str, help="Filter by incident type")
    parser.add_argument("--count", action="store_true", help="Show total incidents")
    args = parser.parse_args()

    kb = IncidentKnowledgeBase()

    if args.seed:
        print("\n  Seeding incident knowledge base...")
        kb.seed()
        print(f"  Total incidents: {kb.count()}")

    elif args.query:
        print(f"\n  Searching: \"{args.query}\"")
        if args.service:
            print(f"  Filter: service={args.service}")
        if args.type:
            print(f"  Filter: type={args.type}")

        results = kb.query(args.query, n_results=3,
                          service_filter=args.service,
                          type_filter=args.type)

        print(f"\n  Found {len(results)} similar incidents:\n")
        for i, r in enumerate(results, 1):
            meta = r["metadata"]
            print(f"  {i}. [{meta.get('severity', '?').upper()}] {meta.get('title', '?')}")
            print(f"     Service: {meta.get('service', '?')} | Type: {meta.get('type', '?')}")
            print(f"     Similarity: {r['similarity']:.2%}")
            print(f"     Resolved in: {meta.get('time_to_resolve', '?')} minutes")
            print()

    elif args.count:
        print(f"\n  Total incidents in knowledge base: {kb.count()}")

    else:
        parser.print_help()
        print("\n\n  Quick start:")
        print("    python -m rag.chroma_store --seed")
        print("    python -m rag.chroma_store --query 'memory usage climbing'")
        print("    python -m rag.chroma_store --query 'errors after deployment' --type bad_deployment")