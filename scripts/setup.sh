#!/usr/bin/env bash

# Color codes for output
GREEN='\033[0;32m'
RED='\033[0;31m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${CYAN}"
echo "================================================================="
echo "        👻 GHOSTOPS - PRODUCTION-GRADE INFRASTRUCTURE SETUP       "
echo "================================================================="
echo -e "${NC}"

# Check for required tools
for tool in minikube kubectl helm docker; do
    if ! command -v $tool &> /dev/null; then
        echo -e "${RED}Error: Required command '$tool' is not installed. Aborting.${NC}"
        exit 1
    fi
done

# --- 1. Start Minikube ---
echo -e "${GREEN}[1/7] Initializing Minikube cluster...${NC}"
minikube status &> /dev/null
if [ $? -ne 0 ]; then
    echo "Minikube is stopped. Starting cluster..."
    minikube start --driver=docker
else
    echo "Minikube is already running."
fi

# --- 2. Add Helm Repositories ---
echo -e "${GREEN}[2/7] Adding & updating Helm chart repositories...${NC}"
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo add grafana https://grafana.github.io/helm-charts
helm repo update

# --- 3. Install kube-prometheus-stack ---
echo -e "${GREEN}[3/7] Deploying Prometheus + Grafana (kube-prometheus-stack)...${NC}"
helm upgrade --install prometheus-stack prometheus-community/kube-prometheus-stack \
    --namespace monitoring \
    --create-namespace \
    --set grafana.adminPassword=admin \
    --wait

# --- 4. Install loki-stack ---
echo -e "${GREEN}[4/7] Deploying Grafana Loki + Promtail log aggregator...${NC}"
helm upgrade --install loki-stack grafana/loki-stack \
    --namespace monitoring \
    --set loki.auth_enabled=false \
    --wait

# --- 5. Point to Minikube Docker daemon & Build FastAPI image ---
echo -e "${GREEN}[5/7] Pointing terminal context to Minikube's Docker daemon...${NC}"
eval $(minikube -p minikube docker-env)

echo "Building Custom FastAPI Application container image inside Minikube..."
docker build -t ghostops-fastapi-app:latest ./fastapi_app/

# --- 6. Apply Kubernetes Manifests ---
echo -e "${GREEN}[6/7] Resolving API credentials and applying Kubernetes manifests...${NC}"

# Extract GROQ_API_KEY from local .env if present to automatically configure K8s Secret
if [ -f .env ]; then
    # Extract API key while supporting Unix/macOS/Windows line-endings
    API_KEY=$(grep -E "^GROQ_API_KEY=" .env | cut -d'=' -f2- | tr -d '\r\n')
    if [ ! -z "$API_KEY" ]; then
        echo "Found GROQ_API_KEY in local .env. Encrypting and mapping to Secret..."
        ENCODED_KEY=$(echo -n "$API_KEY" | base64 | tr -d '\r\n ')
        
        # Output resolved secrets manifest temporarily
        sed "s|cGxhY2Vob2xkZXJfZ3JvcV9hcGlfa2V5X2hlcmU=|$ENCODED_KEY|g" k8s/secrets.yaml > k8s/secrets-resolved.yaml
        kubectl apply -f k8s/secrets-resolved.yaml
        rm k8s/secrets-resolved.yaml
    else
        echo -e "${YELLOW}Warning: GROQ_API_KEY in .env is empty. Deploying Secret template placeholder.${NC}"
        kubectl apply -f k8s/secrets.yaml
    fi
else
    echo -e "${YELLOW}Warning: No local .env file found. Deploying Secret template placeholder.${NC}"
    kubectl apply -f k8s/secrets.yaml
fi

# Deploy Jaeger All-in-One and core FastAPI App
kubectl apply -f k8s/jaeger.yaml
kubectl apply -f app.yaml

# --- 7. Configure background port-forwarding ---
echo -e "${GREEN}[7/7] Configuring local port-forward tunnels for Grafana and Jaeger...${NC}"

# Kill any existing background port-forwards to prevent address binding conflicts
if command -v pkill &> /dev/null; then
    pkill -f "port-forward" || true
fi

echo "Forwarding Jaeger Query UI to http://localhost:16686..."
kubectl port-forward svc/jaeger-query 16686:16686 > /dev/null 2>&1 &

echo "Forwarding Grafana UI to http://localhost:3000..."
kubectl port-forward -n monitoring svc/prometheus-stack-grafana 3000:80 > /dev/null 2>&1 &

# Fetch Minikube IP
MINIKUBE_IP=$(minikube ip)

echo -e "\n${GREEN}=================================================================${NC}"
echo -e "${GREEN}      👻 GHOSTOPS PRODUCTION-GRADE ENVIRONMENT READY             ${NC}"
echo -e "${GREEN}=================================================================${NC}\n"
echo -e "Access all components using the following details:"
echo -e ""
echo -e "  🌐 ${CYAN}Flask Dashboard (Control Room)${NC}  : http://localhost:5000"
echo -e "  🚀 ${CYAN}FastAPI App (Kubernetes Host)${NC}   : http://${MINIKUBE_IP}:30080"
echo -e "  📊 ${CYAN}Grafana Dashboard (Monitoring)${NC}  : http://localhost:3000"
echo -e "     ${YELLOW}Credentials${NC}                    : User: admin | Password: admin"
echo -e "  🔍 ${CYAN}Jaeger Distributed Tracing UI${NC}  : http://localhost:16686"
echo -e ""
echo -e "To launch background control loops:"
echo -e "  1. Run Flask dashboard    : ${YELLOW}python app.py${NC} (Terminal A)"
echo -e "  2. Run Autonomous Healer  : ${YELLOW}python healer.py${NC} (Terminal B)"
echo -e "\n================================================================="
