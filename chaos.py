import os
import sys
import subprocess
import random
import datetime
import json
from opentelemetry import trace
from opentelemetry.exporter.jaeger.thrift import JaegerExporter
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

# --- OpenTelemetry Tracing Setup ---
JAEGER_HOST = os.getenv("JAEGER_HOST", "localhost")
JAEGER_PORT = int(os.getenv("JAEGER_PORT", "6831"))
ACTIVE_TRACE_FILE = "active_trace.json"

try:
    resource = Resource(attributes={SERVICE_NAME: "ghostops-chaos-engine"})
    provider = TracerProvider(resource=resource)
    jaeger_exporter = JaegerExporter(agent_host_name=JAEGER_HOST, agent_port=JAEGER_PORT)
    processor = BatchSpanProcessor(jaeger_exporter)
    provider.add_span_processor(processor)
    trace.set_tracer_provider(provider)
except Exception as e:
    # Running without Jaeger tracing
    pass

tracer = trace.get_tracer("ghostops-chaos-engine")

def get_pods():
    """Returns a list of active pod names for the ghostops-app deployment."""
    cmd = ["kubectl", "get", "pods", "-l", "app=ghostops-app", "-o", "json"]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Error fetching pods: {result.stderr}")
        return []
    try:
        data = json.loads(result.stdout)
        return [item['metadata']['name'] for item in data['items']]
    except:
        return []

def kill_pod(pod_name):
    """Deletes a specific pod under a monitored trace span."""
    # Start OpenTelemetry Span
    with tracer.start_as_current_span("chaos_pod_deletion") as span:
        span.set_attribute("chaos.target_pod", pod_name)
        span.set_attribute("chaos.trigger_time", datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        
        # Inject traceparent context into active_trace.json for healer to propagate
        carrier = {}
        TraceContextTextMapPropagator().inject(carrier=carrier)
        try:
            with open(ACTIVE_TRACE_FILE, "w") as f:
                json.dump(carrier, f, indent=4)
            print(f"Propagated trace context traceparent: {carrier.get('traceparent')}")
        except Exception as e:
            print(f"Warning: Could not save active trace parent: {e}")
            
        cmd = ["kubectl", "delete", "pod", pod_name]
        print(f"[{datetime.datetime.now()}] CHAOS: Target locked on {pod_name}...")
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode == 0:
            print(f"[{datetime.datetime.now()}] CHAOS: Pod {pod_name} has been terminated.")
            span.set_attribute("chaos.status", "success")
        else:
            print(f"Error killing pod: {result.stderr}")
            span.set_attribute("chaos.status", "failed")
            span.record_exception(RuntimeError(result.stderr))

def main():
    pods = get_pods()
    if not pods:
        print("No active ghostops pods found. Ensure the deployment is running.")
        return

    pod_to_kill = random.choice(pods)
    kill_pod(pod_to_kill)

if __name__ == "__main__":
    main()
