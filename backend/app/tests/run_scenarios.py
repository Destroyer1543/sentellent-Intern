# tests/run_scenarios.py
import json
import sys
from typing import Any, Dict, List

from fastapi.testclient import TestClient

# IMPORTANT: adjust import if your app is in a different module
from app.main import app


client = TestClient(app)

def _fail(name: str, msg: str) -> None:
    raise AssertionError(f"[{name}] {msg}")

def _get(d: Dict[str, Any], path: str) -> Any:
    cur: Any = d
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur

def _assert_expect(test_name: str, resp_json: Dict[str, Any], expect: Dict[str, Any]) -> None:
    reply = resp_json.get("reply", "") or ""

    # reply_contains: list of substrings
    if "reply_contains" in expect:
        for s in expect["reply_contains"]:
            if s.lower() not in reply.lower():
                _fail(test_name, f"Expected reply to contain '{s}', got: {reply}")

    # pending_action_null: bool
    if expect.get("pending_action_null") is True:
        if resp_json.get("pending_action") is not None:
            _fail(test_name, f"Expected pending_action null, got: {resp_json.get('pending_action')}")

    # pending_action_type: string
    if "pending_action_type" in expect:
        pa = resp_json.get("pending_action")
        if not isinstance(pa, dict):
            _fail(test_name, f"Expected pending_action dict, got: {pa}")
        if pa.get("type") != expect["pending_action_type"]:
            _fail(test_name, f"Expected pending_action.type={expect['pending_action_type']}, got: {pa.get('type')}")

    # json_path_equals: {"path":"value"} (optional)
    if "json_path_equals" in expect:
        for path, expected_value in expect["json_path_equals"].items():
            actual = _get(resp_json, path)
            if actual != expected_value:
                _fail(test_name, f"Expected {path}={expected_value}, got {actual}")

def run() -> int:
    scenarios_path = "app/tests/scenarios.json"
    with open(scenarios_path, "r", encoding="utf-8") as f:
        scenarios: List[Dict[str, Any]] = json.load(f)

    passed = 0
    failed = 0

    for sc in scenarios:
        name = sc.get("name", "(unnamed)")
        steps = sc.get("steps", [])
        print(f"\n=== {name} ===")
        try:
            for i, step in enumerate(steps, start=1):
                endpoint = step["endpoint"]
                payload = step.get("payload", {})
                expect = step.get("expect", {})

                r = client.post(endpoint, json=payload)
                if r.status_code != 200:
                    _fail(name, f"Step {i}: HTTP {r.status_code} - {r.text}")

                resp_json = r.json()
                _assert_expect(name, resp_json, expect)
                print(f"  Step {i}: OK ({endpoint})")

            passed += 1
            print("=> PASS")
        except Exception as e:
            failed += 1
            print(f"=> FAIL: {e}")

    print(f"\nSummary: {passed} passed, {failed} failed")
    return 0 if failed == 0 else 1

if __name__ == "__main__":
    sys.exit(run())
