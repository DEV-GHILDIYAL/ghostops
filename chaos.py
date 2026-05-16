import subprocess
import random
import datetime
import json

def get_pods():
    """Returns a list of pod names for the ghostops-app deployment."""
    cmd = ["kubectl", "get", "pods", "-l", "app=ghostops-app", "-o", "json"]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Error fetching pods: {result.stderr}")
        return []
    
    data = json.loads(result.stdout)
    return [item['metadata']['name'] for item in data['items']]

def kill_pod(pod_name):
    """Deletes a specific pod."""
    cmd = ["kubectl", "delete", "pod", pod_name]
    print(f"[{datetime.datetime.now()}] CHAOS: Target locked on {pod_name}...")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode == 0:
        print(f"[{datetime.datetime.now()}] CHAOS: Pod {pod_name} has been terminated.")
    else:
        print(f"Error killing pod: {result.stderr}")

def main():
    pods = get_pods()
    if not pods:
        print("No ghostops pods found. Ensure the deployment is running.")
        return

    pod_to_kill = random.choice(pods)
    kill_pod(pod_to_kill)

if __name__ == "__main__":
    main()
