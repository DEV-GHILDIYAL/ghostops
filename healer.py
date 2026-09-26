import os
import time
import json
import datetime
import subprocess
import requests
from dotenv import load_dotenv
from opentelemetry import trace
from opentelemetry.exporter.jaeger.thrift import JaegerExporter
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

load_dotenv()

# --- OpenTelemetry Setup ---
JAEGER_HOST = os.getenv("JAEGER_HOST", "localhost")
JAEGER_PORT = int(os.getenv("JAEGER_PORT", "6831"))

try:
    resource = Resource(attributes={SERVICE_NAME: "ghostops-healer"})
    provider = TracerProvider(resource=resource)
    jaeger_exporter = JaegerExporter(agent_host_name=JAEGER_HOST, agent_port=JAEGER_PORT)
    processor = BatchSpanProcessor(jaeger_exporter)
    provider.add_span_processor(processor)
    trace.set_tracer_provider(provider)
    print(f"Healer OpenTelemetry initialized successfully targeting {JAEGER_HOST}:{JAEGER_PORT}")
except Exception as e:
    print(f"Warning: Jaeger connection failed in Healer: {e}. Running without tracing.")

tracer = trace.get_tracer("ghostops-healer-daemon")

STRUCTURED_LOG_FILE = "healer_structured.log"
ACTIVE_TRACE_FILE = "active_trace.json"

def log_structured(event_type, message, **kwargs):
    """Writes a structured JSON log entry for Loki ingestion."""
    log_entry = {
        "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "level": "INFO",
        "event_type": event_type,
        "message": message,
        **kwargs
    }
    # Append to local structured log
    with open(STRUCTURED_LOG_FILE, "a") as f:
        f.write(json.dumps(log_entry) + "\n")
    print(f"[{log_entry['timestamp']}] [{event_type.upper()}] {message}")

def notify_dashboard_event(event):
    """Sends the healing event details directly to the Flask dashboard API."""
    try:
        url = "http://localhost:5000/api/event"
        res = requests.post(url, json=event, timeout=2)
        if res.status_code == 200:
            log_structured("dashboard_stream", "Successfully streamed event to Flask Dashboard WebSockets.")
    except Exception as e:
        # Dashboard might not be running yet, fail silently
        pass

def get_pods_data():
    """Fetches detailed JSON state of active pods."""
    cmd = ["kubectl", "get", "pods", "-l", "app=ghostops-app", "-o", "json"]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        return []
    try:
        return json.loads(result.stdout).get("items", [])
    except:
        return []

def get_degraded_reason(pod):
    """Inspects a pod dictionary to check if it's waiting/degraded."""
    status = pod.get("status", {})
    phase = status.get("phase", "")
    
    if phase in ["Failed", "Unknown"]:
        return f"Phase_{phase}"
        
    container_statuses = status.get("containerStatuses", [])
    for cs in container_statuses:
        state = cs.get("state", {})
        waiting = state.get("waiting", {})
        if waiting:
            reason = waiting.get("reason", "")
            if reason in ["CrashLoopBackOff", "ImagePullBackOff", "ErrImagePull", "CreateContainerConfigError"]:
                return reason
                
        # Also check if it's crashing and restarting frequently
        restart_count = cs.get("restartCount", 0)
        if restart_count > 3:
            return f"HighRestartCount_{restart_count}"
            
    return None

def main():
    log_structured("system_start", "GhostOps Healer Daemon online. Watching cluster every 3 seconds...")
    
    # Track when degraded pods are first seen
    degraded_tracker = {} # {pod_name: first_detected_timestamp}
    
    # Track the active baseline pod names to observe normal deletions
    previous_pods = {p['metadata']['name'] for p in get_pods_data()}
    
    while True:
        time.sleep(3)
        current_pods_data = get_pods_data()
        current_pods = {p['metadata']['name'] for p in current_pods_data}
        
        # --- 1. Identify missing pods (Normal Deletions) ---
        missing_pods = previous_pods - current_pods
        if missing_pods:
            detection_time = time.time()
            timestamp_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            log_structured("pod_deletion_detected", f"Observed pod deletion: {list(missing_pods)}. Initiating health watch.")
            
            # Extract parent trace context if chaos.py generated one
            parent_ctx = None
            if os.path.exists(ACTIVE_TRACE_FILE):
                try:
                    with open(ACTIVE_TRACE_FILE, "r") as f:
                        carrier = json.load(f)
                    parent_ctx = TraceContextTextMapPropagator().extract(carrier=carrier)
                    log_structured("trace_context", "Propagating OTelemetry span context from chaos script.")
                except Exception as e:
                    print(f"Error reading active trace: {e}")

            # Start OpenTelemetry Recovery Span
            with tracer.start_as_current_span("healer_recovery_loop", context=parent_ctx) as span:
                span.set_attribute("healer.action", "monitor_normal_self_healing")
                span.set_attribute("healer.pods_lost", list(missing_pods))
                
                # Wait for Kubernetes to naturally spin up replacement pods and enter 'Running'
                log_structured("self_healing_watch", "Waiting for Kubernetes native scheduler to restore replicas...")
                recovery_start = time.time()
                recovered = False
                
                while time.time() - recovery_start < 45: # Max 45 seconds timeout
                    time.sleep(1.5)
                    check_pods = get_pods_data()
                    running_count = sum(1 for p in check_pods if p.get("status", {}).get("phase") == "Running")
                    
                    if running_count >= 3:
                        recovered = True
                        break
                
                recovery_seconds = int(time.time() - detection_time)
                span.set_attribute("healer.mttr_seconds", recovery_seconds)
                span.set_attribute("healer.recovered", recovered)
                
                if recovered:
                    log_structured("self_healing_success", f"Cluster healed natively in {recovery_seconds}s. All 3 replicas running.", mttr=recovery_seconds)
                    
                    # Prepare Event payload
                    event = {
                        "timestamp": timestamp_str,
                        "pods_lost": list(missing_pods),
                        "recovery_seconds": recovery_seconds,
                        "remediation": "Kubernetes Native Re-scheduling (No rollout needed)"
                    }
                    
                    # Log event locally
                    events = []
                    try:
                        with open("events.json", "r") as f:
                            events = json.load(f)
                    except:
                        pass
                    events.append(event)
                    with open("events.json", "w") as f:
                        json.dump(events, f, indent=4)
                        
                    # Stream event directly to Dashboard
                    notify_dashboard_event(event)
                    
                    # Execute AI Root Cause Analysis (RCA) with propagated trace context
                    # Save active trace parent so rca.py can read it
                    for pod_name in missing_pods:
                        subprocess.run(["python", "rca.py", pod_name, timestamp_str, str(recovery_seconds)])
                else:
                    log_structured("self_healing_timeout", "Kubernetes native self-healing timed out. Pod replacement failed to enter Running state.")
                    span.record_exception(TimeoutError("Self-healing timeout! Cluster degraded."))
            
            # Clear trace context file
            if os.path.exists(ACTIVE_TRACE_FILE):
                try:
                    os.remove(ACTIVE_TRACE_FILE)
                except:
                    pass
                    
            # Refresh baselines
            previous_pods = {p['metadata']['name'] for p in get_pods_data()}
            continue

        # --- 2. Check for Persistent Degradation (CrashLoopBackOff / ImagePullBackOff) ---
        for pod in current_pods_data:
            pod_name = pod["metadata"]["name"]
            reason = get_degraded_reason(pod)
            
            if reason:
                if pod_name not in degraded_tracker:
                    degraded_tracker[pod_name] = time.time()
                    log_structured("pod_degradation_detected", f"Pod {pod_name} is showing degraded state ({reason}). Starting 30s counter.")
                else:
                    elapsed = time.time() - degraded_tracker[pod_name]
                    log_structured("pod_degradation_tick", f"Pod {pod_name} degraded for {int(elapsed)}s/30s (Reason: {reason})")
                    
                    # Trigger Rollout Restart if degraded state exceeds 30 seconds
                    if elapsed >= 30:
                        timestamp_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        log_structured("healing_remediation_triggered", f"CRITICAL: Pod {pod_name} degraded >30s. Triggering deployment rollout restart!")
                        
                        with tracer.start_as_current_span("healer_rollout_remediation") as span:
                            span.set_attribute("healer.action", "rollout_restart")
                            span.set_attribute("healer.target_pod", pod_name)
                            span.set_attribute("healer.degraded_reason", reason)
                            
                            # Trigger K8s rollout restart
                            subprocess.run(["kubectl", "rollout", "restart", "deployment/ghostops-app"])
                            
                            # Block and wait for rollout success
                            rollout_start = time.time()
                            rollout_success = False
                            while time.time() - rollout_start < 60:
                                time.sleep(2)
                                check_pods = get_pods_data()
                                # All 3 new replicas should be healthy
                                healthy_count = sum(1 for p in check_pods if p.get("status", {}).get("phase") == "Running" and not get_degraded_reason(p))
                                if healthy_count >= 3:
                                    rollout_success = True
                                    break
                            
                            rollout_duration = int(time.time() - rollout_start)
                            span.set_attribute("healer.rollout_duration", rollout_duration)
                            
                            if rollout_success:
                                log_structured("rollout_remediation_success", f"Rollout completed. Replicas restored in {rollout_duration}s.")
                                
                                # Log event
                                event = {
                                    "timestamp": timestamp_str,
                                    "pods_lost": [pod_name],
                                    "recovery_seconds": rollout_duration,
                                    "remediation": f"Deployment Rollout Restart (Reason: {reason})"
                                }
                                
                                events = []
                                try:
                                    with open("events.json", "r") as f:
                                        events = json.load(f)
                                except:
                                    pass
                                events.append(event)
                                with open("events.json", "w") as f:
                                    json.dump(events, f, indent=4)
                                    
                                notify_dashboard_event(event)
                                subprocess.run(["python", "rca.py", pod_name, timestamp_str, str(rollout_duration)])
                            else:
                                log_structured("rollout_remediation_failed", "Rollout restart timed out. Cluster remains in critical degraded state.")
                                span.record_exception(RuntimeError("Remediation failed to restore replicas!"))
                                
                        # Reset tracker for this pod
                        degraded_tracker.pop(pod_name, None)
                        break # Break inner loop to refresh cluster state
            else:
                # If pod returned to healthy state, remove from tracker
                if pod_name in degraded_tracker:
                    log_structured("pod_restored", f"Pod {pod_name} successfully recovered from transient degradation.")
                    degraded_tracker.pop(pod_name, None)
                    
        previous_pods = current_pods

if __name__ == "__main__":
    main()
