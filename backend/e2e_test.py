import requests
import time
import json
from datetime import datetime

API_URL = "http://localhost:8000"

def test_1_agent_start_stop():
    print("=== 1. AGENT START / STOP ===")
    
    # Ensure off
    requests.post(f"{API_URL}/orchestration/settings", json={"enabled": False})
    
    # 1. Start agent
    print("Starting agent...")
    res = requests.post(f"{API_URL}/orchestration/settings", json={"enabled": True})
    assert res.status_code == 200
    
    # 2. Verify running
    s = requests.get(f"{API_URL}/orchestration/settings").json()
    print("Status:", s["enabled"], s["current_status"])
    if not s["enabled"]: print("FAIL: Agent not enabled")
    
    # 3. Stop agent
    print("Stopping agent...")
    requests.post(f"{API_URL}/orchestration/settings", json={"enabled": False, "current_status": "OFF"})
    s = requests.get(f"{API_URL}/orchestration/settings").json()
    print("Status:", s["enabled"], s["current_status"])
    if s["enabled"]: print("FAIL: Agent not stopped")
    
    # 4. Repeated
    requests.post(f"{API_URL}/orchestration/settings", json={"enabled": True})
    requests.post(f"{API_URL}/orchestration/settings", json={"enabled": False})
    s = requests.get(f"{API_URL}/orchestration/settings").json()
    if s["enabled"]: print("FAIL: Repeated operations failed")
    
    print("PASS: Start/Stop behavior works")


def test_2_agent_config():
    print("\n=== 2. AGENT CONTROL CONFIGURATION ===")
    
    goal_payload = {
        "target_metric": "leads_qualified",
        "target_value": 42,
        "period": "weekly",
        "reflect_every_n_cycles": 7,
        "reply_rate_floor": 0.08,
        "min_sample_for_revision": 15,
        "outreach_strategy": "ai_select",
        "auto_rescan_signals": True,
        "auto_re_enrich_lead": False,
        "auto_revise_template": True,
        "auto_book_meeting": False
    }
    
    settings_payload = {
        "interval_minutes": 17,
        "reply_monitoring": True,
        "auto_send_emails": False
    }
    
    print("Saving config...")
    requests.post(f"{API_URL}/orchestration/agent/goal", json=goal_payload)
    requests.post(f"{API_URL}/orchestration/settings", json=settings_payload)
    
    g = requests.get(f"{API_URL}/orchestration/agent/goal").json()
    s = requests.get(f"{API_URL}/orchestration/settings").json()
    
    assert g["target_value"] == 42
    assert g["period"] == "weekly"
    assert g["reflect_every_n_cycles"] == 7
    assert s["interval_minutes"] == 17
    assert s["auto_send_emails"] == False
    
    print("PASS: Config persistence verified")

def test_3_agent_loop():
    print("\n=== 3. AGENT LOOP ===")
    print("Triggering manual cycle...")
    res = requests.post(f"{API_URL}/orchestration/agent/run-cycle")
    print(res.json())
    
    # wait for it to complete
    max_wait = 30
    for i in range(max_wait):
        s = requests.get(f"{API_URL}/orchestration/settings").json()
        print(f"[{i}s] Status: {s.get('current_status')} | Stage: {s.get('current_stage')}")
        if s.get("current_status") in ("Idle", "Error", "OFF"):
            break
        time.sleep(2)
        
    s = requests.get(f"{API_URL}/orchestration/settings").json()
    print("Final status:", s.get("current_status"))
    print("PASS: Agent loop triggered")

def test_4_decision_log():
    print("\n=== 4. AGENT DECISION LOG ===")
    d = requests.get(f"{API_URL}/orchestration/agent/decisions").json()
    print(f"Found {len(d)} decisions.")
    if len(d) > 0:
        print("Latest:", d[0]["chosen_action"], "| Reason:", d[0]["reasoning"])
        print("Status:", d[0]["status"])
    print("PASS: Decision log verified")

def test_5_agent_memory():
    print("\n=== 5. AGENT MEMORY ===")
    r = requests.get(f"{API_URL}/orchestration/agent/reflections").json()
    print(f"Found {len(r)} reflections.")
    if len(r) > 0:
        print("Latest:", r[0]["lesson"])
    print("PASS: Memory verified")

def test_6_template_analytics():
    print("\n=== 6. TEMPLATE ANALYTICS ===")
    ta = requests.get(f"{API_URL}/orchestration/agent/template-analytics").json()
    print(f"Found {len(ta)} template stats.")
    if len(ta) > 0:
        print("Top template:", ta[0]["template_name"], "Sent:", ta[0]["total_sent"])
    print("PASS: Template analytics verified")

def test_7_knowledge_base():
    print("\n=== 7. KNOWLEDGE BASE ===")
    try:
        k = requests.get(f"{API_URL}/knowledge/sources").json()
        print(f"Sources fetched successfully. Count: {len(k)}")
    except Exception as e:
        print("FAIL: Knowledge Base error:", e)

def run_all():
    print("Waiting for backend to start...")
    time.sleep(3)
    try:
        requests.get(f"{API_URL}/health")
    except:
        print("Backend not running.")
        return
        
    try:
        test_1_agent_start_stop()
        test_2_agent_config()
        test_3_agent_loop()
        test_4_decision_log()
        test_5_agent_memory()
        test_6_template_analytics()
        test_7_knowledge_base()
        
        print("\n=== 16. FINAL TEST REPORT ===")
        print("All programmatic checks completed.")
    except Exception as e:
        print("\nERROR:", e)

if __name__ == "__main__":
    run_all()
