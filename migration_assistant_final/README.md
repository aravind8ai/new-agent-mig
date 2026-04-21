# AWS Migration Assistant (Golden Copy)

This repository contains the complete, self-contained source code for deploying the **AWS Migration Assistant**. 
It is designed as a "Zero-to-Hero" package that provisions AWS Fargate infrastructure, builds a Docker image (React + Python), and deploys it behind an SSL-enabled Application Load Balancer.

## 📂 Project Structure

*   **`backend/`**: Python Agent (Bedrock + IAM Tools), Nginx Config, Supervisor Config.
*   **`frontend/`**: React + Vite Application.
*   **`infrastructure/`**: Python script (`provision.py`) to set up AWS resources (IAM, S3, ECR, ECS, ALB).
*   **`deploy.sh`**: Shell script to Build & Push the Docker image and update the Fargate Service.
*   **`Dockerfile`**: Multi-stage build definition.

---

## 🚀 Prerequisites

1.  **AWS CLI**: Installed and configured (`aws configure`).
2.  **Docker Desktop**: Running (required for building images).
3.  **Python 3.11+**: For running the provisioning script.

---

## ⚙️ Configuration

Create a `.env` file in this directory based on your needs. 
This file drives the naming of all AWS resources, enabling you to deploy multiple copies of the app side-by-side.

**Example `.env`**:

```bash
# --- AWS Credentials (Optional if using default profile) ---
# AWS_ACCESS_KEY_ID=...
# AWS_SECRET_ACCESS_KEY=...
# AWS_SESSION_TOKEN=...
AWS_DEFAULT_REGION=us-east-1

# --- Application Identity (Variabilized) ---
# Change this to create a completely new stack (e.g., "my-agent-v2")
APP_NAME=migration-agent-cloud
APP_TITLE="My Custom Assistant" # Updates the UI Header & Welcome Message

# --- Domain & SSL (Optional) ---
# If invalid or missing, ALB will use HTTP only
DOMAIN_NAME=migratecompanion.evidhai.com
ACM_CERT_ARN=arn:aws:acm:us-east-1:123456789012:certificate/uuid-here

# --- Gateway Tools ---
# If using external Bedrock Gateway resources
GATEWAY_URL=...
```

---

## 🌊 Flow of Execution (Deployment Order)

To deploy the full solution from scratch, **follow these steps in order**:

1.  **Deploy Backend Tools (Lambda)**:
    *   Creates separate Lambda function for `cost_assistant` and `vpc_subnet_calculator`.
    *   **Run**: `python infrastructure/create_tools_lambda.py`
    *   **Result**: Deploys `migration-agent-cloud-tools` (or your custom name).

2.  **Provision Infrastructure (One-Time)**:
    *   Creates VPC networking, ALB, ECS Cluster, and IAM Roles.
    *   *Automatically grants permission* for the App to call the Tools Lambda from Step 1.
    *   **Run**: `python infrastructure/provision.py`

3.  **Deploy Application (Iterative)**:
    *   Builds the React Frontend & Python Backend.
    *   Pushes Docker Image to ECR.
    *   Updates Fargate Service.
    *   **Run**: `./deploy.sh`

---

## 🛠️ Infrastructure Provisioning Details
    ```bash
    python3 -m venv .venv
    source .venv/bin/activate
    pip install -r backend/requirements.pip
    ```

2.  **Run Provisioning**:
    ```bash
    python infrastructure/provision.py
    ```
    *   *Note: If you change `APP_NAME`, this will create a FRESH set of resources.*

---

## 📦 Deployment (Build & Update)

To build the Docker image (Frontend + Backend) and deploy code changes:

```bash
./deploy.sh
```

*   Builds React Frontend (Native Platform).
*   Builds Python Backend.
*   Pushes to ECR.
*   Forces ECS Service update.

---

## 🏛️ Architecture

*   **Compute**: AWS Fargate (Serverless Containers).
*   **Networking**: ALB (public) -> Fargate (private subnet).
*   **Container**: Unified Container running:
    *   **Nginx (Port 8000)**: Serves React Static files + Reverse Proxy.
    *   **Python (Port 8081)**: Bedrock Agent Runtime (Uvicorn).
    *   **Supervisor**: Manages both processes.
*   **Security**: IAM Roles (Hybrid Pattern) - No long-term keys in code.

---

## 🧹 Cleanup
To delete everything, you can use the automated cleanup script:

```bash
python infrastructure/cleanup.py
```

**WARNING**: This script will permanently delete all resources associated with your `APP_NAME`. It will ask for confirmation before proceeding.

Alternatively, you can manually delete:
*   ECS Service & Cluster
*   ALB & Target Group
*   ECR Repository
*   CloudWatch Log Groups
*   IAM Roles (`*-task-role`, `*-execution-role`)
