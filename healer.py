import subprocess
import time
import json
import datetime
from dotenv import load_dotenv
load_dotenv()
def get_pod_names():
    """Returns a set of current pod names with label app=ghostops-app."""
    cmd = ["kubectl", "get", "pods", "-l", "app=ghostops-app", "-o", "json"]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        return set()
    data = json.loads(result.stdout)
    return {item['metadata']['name'] for item in data['items']}

def log_event(event):
    events = []
    try:
        with open("events.json", "r") as f:
            events = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    events.append(event)
    with open("events.json", "w") as f:
        json.dump(events, f, indent=4)

def main():
    print(f"[{datetime.datetime.now()}] Healer started. Watching every 5 seconds...")
    previous_pods = get_pod_names()
    
    while True:
        time.sleep(5)
        current_pods = get_pod_names()
        
        # Identify missing pods
        missing_pods = previous_pods - current_pods
        
        if missing_pods:
            detection_time = time.time()
            terminated_at_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            print(f"[{terminated_at_str}] HEALING TRIGGERED: {len(missing_pods)} pods lost ({', '.join(missing_pods)}). Restarting deployment.")
            
            # Trigger rollout restart
            subprocess.run(["kubectl", "rollout", "restart", "deployment/ghostops-app"])
            
            # Wait for recovery (all 3 pods back to Running)
            print(f"[{datetime.datetime.now()}] Waiting for recovery...")
            while True:
                time.sleep(2)
                check_cmd = ["kubectl", "get", "pods", "-l", "app=ghostops-app", "-o", "json"]
                res = subprocess.run(check_cmd, capture_output=True, text=True)
                if res.returncode == 0:
                    data = json.loads(res.stdout)
                    running_pods = [p for p in data['items'] if p['status']['phase'] == 'Running']
                    if len(running_pods) >= 3:
                        break
            
            recovery_seconds = int(time.time() - detection_time)
            print(f"[{datetime.datetime.now()}] Recovery complete in {recovery_seconds}s.")
            
            # Log event
            log_event({
                "timestamp": terminated_at_str,
                "pods_lost": list(missing_pods),
                "recovery_seconds": recovery_seconds
            })
            
            # Call RCA script for each missing pod
            for pod_name in missing_pods:
                subprocess.run(["python", "rca.py", pod_name, terminated_at_str, str(recovery_seconds)])
            
            # Refresh state with new pods to avoid loop and add cooldown
            print(f"[{datetime.datetime.now()}] Healing complete. Entering 15s cooldown...")
            time.sleep(15)
            previous_pods = get_pod_names()
        else:
            print(f"[{datetime.datetime.now()}] All pods healthy.")
            previous_pods = current_pods

if __name__ == "__main__":
    main()
