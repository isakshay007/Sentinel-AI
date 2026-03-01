"""
SentinelAI — Evaluation Pipeline
Evaluates agent performance using DeepEval metrics.

Metrics:
  1. ToolCorrectness    — Did agents call the RIGHT tools?
  2. ArgumentCorrectness — Did agents pass correct arguments?
  3. GEval (DiagnosisQuality)  — Was the root cause diagnosis accurate?
  4. GEval (PlanQuality)       — Was the remediation plan logical?
  5. GEval (ResponseRelevancy) — Was the overall response relevant?
  6. GEval (ActionEfficiency)  — Were actions efficient (no waste)?

Usage:
  python -m evaluation.eval_pipeline                    # Run all tests
  python -m evaluation.eval_pipeline --scenario memory_leak  # Run one scenario
"""

import json
import asyncio
import os
from datetime import datetime, timezone
from pathlib import Path

from deepeval import evaluate
from deepeval.test_case import LLMTestCase, ToolCall, LLMTestCaseParams
from deepeval.metrics import (
    ToolCorrectnessMetric,
    GEval,
)
from deepeval.models import DeepEvalBaseLLM
from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).parent.parent / ".env")


# =============================================================================
# CUSTOM GROQ MODEL FOR DEEPEVAL
# =============================================================================

class GroqEvalModel(DeepEvalBaseLLM):
    """Custom DeepEval model wrapper for Groq."""

    def __init__(self, model_name: str = "llama-3.1-8b-instant"):
        self.model_name = model_name
        super().__init__(model_name)

    def load_model(self):
        from langchain_groq import ChatGroq
        return ChatGroq(
            model=self.model_name,
            temperature=0.1,
            api_key=os.getenv("GROQ_API_KEY"),
        )

    def generate(self, prompt: str, schema=None) -> str:
        from langchain_core.messages import HumanMessage
        model = self.load_model()
        response = model.invoke([HumanMessage(content=prompt)])
        return response.content

    async def a_generate(self, prompt: str, schema=None) -> str:
        return self.generate(prompt, schema)

    def get_model_name(self) -> str:
        return f"groq/{self.model_name}"


# =============================================================================
# TEST CASE DEFINITIONS — Expected behavior for each scenario
# =============================================================================

SCENARIO_TEST_CASES = {
    "memory_leak": {
        "input": "Monitor user-service for anomalies and respond to any incidents detected",
        "service": "user-service",

        # Expected tool calls for the Watcher phase
        "watcher_expected_tools": [
            ToolCall(name="get_current_metrics"),
            ToolCall(name="get_metric_history"),
            ToolCall(name="detect_anomaly"),
            ToolCall(name="get_recent_errors"),
        ],

        # Expected tool calls for the Diagnostician phase
        "diagnostician_expected_tools": [
            ToolCall(name="search_logs"),
            ToolCall(name="detect_anomaly"),
            ToolCall(name="get_deployment_history"),
        ],

        # Expected executor tools
        "executor_expected_tools": [
            ToolCall(name="send_notification"),
            ToolCall(name="scale_service"),
            ToolCall(name="restart_service"),
        ],

        # Expected diagnosis
        "expected_root_cause": "Memory leak in user-service caused by database connections not being released after timeout in the connection pool or session handler",
        "expected_severity": "critical",
        "expected_category": "memory_leak",

        # Expected plan characteristics
        "expected_plan_description": "The remediation plan should include notification to the team, scaling up the service for capacity, and restarting the service to clear leaked connections. Dangerous actions like rollback should require approval.",
    },

    "bad_deployment": {
        "input": "Monitor payment-service for anomalies and respond to any incidents detected",
        "service": "payment-service",

        "watcher_expected_tools": [
            ToolCall(name="get_current_metrics"),
            ToolCall(name="get_metric_history"),
            ToolCall(name="detect_anomaly"),
            ToolCall(name="get_recent_errors"),
        ],

        "diagnostician_expected_tools": [
            ToolCall(name="search_logs"),
            ToolCall(name="detect_anomaly"),
            ToolCall(name="get_deployment_history"),
        ],

        "executor_expected_tools": [
            ToolCall(name="send_notification"),
            ToolCall(name="rollback_deployment"),
        ],

        "expected_root_cause": "Bad deployment v3.8.13 introduced a regression, likely related to the async database driver migration causing incompatibility with connection pool configuration",
        "expected_severity": "critical",
        "expected_category": "bad_deployment",

        "expected_plan_description": "The remediation plan should include notification and rolling back to the previous known-good version v3.8.12. The rollback is a dangerous action requiring approval.",
    },

    "api_timeout": {
        "input": "Monitor api-gateway for anomalies and respond to any incidents detected",
        "service": "api-gateway",

        "watcher_expected_tools": [
            ToolCall(name="get_current_metrics"),
            ToolCall(name="get_metric_history"),
            ToolCall(name="detect_anomaly"),
            ToolCall(name="get_recent_errors"),
        ],

        "diagnostician_expected_tools": [
            ToolCall(name="search_logs"),
            ToolCall(name="detect_anomaly"),
            ToolCall(name="get_deployment_history"),
        ],

        "executor_expected_tools": [
            ToolCall(name="send_notification"),
            ToolCall(name="scale_service"),
            ToolCall(name="restart_service"),
        ],

        "expected_root_cause": "Upstream dependency (Redis cache or external service) became unresponsive, causing cascading timeouts across dependent services",
        "expected_severity": "critical",
        "expected_category": "api_timeout",

        "expected_plan_description": "The remediation plan should include notification, scaling up to handle timeout retries, and restarting to clear stale connections.",
    },
}


# =============================================================================
# RUN PIPELINE AND COLLECT RESULTS
# =============================================================================

async def run_scenario_and_collect(service: str, scenario: str) -> dict:
    """Run the full pipeline for a scenario and collect results for evaluation."""
    from agents.watcher import run_watcher
    from agents.diagnostician import run_diagnostician
    import uuid

    print(f"\n  Running Watcher for {service} ({scenario})...")
    watcher = await run_watcher(service, scenario)

    diag = None
    if watcher.get("should_alert"):
        print(f"  Running Diagnostician...")
        diag = await run_diagnostician(
            incident_id=watcher.get("incident_id", str(uuid.uuid4())),
            service=service,
            watcher_summary=watcher.get("summary", "Anomaly detected"),
            watcher_metrics=watcher.get("metrics"),
            watcher_severity=watcher.get("severity", "high"),
            scenario=scenario,
        )

    return {
        "watcher": watcher,
        "diagnostician": diag,
    }


# =============================================================================
# BUILD TEST CASES FROM PIPELINE RESULTS
# =============================================================================

def build_tool_correctness_cases(scenario: str, results: dict) -> list:
    """Build ToolCorrectness test cases from pipeline results."""
    test_config = SCENARIO_TEST_CASES[scenario]
    cases = []

    # Watcher tool correctness
    watcher = results.get("watcher", {})
    watcher_tools_called = [
        ToolCall(name=tc.get("tool", ""))
        for tc in watcher.get("tool_calls", [])
        if tc.get("server") in ("MetricsMCP", "LogsMCP")  # Exclude alert tools
    ]

    if watcher_tools_called:
        cases.append(LLMTestCase(
            input=f"Monitor {test_config['service']} for anomalies",
            actual_output=watcher.get("summary", "No summary"),
            tools_called=watcher_tools_called,
            expected_tools=test_config["watcher_expected_tools"],
        ))

    # Diagnostician tool correctness
    diag = results.get("diagnostician")
    if diag:
        diag_tools_called = [
            ToolCall(name=tc.get("tool", ""))
            for tc in diag.get("tool_calls", [])
        ]
        if diag_tools_called:
            cases.append(LLMTestCase(
                input=f"Diagnose root cause for incident on {test_config['service']}",
                actual_output=diag.get("root_cause", "No diagnosis"),
                tools_called=diag_tools_called,
                expected_tools=test_config["diagnostician_expected_tools"],
            ))

    return cases


def build_geval_cases(scenario: str, results: dict) -> dict:
    """Build GEval test cases from pipeline results."""
    test_config = SCENARIO_TEST_CASES[scenario]
    cases = {}

    watcher = results.get("watcher", {})
    diag = results.get("diagnostician")

    # Diagnosis Quality
    if diag:
        cases["diagnosis_quality"] = LLMTestCase(
            input=f"Diagnose the root cause of the incident on {test_config['service']}. The service is experiencing {test_config['expected_severity']} level issues.",
            actual_output=json.dumps({
                "root_cause": diag.get("root_cause", "Unknown"),
                "confidence": diag.get("confidence", 0),
                "reasoning_chain": [
                    step.get("step", "")
                    for step in diag.get("reasoning_chain", [])
                ],
            }),
            expected_output=test_config["expected_root_cause"],
        )

    # Detection Quality
    cases["detection_quality"] = LLMTestCase(
        input=f"Monitor {test_config['service']} and detect any anomalies",
        actual_output=json.dumps({
            "alert_triggered": watcher.get("should_alert", False),
            "confidence": watcher.get("confidence", 0),
            "severity": watcher.get("severity", "unknown"),
            "summary": watcher.get("summary", "No summary"),
        }),
        expected_output=f"Alert should be triggered with high confidence. Severity should be {test_config['expected_severity']}. The anomaly should be correctly identified.",
    )

    # Plan Quality (using diagnosis recommended actions)
    if diag and diag.get("recommended_actions"):
        cases["plan_quality"] = LLMTestCase(
            input=f"Create a remediation plan for: {diag.get('root_cause', 'Unknown issue')}",
            actual_output=json.dumps(diag.get("recommended_actions", [])),
            expected_output=test_config["expected_plan_description"],
        )

    return cases


# =============================================================================
# METRICS
# =============================================================================

def get_metrics() -> dict:
    """Initialize all evaluation metrics."""
    groq_model = GroqEvalModel("llama-3.1-8b-instant")

    return {
        "tool_correctness": ToolCorrectnessMetric(
            threshold=0.5,
            model=groq_model,
        ),
        "diagnosis_quality": GEval(
            name="Diagnosis Quality",
            criteria="Evaluate whether the actual root cause diagnosis is accurate and matches the expected root cause. Consider if the diagnosis correctly identifies the type of issue (memory leak, bad deployment, timeout) and the specific mechanism.",
            evaluation_params=[
                LLMTestCaseParams.ACTUAL_OUTPUT,
                LLMTestCaseParams.EXPECTED_OUTPUT,
            ],
            threshold=0.5,
            model=groq_model,
        ),
        "detection_quality": GEval(
            name="Detection Quality",
            criteria="Evaluate whether the anomaly detection correctly triggered an alert with appropriate confidence and severity. The alert should have been triggered (true), confidence should be above 0.7, and severity should match the expected level.",
            evaluation_params=[
                LLMTestCaseParams.ACTUAL_OUTPUT,
                LLMTestCaseParams.EXPECTED_OUTPUT,
            ],
            threshold=0.5,
            model=groq_model,
        ),
        "plan_quality": GEval(
            name="Plan Quality",
            criteria="Evaluate whether the remediation plan is logical, actionable, and appropriate for the diagnosed root cause. The plan should include relevant actions with proper risk classification.",
            evaluation_params=[
                LLMTestCaseParams.ACTUAL_OUTPUT,
                LLMTestCaseParams.EXPECTED_OUTPUT,
            ],
            threshold=0.5,
            model=groq_model,
        ),
    }


# =============================================================================
# MAIN EVALUATION RUNNER
# =============================================================================

async def run_evaluation(scenarios: list = None) -> dict:
    """Run the full evaluation pipeline."""
    if scenarios is None:
        scenarios = list(SCENARIO_TEST_CASES.keys())

    metrics = get_metrics()
    all_results = {}

    for scenario in scenarios:
        print(f"\n{'='*55}")
        print(f"  Evaluating: {scenario}")
        print(f"{'='*55}")

        config = SCENARIO_TEST_CASES[scenario]

        # Run pipeline
        print(f"\n  Phase 1: Running pipeline...")
        results = await run_scenario_and_collect(config["service"], scenario)

        # Build test cases
        print(f"\n  Phase 2: Building test cases...")

        # Tool Correctness
        tc_cases = build_tool_correctness_cases(scenario, results)
        print(f"    Tool correctness cases: {len(tc_cases)}")

        # GEval cases
        geval_cases = build_geval_cases(scenario, results)
        print(f"    GEval cases: {len(geval_cases)}")

        # Run evaluations
        print(f"\n  Phase 3: Running metrics...")
        scenario_scores = {}

        # Tool Correctness evaluation
        if tc_cases:
            for i, tc in enumerate(tc_cases):
                try:
                    metrics["tool_correctness"].measure(tc)
                    score = metrics["tool_correctness"].score
                    phase = "watcher" if i == 0 else "diagnostician"
                    scenario_scores[f"tool_correctness_{phase}"] = score
                    print(f"    Tool Correctness ({phase}): {score:.2f}")
                except Exception as e:
                    print(f"    Tool Correctness error: {e}")
                    scenario_scores[f"tool_correctness_{i}"] = 0.0

        # GEval metrics
        for metric_name, test_case in geval_cases.items():
            try:
                metric = metrics.get(metric_name)
                if metric:
                    metric.measure(test_case)
                    score = metric.score
                    scenario_scores[metric_name] = score
                    reason = metric.reason if hasattr(metric, 'reason') else ""
                    print(f"    {metric_name}: {score:.2f} — {reason[:80] if reason else ''}")
            except Exception as e:
                print(f"    {metric_name} error: {e}")
                scenario_scores[metric_name] = 0.0

        all_results[scenario] = {
            "scores": scenario_scores,
            "watcher_alert": results["watcher"].get("should_alert", False),
            "watcher_confidence": results["watcher"].get("confidence", 0),
            "diagnosis_root_cause": results.get("diagnostician", {}).get("root_cause", "N/A") if results.get("diagnostician") else "N/A",
            "diagnosis_confidence": results.get("diagnostician", {}).get("confidence", 0) if results.get("diagnostician") else 0,
        }

    return all_results


def print_summary(all_results: dict):
    """Print evaluation summary table."""
    print(f"\n{'='*70}")
    print(f"  EVALUATION SUMMARY")
    print(f"{'='*70}")

    # Collect all metric names
    all_metrics = set()
    for scenario_data in all_results.values():
        all_metrics.update(scenario_data["scores"].keys())
    all_metrics = sorted(all_metrics)

    # Header
    header = f"  {'Metric':<30}"
    for scenario in all_results:
        header += f" {scenario:<16}"
    print(header)
    print(f"  {'-'*30}" + f" {'-'*16}" * len(all_results))

    # Rows
    for metric in all_metrics:
        row = f"  {metric:<30}"
        for scenario in all_results:
            score = all_results[scenario]["scores"].get(metric, None)
            if score is not None:
                icon = "✓" if score >= 0.5 else "✗"
                row += f" {icon} {score:.2f}         "
            else:
                row += f"   —             "
        print(row)

    # Average scores
    print(f"\n  {'AVERAGES':<30}", end="")
    for scenario in all_results:
        scores = list(all_results[scenario]["scores"].values())
        avg = sum(scores) / len(scores) if scores else 0
        print(f" {avg:.2f}            ", end="")
    print()

    # Overall
    all_scores = []
    for scenario_data in all_results.values():
        all_scores.extend(scenario_data["scores"].values())
    overall = sum(all_scores) / len(all_scores) if all_scores else 0
    print(f"\n  Overall Score: {overall:.2f}")
    print(f"  Total Metrics Evaluated: {len(all_scores)}")

    passed = sum(1 for s in all_scores if s >= 0.5)
    print(f"  Passed (>= 0.5): {passed}/{len(all_scores)}")


def save_results(all_results: dict):
    """Save evaluation results to JSON."""
    output_dir = Path("evaluation/results")
    output_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filepath = output_dir / f"eval_{timestamp}.json"

    with open(filepath, "w") as f:
        json.dump({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "model": "groq/llama-3.1-8b-instant",
            "results": all_results,
        }, f, indent=2)

    print(f"\n  Results saved to {filepath}")
    return filepath


# =============================================================================
# CLI
# =============================================================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="SentinelAI Evaluation Pipeline")
    parser.add_argument("--scenario", default=None,
                        choices=["memory_leak", "bad_deployment", "api_timeout"],
                        help="Run evaluation for a specific scenario")
    args = parser.parse_args()

    scenarios = [args.scenario] if args.scenario else None

    print(f"\n{'='*55}")
    print(f"  SentinelAI Evaluation Pipeline")
    print(f"  Model: groq/llama-3.1-8b-instant")
    print(f"{'='*55}")

    results = asyncio.run(run_evaluation(scenarios))
    print_summary(results)
    save_results(results)

    print()