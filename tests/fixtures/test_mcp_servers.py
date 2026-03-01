"""
SentinelAI — MCP Server Integration Tests
Tests all 4 MCP servers by connecting as a client, listing tools,
and calling each tool with realistic parameters.

Run:
  python -m tests.test_mcp_servers

Prerequisites:
  - Mock data fixtures generated: python -m backend.mock_data_generator --seed-all
"""

import asyncio
import json
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

# Server configurations
SERVERS = {
    "LogsMCP": {
        "command": sys.executable,
        "args": ["-m", "mcp_servers.logs_server"],
        "test_calls": [
            {
                "tool": "search_logs",
                "args": {"query": "error", "severity": "ERROR", "minutes_ago": 120},
                "description": "Search for ERROR logs"
            },
            {
                "tool": "get_recent_errors",
                "args": {"minutes": 60, "include_warnings": True},
                "description": "Get recent errors and warnings"
            },
        ],
    },
    "MetricsMCP": {
        "command": sys.executable,
        "args": ["-m", "mcp_servers.metrics_server"],
        "test_calls": [
            {
                "tool": "get_current_metrics",
                "args": {"service": "user-service"},
                "description": "Get current user-service metrics"
            },
            {
                "tool": "get_metric_history",
                "args": {"service": "user-service", "metric": "memory_percent", "minutes": 120},
                "description": "Get memory history for user-service"
            },
            {
                "tool": "detect_anomaly",
                "args": {"service": "user-service", "metric": "memory_percent", "method": "threshold"},
                "description": "Check memory anomaly on user-service"
            },
        ],
    },
    "InfraMCP": {
        "command": sys.executable,
        "args": ["-m", "mcp_servers.infra_server"],
        "test_calls": [
            {
                "tool": "get_deployment_history",
                "args": {"service": "payment-service", "limit": 5},
                "description": "Get payment-service deploy history"
            },
            {
                "tool": "scale_service",
                "args": {"service": "api-gateway", "replicas": 4, "reason": "integration test"},
                "description": "Scale api-gateway to 4 replicas"
            },
            {
                "tool": "restart_service",
                "args": {"service": "user-service", "reason": "integration test"},
                "description": "Restart user-service"
            },
        ],
    },
    "AlertMCP": {
        "command": sys.executable,
        "args": ["-m", "mcp_servers.alert_server"],
        "test_calls": [
            {
                "tool": "get_on_call_engineer",
                "args": {},
                "description": "Get current on-call info"
            },
            {
                "tool": "send_notification",
                "args": {
                    "channel": "slack",
                    "message": "Integration test: memory leak detected in user-service",
                    "severity": "high",
                    "service": "user-service",
                },
                "description": "Send Slack notification"
            },
            {
                "tool": "create_incident_ticket",
                "args": {
                    "title": "Memory leak in user-service",
                    "description": "Memory usage climbing steadily. Currently at 95%.",
                    "priority": "P1",
                    "service": "user-service",
                },
                "description": "Create P1 incident ticket"
            },
        ],
    },
}


async def test_server(name: str, config: dict) -> dict:
    """Test a single MCP server by connecting, listing tools, and calling them."""
    print(f"\n{'='*60}")
    print(f"  Testing: {name}")
    print(f"{'='*60}")

    results = {
        "server": name,
        "status": "unknown",
        "tools_discovered": [],
        "test_results": [],
        "errors": [],
    }

    server_params = StdioServerParameters(
        command=config["command"],
        args=config["args"],
    )

    try:
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                # Initialize
                await session.initialize()
                print(f"  ✓ Connected to {name}")

                # List tools
                tools_response = await session.list_tools()
                tools = tools_response.tools
                results["tools_discovered"] = [
                    {"name": t.name, "description": t.description[:80]}
                    for t in tools
                ]
                print(f"  ✓ Discovered {len(tools)} tools:")
                for t in tools:
                    print(f"      • {t.name}: {t.description[:60]}...")

                # Call each test tool
                for test in config["test_calls"]:
                    tool_name = test["tool"]
                    tool_args = test["args"]
                    desc = test["description"]

                    try:
                        result = await session.call_tool(tool_name, tool_args)

                        # Parse the response
                        response_text = ""
                        for content in result.content:
                            if hasattr(content, "text"):
                                response_text = content.text

                        response_data = json.loads(response_text)
                        has_error = "error" in response_data

                        status = "FAIL" if has_error else "PASS"
                        icon = "✗" if has_error else "✓"

                        print(f"  {icon} {desc}: {status}")

                        if has_error:
                            print(f"      Error: {response_data['error']}")

                        results["test_results"].append({
                            "tool": tool_name,
                            "description": desc,
                            "status": status,
                            "response_preview": str(response_data)[:200],
                        })

                    except Exception as e:
                        print(f"  ✗ {desc}: EXCEPTION — {e}")
                        results["test_results"].append({
                            "tool": tool_name,
                            "description": desc,
                            "status": "EXCEPTION",
                            "error": str(e),
                        })
                        results["errors"].append(str(e))

        results["status"] = "passed" if not results["errors"] else "failed"

    except Exception as e:
        print(f"  ✗ Failed to connect: {e}")
        results["status"] = "connection_failed"
        results["errors"].append(str(e))

    return results


async def run_all_tests():
    """Test all MCP servers sequentially."""
    print("\n╔══════════════════════════════════════════════╗")
    print("║   SentinelAI — MCP Server Integration Tests  ║")
    print("╚══════════════════════════════════════════════╝")

    all_results = []
    total_tools = 0
    total_tests = 0
    total_passed = 0

    for name, config in SERVERS.items():
        result = await test_server(name, config)
        all_results.append(result)
        total_tools += len(result["tools_discovered"])
        for tr in result["test_results"]:
            total_tests += 1
            if tr["status"] == "PASS":
                total_passed += 1

    # Summary
    print(f"\n{'='*60}")
    print(f"  SUMMARY")
    print(f"{'='*60}")
    print(f"  Servers tested:  {len(all_results)}")
    print(f"  Tools discovered: {total_tools}")
    print(f"  Tests run:       {total_tests}")
    print(f"  Tests passed:    {total_passed}/{total_tests}")

    for r in all_results:
        icon = "✓" if r["status"] == "passed" else "✗"
        tools = len(r["tools_discovered"])
        print(f"  {icon} {r['server']}: {tools} tools — {r['status']}")

    # Save results
    output_path = Path("tests/results/mcp_integration_test.json")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(all_results, f, indent=2)
    print(f"\n  Results saved to {output_path}")

    if total_passed == total_tests:
        print(f"\n  🎉 All tests passed!")
    else:
        print(f"\n  ⚠️  {total_tests - total_passed} test(s) failed")

    return all_results


if __name__ == "__main__":
    asyncio.run(run_all_tests())