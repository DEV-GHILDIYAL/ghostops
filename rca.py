import sys
import os
import base64
import subprocess
import requests
import json
import datetime
from dotenv import load_dotenv
from opentelemetry import trace
from opentelemetry.exporter.jaeger.thrift import JaegerExporter
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

load_dotenv()

# --- OpenTelemetry Tracing Setup ---
JAEGER_HOST = os.getenv("JAEGER_HOST", "localhost")
JAEGER_PORT = int(os.getenv("JAEGER_PORT", "6831"))

try:
    resource = Resource(attributes={SERVICE_NAME: "ghostops-rca"})
    provider = TracerProvider(resource=resource)
    jaeger_exporter = JaegerExporter(agent_host_name=JAEGER_HOST, agent_port=JAEGER_PORT)
    processor = BatchSpanProcessor(jaeger_exporter)
    provider.add_span_processor(processor)
    trace.set_tracer_provider(provider)
except Exception as e:
    # Fail silently, continue without telemetry
    pass

tracer = trace.get_tracer("ghostops-rca-compiler")
ACTIVE_TRACE_FILE = "active_trace.json"

def get_groq_api_key():
    """Retrieves GROQ_API_KEY from environment or directly from Kubernetes Secret fallback."""
    api_key = os.getenv("GROQ_API_KEY")
    if api_key:
        print("GROQ_API_KEY extracted from local Environment Variable.")
        return api_key

    # Secret retrieval fallback via kubectl
    print("Warning: GROQ_API_KEY not found in Environment. Querying Kubernetes Secrets...")
    cmd = ["kubectl", "get", "secret", "ghostops-secrets", "-o", "jsonpath={.data.GROQ_API_KEY}"]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode == 0 and result.stdout.strip():
        try:
            encoded_key = result.stdout.strip()
            decoded_bytes = base64.b64decode(encoded_key)
            decoded_key = decoded_bytes.decode("utf-8").strip()
            print("GROQ_API_KEY successfully extracted and decoded from Kubernetes Secret 'ghostops-secrets'.")
            return decoded_key
        except Exception as e:
            print(f"Error decoding base64 key from Kubernetes Secret: {e}")
    else:
        print(f"Error: Could not retrieve secret via kubectl: {result.stderr.strip()}")
        
    return None

def log_rca_locally(report_data):
    reports = []
    try:
        with open("rca_reports.json", "r") as f:
            reports = json.load(f)
    except:
        pass
    reports.append(report_data)
    with open("rca_reports.json", "w") as f:
        json.dump(reports, f, indent=4)

def notify_dashboard_rca(report_data):
    """Streams the generated RCA report directly to the Flask dashboard API via POST."""
    try:
        url = "http://localhost:5000/api/rca"
        res = requests.post(url, json=report_data, timeout=2)
        if res.status_code == 200:
            print("Successfully streamed AI RCA report to Flask Dashboard WebSockets.")
    except:
        # Flask dashboard might not be running, fail silently
        pass

def generate_rca(pod_name, terminated_at, recovery_seconds):
    # Retrieve base64 decoded API Key from K8s Secret or Env
    api_key = get_groq_api_key()
    if not api_key:
        print("CRITICAL: GROQ_API_KEY could not be resolved. Aborting RCA generation.")
        return

    # Extract parent trace context if healer propagated one
    parent_ctx = None
    if os.path.exists(ACTIVE_TRACE_FILE):
        try:
            with open(ACTIVE_TRACE_FILE, "r") as f:
                carrier = json.load(f)
            parent_ctx = TraceContextTextMapPropagator().extract(carrier=carrier)
        except:
            pass

    # Trace AI RCA generation in Jaeger
    with tracer.start_as_current_span("generate_ai_rca", context=parent_ctx) as span:
        span.set_attribute("rca.target_pod", pod_name)
        span.set_attribute("rca.recovery_seconds", recovery_seconds)
        
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": "llama-3.1-8b-instant",
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are an elite Site Reliability Engineer (SRE) assistant. "
                        "Generate a highly technical and professional Root Cause Analysis (RCA) report. "
                        "Keep it concise, bulleted, and informative. Use markdown."
                    )
                },
                {
                    "role": "user",
                    "content": (
                        f"Pod {pod_name} terminated unexpectedly at {terminated_at}. "
                        f"The self-healing cycle successfully recovered the system in {recovery_seconds} seconds. "
                        "Draft a clean SRE RCA post-mortem containing: "
                        "1. INCIDENT DESCRIPTION, 2. POTENTIAL ROOT CAUSES (mentioning CrashLoop or CPU/Memory resource exhaustion spikes), "
                        "3. AUTOMATED REMEDIATION DETAILS, 4. RESILIENCY RECOMMENDATION."
                    )
                }
            ]
        }
        
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=10)
            response.raise_for_status()
            data = response.json()
            report_content = data['choices'][0]['message']['content']
            
            print("\n--- ROOT CAUSE ANALYSIS REPORT ---")
            print(report_content)
            print("----------------------------------\n")
            
            report_payload = {
                "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "pod_name": pod_name,
                "report": report_content
            }
            
            # Log locally
            log_rca_locally(report_payload)
            # Stream dynamically to Flask Socket.IO dashboard
            notify_dashboard_rca(report_payload)
            
            span.set_attribute("rca.status", "completed")
            
        except requests.exceptions.RequestException as e:
            span.record_exception(e)
            print(f"Error calling Groq API: {e}")
            if hasattr(e, 'response') and e.response is not None:
                print(f"Response details: {e.response.text}")

if __name__ == "__main__":
    if len(sys.argv) < 4:
        print("Usage: python rca.py <pod_name> <terminated_at> <recovery_seconds>")
        sys.exit(1)

    generate_rca(sys.argv[1], sys.argv[2], sys.argv[3])