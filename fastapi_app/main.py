import os
import time
import socket
import threading
from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.responses import JSONResponse
from prometheus_client import Counter, Gauge, make_asgi_app
from opentelemetry import trace
from opentelemetry.exporter.jaeger.thrift import JaegerExporter
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

# Initialize FastAPI App
app = FastAPI(title="GhostOps FastAPI Core Application", version="1.0.0")

# --- OpenTelemetry Instrumentation Setup ---
JAEGER_HOST = os.getenv("JAEGER_HOST", "localhost")
JAEGER_PORT = int(os.getenv("JAEGER_PORT", "6831"))
POD_NAME = os.getenv("POD_NAME", socket.gethostname())

try:
    resource = Resource(attributes={
        SERVICE_NAME: "ghostops-fastapi-app",
        "k8s.pod.name": POD_NAME,
        "k8s.node.name": os.getenv("NODE_NAME", "unknown")
    })
    provider = TracerProvider(resource=resource)
    jaeger_exporter = JaegerExporter(
        agent_host_name=JAEGER_HOST,
        agent_port=JAEGER_PORT,
    )
    processor = BatchSpanProcessor(jaeger_exporter)
    provider.add_span_processor(processor)
    trace.set_tracer_provider(provider)
    print(f"Jaeger OpenTelemetry initialized successfully targeting {JAEGER_HOST}:{JAEGER_PORT}")
except Exception as e:
    print(f"Warning: Jaeger OpenTelemetry initialization failed: {e}. Fallback to console/no-op.")

tracer = trace.get_tracer("ghostops-fastapi-core")

# --- Prometheus Metrics ---
REQUEST_COUNTER = Counter(
    "ghostops_http_requests_total", 
    "Total HTTP requests handled by the FastAPI application", 
    ["method", "endpoint", "status_code"]
)
CPU_SPIKE_GAUGE = Gauge(
    "ghostops_simulated_cpu_utilization", 
    "Simulated CPU usage percentage (0-100%)"
)
MEMORY_LEAK_GAUGE = Gauge(
    "ghostops_simulated_memory_leaked_mb", 
    "Simulated Memory leaked and held in MB"
)

# Set defaults
CPU_SPIKE_GAUGE.set(10.0)  # Baseline simulated CPU
MEMORY_LEAK_GAUGE.set(0.0) # Baseline simulated Memory

# Global state to hold simulated memory leak
MEMORY_LEAK_POOL = []

# --- Middleware for metrics logging ---
@app.middleware("http")
async def track_metrics_and_traces(request, call_next):
    method = request.method
    endpoint = request.url.path
    
    # Avoid tracking metrics endpoint request loops
    if endpoint == "/metrics":
        return await call_next(request)
        
    start_time = time.time()
    try:
        response = await call_next(request)
        status_code = str(response.status_code)
        return response
    except Exception as e:
        status_code = "500"
        raise e
    finally:
        latency = time.time() - start_time
        REQUEST_COUNTER.labels(method=method, endpoint=endpoint, status_code=status_code).inc()

# --- CPU Chaos Thread Workers ---
def run_cpu_chaos(duration_seconds: int, parent_span_context=None):
    # Setup OpenTelemetry tracer context if propagated
    ctx = trace.set_span_in_context(trace.NonRecordingSpan(parent_span_context)) if parent_span_context else None
    with tracer.start_as_current_span("cpu_chaos_spike_worker", context=ctx) as span:
        span.set_attribute("chaos.type", "cpu_spike")
        span.set_attribute("chaos.duration", duration_seconds)
        
        print(f"Starting CPU spike for {duration_seconds}s...")
        CPU_SPIKE_GAUGE.set(100.0)
        end_time = time.time() + duration_seconds
        
        # Heavy CPU work loop
        while time.time() < end_time:
            # Active spinning for mathematical calculations
            _ = [x ** 2 for x in range(1000)]
            
        CPU_SPIKE_GAUGE.set(10.0)
        print("CPU spike ended.")

# --- Endpoints ---
@app.get("/")
async def get_service_info():
    with tracer.start_as_current_span("get_service_info") as span:
        info = {
            "service": "GhostOps Core App",
            "hostname": socket.gethostname(),
            "pod_name": os.getenv("POD_NAME", "local-dev"),
            "node_name": os.getenv("NODE_NAME", "local-node"),
            "status": "Running",
            "timestamp": time.time(),
            "cpu_baseline": "10%",
            "memory_leak_active": f"{len(MEMORY_LEAK_POOL) * 50} MB leaked"
        }
        span.set_attribute("app.hostname", info["hostname"])
        return JSONResponse(content=info)

@app.get("/health")
async def health_check():
    # Keep lightweight, no telemetry to avoid cluttering traces
    return {"status": "healthy", "pod": os.getenv("POD_NAME", "local-dev")}

@app.post("/chaos/cpu")
async def trigger_cpu_chaos(background_tasks: BackgroundTasks, duration: int = 15):
    current_span = trace.get_current_span().get_span_context()
    background_tasks.add_task(run_cpu_chaos, duration, current_span)
    return {
        "status": "triggered", 
        "message": f"CPU spike daemon initiated for {duration} seconds.",
        "pod": os.getenv("POD_NAME", "local-dev")
    }

@app.post("/chaos/memory")
async def trigger_memory_leak(leak_mb: int = 50):
    with tracer.start_as_current_span("memory_chaos_leak") as span:
        span.set_attribute("chaos.type", "memory_leak")
        span.set_attribute("chaos.leak_size_mb", leak_mb)
        
        try:
            # Allocate arbitrary block of memory (approx leak_mb Megabytes)
            # 1 MB is roughly 1024 * 1024 characters/bytes
            block = bytearray(leak_mb * 1024 * 1024)
            MEMORY_LEAK_POOL.append(block)
            
            current_total = len(MEMORY_LEAK_POOL) * leak_mb
            MEMORY_LEAK_GAUGE.set(float(current_total))
            
            print(f"Allocated leak of {leak_mb} MB. Total simulated leak: {current_total} MB")
            return {
                "status": "success",
                "message": f"Successfully leaked {leak_mb} MB.",
                "total_leaked_mb": current_total,
                "allocations_count": len(MEMORY_LEAK_POOL),
                "pod": os.getenv("POD_NAME", "local-dev")
            }
        except MemoryError:
            span.record_exception(MemoryError("OOM simulated allocation failure!"))
            raise HTTPException(status_code=500, detail="Out of Memory simulation triggered crash!")

@app.post("/chaos/reset")
async def reset_chaos():
    global MEMORY_LEAK_POOL
    with tracer.start_as_current_span("chaos_reset") as span:
        MEMORY_LEAK_POOL.clear()
        MEMORY_LEAK_GAUGE.set(0.0)
        CPU_SPIKE_GAUGE.set(10.0)
        return {
            "status": "reset", 
            "message": "Simulated resources and memory allocations have been cleared."
        }

# Mount Prometheus ASGI handler to expose standard and custom gauges/counters
metrics_app = make_asgi_app()
app.mount("/metrics", metrics_app)

# Instrument the FastAPI app automatically
FastAPIInstrumentor.instrument_app(app)
