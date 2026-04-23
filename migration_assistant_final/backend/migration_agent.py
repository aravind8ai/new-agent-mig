import os
import boto3
import asyncio
import time
import logging
import json
import re
import sys
from botocore.exceptions import ClientError
from dotenv import load_dotenv
# Load environment variables
load_dotenv()

from strands import Agent
from bedrock_agentcore.runtime import BedrockAgentCoreApp
import uvicorn
from strands.models import BedrockModel

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- SIMPLE MEMORY STORE (Global Dict) ---
# --- SIMPLE MEMORY STORE (Global Dict) ---
# Replacing complex MemoryClient for reliable POC demo
# Replacing complex MemoryClient for reliable POC demo
app = BedrockAgentCoreApp()

GLOBAL_MEMORY_STORE = {}

def add_to_memory(session_id, role, content):
    if session_id not in GLOBAL_MEMORY_STORE:
        GLOBAL_MEMORY_STORE[session_id] = []
    
    GLOBAL_MEMORY_STORE[session_id].append({
        "role": role,
        "content": content,
        "timestamp": time.time()
    })
    print(f"💾 Saved to memory [{session_id}]: {role} - {len(content)} chars")

def get_memory(session_id, limit=10):
    if session_id not in GLOBAL_MEMORY_STORE:
        return []
    return GLOBAL_MEMORY_STORE[session_id][-limit:]

# --- Gateway Configuration ---
# In a real scenario, these would come from environment variables or Secrets Manager
GATEWAY_URL = os.getenv("GATEWAY_URL")
# Dynamic Token Retrieval
import gateway_infra_utils as utils

def get_dynamic_token():
    """Reads credentials from ENV or gateway_auth.json and fetches fresh token"""
    try:
        # 1. Try Environment Variables (Best Practice)
        user_pool_id = os.getenv("GATEWAY_USER_POOL_ID")
        client_id = os.getenv("GATEWAY_CLIENT_ID")
        client_secret = os.getenv("GATEWAY_CLIENT_SECRET")
        scope_string = os.getenv("GATEWAY_SCOPE_STRING")
        
        if user_pool_id and client_id and client_secret:
            # print("DEBUG: Using Credentials from Environment Variables") # Optional debug
            pass
        else:
            # 2. Fallback to gateway_auth.json (Local Dev)
            if os.path.exists("gateway_auth.json"):
                with open("gateway_auth.json", "r") as f:
                    auth_config = json.load(f)
                    user_pool_id = user_pool_id or auth_config.get("user_pool_id")
                    client_id = client_id or auth_config.get("client_id")
                    client_secret = client_secret or auth_config.get("client_secret")
                    scope_string = scope_string or auth_config.get("scope_string")
            else:
                 logger.warning("No auth credentials found (Env or JSON).")
                 return None

        if not (user_pool_id and client_id and client_secret):
            logger.error("Missing required Auth Credentials")
            return None

        token_resp = utils.get_token(
            user_pool_id=user_pool_id,
            client_id=client_id,
            client_secret=client_secret,
            scope_string=scope_string or "",
            # Assuming region is in env or derived, defaulting for now
            region=os.getenv("AWS_DEFAULT_REGION", "us-east-1")
        )
        return token_resp.get("access_token")
    except Exception as e:
        logger.error(f"Failed to fetch dynamic token: {e}")
        return None

def create_gateway_transport():
    """
    Creates the transport to connect to the Bedrock AgentCore Gateway.
    Included Auth headers (OAuth Bearer Token).
    """
    print("DEBUG: Entering create_gateway_transport")
    token = get_dynamic_token()
    print(f"DEBUG: Token fetched: {'YES' if token else 'NO'}")
    
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    else:
        logger.warning("No Auth Token found. Gateway connection may fail if secured.")
    
    print(f"DEBUG: GATEWAY_URL env var: {GATEWAY_URL}")
    
    if not GATEWAY_URL:
        # Check if we can find Gateway ID from deployment output? 
        # For now, we still rely on env var or user providing it.
        logger.error("GATEWAY_URL not set. Raising ValueError.")
        raise ValueError("GATEWAY_URL environment variable is MISSING")

    print(f"DEBUG: Creating streamablehttp_client with URL: {GATEWAY_URL}")
    return streamablehttp_client(GATEWAY_URL, headers=headers)


# --- Local Tools ---
# In a serverless/website context, we process the image payload (base64) directly 
# within the Agent's execution environment. This avoids sending large files over the Gateway.

from strands import tool
import base64

# Global context for image payload (Simple implementation for demo)
# In production, use ContextVar
CURRENT_IMAGE_CONTEXT = {}

@tool
def hld_lld_input_agent(payload):
    """
    Input agent that processes High Level Design (HLD) and Low Level Design (LLD) images.
    If 'IMAGE_PAYLOAD' is passed, it uses the recently uploaded image.
    """
    # Check if we should use the injected image
    if payload == "IMAGE_PAYLOAD":
        payload = CURRENT_IMAGE_CONTEXT.get("payload", "")
        if not payload:
            return "Error: No image found in current context."
            
    print(f"Local Tool: HLD/LLD Input Agent called with payload size: {len(str(payload))}")
    
    # Initialize Bedrock client
    try:
        bedrock_client = boto3.client('bedrock-runtime', region_name=os.getenv("AWS_DEFAULT_REGION", "us-east-1"))
    except Exception as e:
        return f"Error initializing AWS Bedrock client: {str(e)}"
        
    try:
        # Assign payload to image_data
        image_data = payload
        image_format = "png" # Default
        
        # Ensure image_data is bytes for Nova
        if isinstance(image_data, str):
            try:
                # Analyze header if present to get format
                # Also check magic bytes of base64
                if "image/jpeg" in image_data or "image/jpg" in image_data or image_data.strip().startswith("/9j/"):
                    image_format = "jpeg"
                elif "image/png" in image_data:
                    image_format = "png"
                
                # If it still has header like "data:image/png;base64,", strip it
                if "," in image_data:
                    image_data = image_data.split(",")[1]
                image_bytes = base64.b64decode(image_data)
            except Exception as e:
                return f"Error decoding base64 image: {str(e)}"
        else:
            image_bytes = image_data
            
        print(f"Processing image ({image_format}) with Amazon Nova Vision...")
        
        nova_request = {
            "modelId": "us.amazon.nova-pro-v1:0",
            "contentType": "application/json",
            "accept": "application/json",
            "body": json.dumps({
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "text": """Analyze this High Level Design (HLD) or Low Level Design (LLD) architecture diagram. 
                                Extract and identify:
                                1. System components and their relationships
                                2. AWS Cloud equivalent services (migrating from on-prem)
                                3. Security considerations visible
                                4. Scalability and performance aspects
                                
                                Provide a detailed technical analysis suitable for cloud migration planning."""
                            },
                            {
                                "image": {
                                    "format": image_format, 
                                    "source": {
                                        # ACTUALLY: Nova expects 'bytes': <base64_string>
                                        "bytes": base64.b64encode(image_bytes).decode('utf-8')
                                    }
                                }
                            }
                        ]
                    }
                ],
                "inferenceConfig": {
                    "max_new_tokens": 2000,
                    "temperature": 0.1
                }
            })
        }

        # Call Nova Vision
        nova_response = bedrock_client.invoke_model(**nova_request)
        nova_result = json.loads(nova_response['body'].read())
        vision_analysis = nova_result['output']['message']['content'][0]['text']
        
        print("✅ Nova Vision analysis completed")
        return vision_analysis
        
    except Exception as e:
        logger.error(f"Error in HLD/LLD analysis: {str(e)}")
        return f"Error analyzing architecture diagram: {str(e)}"


# --- Initialize Agent with HYBRID Tools ---

import requests
from strands import tool
    
# --- Remote Gateway Tool Helper ---
def invoke_gateway_tool(tool_name, payload):
    """
    Invokes the 'gateway_tools_lambda' function directly via Boto3.
    This bypasses Protocol/Gateway issues while preserving the Serverless architecture.
    """
    import json
    
    # Use the environment variable injected by provision_serverless.py
    function_name = os.getenv("TOOLS_LAMBDA_NAME", "migration-agent-serverless-tools") 
    
    # Construct Payload matching what gateway_tools_lambda.py expects
    lambda_payload = {
        "tool_name": tool_name,
        # The lambda expects flattened arguments or 'payload' depending on implementation
        # Looking at gateway_tools_lambda.py:
        # tool_name = event.get('tool_name')
        # ...
        # elif tool_name == 'cost_assistant': service = event.get('payload') or event.get('service')
    }
    
    if isinstance(payload, dict):
        lambda_payload.update(payload)
    elif isinstance(payload, str):
        lambda_payload['payload'] = payload

    print(f"DEBUG: Invoking Lambda {function_name} with: {json.dumps(lambda_payload)}")

    try:
        client = boto3.client('lambda', region_name=os.getenv("AWS_DEFAULT_REGION", "us-east-1"))
        
        response = client.invoke(
            FunctionName=function_name,
            InvocationType='RequestResponse',
            Payload=json.dumps(lambda_payload)
        )
        
        # Parse Response
        response_payload = response['Payload'].read()
        response_data = json.loads(response_payload)
        
        # Check for Function Error
        if 'FunctionError' in response:
            logger.error(f"Lambda Error: {response_data}")
            return f"Tool Execution Failed: {response_data}"
            
        # The Lambda returns { "statusCode": 200, "body": ... }
        if 'body' in response_data:
            return response_data['body']
        return str(response_data)
        
    except Exception as e:
        logger.error(f"Failed to invoke Lambda tool {tool_name}: {e}")
        return f"Error invoking Lambda: {str(e)}"

# --- Local Diagram Generation Tool ---
from pathlib import Path
from uuid import uuid4
from mcp import StdioServerParameters, stdio_client

# Directory for storing generated diagrams
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DIAGRAM_OUTPUT_DIR = Path(os.path.join(SCRIPT_DIR, "generated-diagrams"))
DIAGRAM_OUTPUT_DIR.mkdir(exist_ok=True)

# Log S3 bucket config at startup so it's visible in ECS/supervisord logs
logger.info(f"[Config] DIAGRAM_BUCKET_NAME = {os.getenv('DIAGRAM_BUCKET_NAME', '<not set — will use local storage>')}")

def _extract_mermaid_code(text: str) -> str:
    if not text:
        return ""

    code_match = re.search(r"```(?:mermaid)?\s*(.*?)```", text, flags=re.IGNORECASE | re.DOTALL)
    code = code_match.group(1).strip() if code_match else text.strip()
    code = "\n".join(line.strip() for line in code.splitlines() if line.strip())
    if not code:
        return ""
    if not code.lower().startswith(("graph ", "flowchart ")):
        code = "flowchart LR\n" + code
    return _sanitize_mermaid_code(code)

def _sanitize_mermaid_code(code: str) -> str:
    """
    Best-effort cleanup for Nova-generated Mermaid to avoid parser errors.
    """
    lines = [line.strip() for line in code.splitlines() if line.strip()]
    if not lines:
        return ""

    normalized = []
    has_flow_header = False

    for raw_line in lines:
        line = raw_line.encode("ascii", errors="ignore").decode("ascii")
        line = line.replace("\t", " ")
        line = re.sub(r"\s{2,}", " ", line).strip()

        # Remove accidental markdown fences if present.
        if line.startswith("```"):
            continue

        # Keep only one explicit graph header.
        if line.lower().startswith(("flowchart ", "graph ")):
            if not has_flow_header:
                normalized.append("flowchart LR")
                has_flow_header = True
            continue

        # Split accidentally concatenated node declarations like:
        # EC2_1[Web 1] EC2_2[Web 2]
        line = re.sub(
            r"(\[[^\]]*\]|\([^)]+\)|\{[^}]+\})\s+([A-Za-z_][A-Za-z0-9_]*)\s*(?=\[|\(|\{)",
            r"\1\n\2",
            line,
        )
        # Split accidentally concatenated edge statements like:
        # DB["Amazon RDS"]APP --> OBJ["Amazon S3"]
        line = re.sub(
            r"(\[[^\]]*\]|\([^)]+\)|\{[^}]+\}|\"[^\"]*\")\s*([A-Za-z_][A-Za-z0-9_]*\s*(?:-->|-\.->|==>))",
            r"\1\n\2",
            line,
        )

        for segment in [seg.strip() for seg in line.split("\n") if seg.strip()]:
            segment = segment.encode("ascii", errors="ignore").decode("ascii")

            # Normalize node IDs in declarations: avoid dashes/spaces.
            segment = re.sub(
                r"^([A-Za-z_][A-Za-z0-9 _-]*)(\s*(?:\[|\(|\{))",
                lambda m: re.sub(r"[^A-Za-z0-9_]", "_", m.group(1)) + m.group(2),
                segment,
            )

            # Quote labels inside square brackets to avoid parser issues with symbols.
            segment = re.sub(
                r"([A-Za-z_][A-Za-z0-9_]*)\[(.*?)\]",
                lambda m: f'{m.group(1)}["{m.group(2).replace(chr(34), chr(39))}"]',
                segment,
            )

            normalized.append(segment)

    if not has_flow_header:
        normalized.insert(0, "flowchart LR")

    cleaned = "\n".join(normalized).strip()
    cleaned = cleaned.encode("ascii", errors="ignore").decode("ascii")

    # Reject known bad concatenations and broken/incomplete edge endings.
    if re.search(r"(\[[^\]]*\]|\([^)]+\)|\{[^}]+\}|\"[^\"]*\")\s*[A-Za-z_][A-Za-z0-9_]*\s*(?:-->|-\.->|==>)", cleaned):
        return ""
    if re.search(r"(?:-->|-\.->|==>)\s*$", cleaned, flags=re.MULTILINE):
        return ""
    if re.search(r"(?:--|==|-\.->|->)\s*$", cleaned, flags=re.MULTILINE):
        return ""

    # Hard validation heuristics: reject clearly malformed structures.
    malformed_pattern = r"\[[^\]]*\]\s+[A-Za-z_][A-Za-z0-9_]*(?:\[|\(|\{)"
    if re.search(malformed_pattern, cleaned):
        return ""

    # Ensure this is a connected graph, not a loose list of nodes.
    if "-->" not in cleaned and "-.->" not in cleaned and "==>" not in cleaned:
        return ""

    edge_pattern = re.compile(
        r'^[A-Za-z_][A-Za-z0-9_]*(?:\["[^"]*"\]|\([^)]+\)|\{[^}]+\})?\s*'
        r'(?:-->|-\.->|==>)\s*'
        r'[A-Za-z_][A-Za-z0-9_]*(?:\["[^"]*"\]|\([^)]+\)|\{[^}]+\})?$'
    )
    node_pattern = re.compile(
        r'^[A-Za-z_][A-Za-z0-9_]*(?:\["[^"]*"\]|\([^)]+\)|\{[^}]+\})$'
    )

    for line in cleaned.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.lower().startswith("flowchart "):
            continue
        if line.startswith("%%"):
            continue
        if re.search(r"[^\x20-\x7E]", line):
            return ""
        if not edge_pattern.match(line) and not node_pattern.match(line):
            return ""

    return cleaned

def _default_mermaid_template() -> str:
    return (
        "flowchart LR\n"
        'User["Users"] --> DNS["Route 53"]\n'
        'DNS --> ALB["Application Load Balancer"]\n'
        'ALB --> APP["AWS Compute (ECS or Lambda)"]\n'
        'APP --> DB["Amazon RDS"]\n'
        'APP --> OBJ["Amazon S3"]\n'
        'APP --> OBS["CloudWatch"]\n'
    )

_CANVAS_PROMPT_TEMPLATE = """You are an AWS Solutions Architect. Write a detailed image generation prompt for an AWS architecture diagram.

The prompt will be sent to an AI image generator. It must describe a clean, professional, white-background AWS architecture diagram with labeled boxes for each AWS service, arrows showing data flow, and grouped sections for VPC/subnets/clusters.

Include ALL of the following in the prompt:
- Every AWS service mentioned in the request, with its official name label
- Directional arrows showing the flow between services
- Grouped sections (e.g. "VPC", "Public Subnet", "Private Subnet", "On-Premises")
- AWS service icon colors (orange for compute, blue for networking, purple for database, green for storage)
- Clean white background, technical diagram style, no people, no decorative elements

User request:
{payload}

Return ONLY the image generation prompt text, no explanation."""


def _generate_diagrams_fallback(payload: str, failure_reason: str = "") -> str:
    """
    Uses Nova Pro to write an image prompt, then Nova Canvas to generate the diagram PNG directly.
    Falls back to matplotlib renderer if Canvas fails.
    """
    bedrock_client = boto3.client(
        "bedrock-runtime",
        region_name=os.getenv("AWS_DEFAULT_REGION", "us-east-1"),
    )

    # Step 1: Nova Pro writes a detailed image prompt
    image_prompt = ""
    try:
        resp = bedrock_client.invoke_model(
            modelId="us.amazon.nova-pro-v1:0",
            contentType="application/json",
            accept="application/json",
            body=json.dumps({
                "messages": [{"role": "user", "content": [{"text": _CANVAS_PROMPT_TEMPLATE.format(payload=payload)}]}],
                "inferenceConfig": {"max_new_tokens": 600, "temperature": 0.2},
            }),
        )
        result = json.loads(resp["body"].read())
        image_prompt = result.get("output", {}).get("message", {}).get("content", [{}])[0].get("text", "").strip()
        logger.info(f"[canvas] Image prompt generated ({len(image_prompt)} chars)")
    except Exception as e:
        logger.warning(f"[canvas] Nova Pro prompt generation failed: {e}")
        image_prompt = f"Professional AWS architecture diagram showing: {payload}. White background, labeled service boxes with arrows, technical style."

    # Step 2: Nova Canvas generates the image
    img_url = None
    try:
        canvas_resp = bedrock_client.invoke_model(
            modelId="amazon.nova-canvas-v1:0",
            contentType="application/json",
            accept="application/json",
            body=json.dumps({
                "taskType": "TEXT_IMAGE",
                "textToImageParams": {
                    "text": image_prompt,
                    "negativeText": "people, faces, hands, text errors, blurry, low quality, decorative borders, 3D rendering",
                },
                "imageGenerationConfig": {
                    "numberOfImages": 1,
                    "width": 1280,
                    "height": 768,
                    "quality": "standard",
                    "cfgScale": 8.0,
                },
            }),
        )
        canvas_result = json.loads(canvas_resp["body"].read())
        images = canvas_result.get("images", [])
        if images:
            image_bytes = base64.b64decode(images[0])
            img_url = _save_diagram_image(image_bytes, "png")
            logger.info(f"[canvas] Nova Canvas diagram saved: {img_url}")
        else:
            logger.warning(f"[canvas] No images returned. Error: {canvas_result.get('error')}")
    except Exception as e:
        logger.warning(f"[canvas] Nova Canvas generation failed: {e}")

    if img_url:
        return (
            f"### Generated Architecture Diagram:\n\n"
            f"![Architecture Diagram]({img_url})\n"
        )

    # Fallback: matplotlib renderer
    logger.warning("[canvas] Nova Canvas failed — falling back to matplotlib renderer")
    return _render_with_matplotlib(payload, failure_reason)


def _render_with_matplotlib(payload: str, failure_reason: str = "") -> str:
    """Renders architecture diagram using matplotlib as last resort before mermaid."""
    bedrock_client = boto3.client(
        "bedrock-runtime",
        region_name=os.getenv("AWS_DEFAULT_REGION", "us-east-1"),
    )

    _MATPLOTLIB_PROMPT = """Extract the AWS architecture from the user request and return ONLY valid JSON:
{
  "title": "Architecture title",
  "clusters": [{"name": "Cluster label", "services": ["Service1", "Service2"]}],
  "connections": [["SourceService", "TargetService"]]
}
Use real AWS service names. Include ALL services. No explanation.

User request:
""" + payload

    arch_json = None
    try:
        resp = bedrock_client.invoke_model(
            modelId="us.amazon.nova-pro-v1:0",
            contentType="application/json",
            accept="application/json",
            body=json.dumps({
                "messages": [{"role": "user", "content": [{"text": _MATPLOTLIB_PROMPT}]}],
                "inferenceConfig": {"max_new_tokens": 800, "temperature": 0.1},
            }),
        )
        raw = json.loads(resp["body"].read())
        text = raw.get("output", {}).get("message", {}).get("content", [{}])[0].get("text", "")
        json_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        json_str = json_match.group(1) if json_match else text.strip()
        arch_json = json.loads(json_str)
    except Exception as e:
        logger.warning(f"[matplotlib] JSON extraction failed: {e}")

    if arch_json:
        try:
            image_bytes = _render_architecture_png(
                title=arch_json.get("title", "AWS Architecture"),
                clusters=arch_json.get("clusters", []),
                connections=arch_json.get("connections", []),
            )
            img_url = _save_diagram_image(image_bytes, "png")
            if img_url:
                return f"### Generated Architecture Diagram:\n\n![Architecture Diagram]({img_url})\n"
        except Exception as e:
            logger.warning(f"[matplotlib] Render failed: {e}")

    logger.warning("[matplotlib] Falling back to mermaid.ink")
    return _generate_mermaid_last_resort(payload, failure_reason)


# AWS service color map for matplotlib renderer
_AWS_COLORS = {
    "default":    {"bg": "#E8F4FD", "border": "#1A73E8", "text": "#0D47A1"},
    "compute":    {"bg": "#FFF3E0", "border": "#FF6D00", "text": "#E65100"},
    "network":    {"bg": "#E8F5E9", "border": "#2E7D32", "text": "#1B5E20"},
    "database":   {"bg": "#F3E5F5", "border": "#6A1B9A", "text": "#4A148C"},
    "storage":    {"bg": "#FFF8E1", "border": "#F57F17", "text": "#E65100"},
    "security":   {"bg": "#FCE4EC", "border": "#C62828", "text": "#B71C1C"},
    "management": {"bg": "#E0F2F1", "border": "#00695C", "text": "#004D40"},
}
_SERVICE_CATEGORY = {
    "EC2": "compute", "ECS": "compute", "ECS Fargate": "compute", "Lambda": "compute",
    "Fargate": "compute",
    "ALB": "network", "NLB": "network", "Route 53": "network", "CloudFront": "network",
    "API Gateway": "network", "NAT Gateway": "network", "Transit Gateway": "network",
    "VPC Endpoint": "network", "Network Firewall": "network", "WAF": "network",
    "IGW": "network", "Internet Gateway": "network",
    "RDS": "database", "Aurora": "database", "DynamoDB": "database",
    "ElastiCache": "database", "Redshift": "database",
    "S3": "storage", "EFS": "storage", "EBS": "storage",
    "Cognito": "security", "IAM": "security", "KMS": "security",
    "Secrets Manager": "security", "Shield": "security",
    "CloudWatch": "management", "CloudTrail": "management",
    "SQS": "management", "SNS": "management",
}


def _render_architecture_png(title: str, clusters: list, connections: list) -> bytes:
    """Render architecture diagram using matplotlib."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import FancyBboxPatch
    import io

    all_services = {}
    cluster_colors = ["#E3F2FD", "#E8F5E9", "#FFF3E0", "#F3E5F5", "#E0F2F1", "#FFF8E1", "#FCE4EC", "#EDE7F6"]
    x_cursor = 0.5
    cluster_boxes = []
    for ci, cluster in enumerate(clusters):
        services = cluster.get("services", [])
        y_start = len(services) * 1.4 + 0.8
        for si, svc in enumerate(services):
            all_services[svc] = (x_cursor, y_start - si * 1.4 - 0.7)
        cluster_boxes.append({"name": cluster["name"], "x": x_cursor,
                               "y_top": y_start + 0.3, "y_bot": y_start - len(services) * 1.4 + 0.1,
                               "color": cluster_colors[ci % len(cluster_colors)]})
        x_cursor += 2.2

    total_w = max(x_cursor + 0.5, 8)
    total_h = max(max((len(c.get("services", [])) for c in clusters), default=3) * 1.4 + 2.0, 6)
    fig, ax = plt.subplots(figsize=(max(total_w * 0.9, 10), max(total_h * 0.75, 6)))
    ax.set_xlim(-0.5, total_w); ax.set_ylim(-0.5, total_h + 0.5); ax.axis("off")
    fig.patch.set_facecolor("#F8FAFC"); ax.set_facecolor("#F8FAFC")
    ax.text(total_w / 2, total_h + 0.1, title, ha="center", va="top", fontsize=14, fontweight="bold", color="#1A237E")

    for cb in cluster_boxes:
        ax.add_patch(FancyBboxPatch((cb["x"] - 0.9, cb["y_bot"] - 0.2), 1.8, cb["y_top"] - cb["y_bot"] + 0.2,
                                    boxstyle="round,pad=0.1", linewidth=1.5, edgecolor="#90A4AE",
                                    facecolor=cb["color"], alpha=0.6, zorder=1))
        ax.text(cb["x"], cb["y_top"] + 0.05, cb["name"], ha="center", va="bottom",
                fontsize=7.5, color="#37474F", fontweight="bold", style="italic")

    for src, dst in connections:
        if src in all_services and dst in all_services:
            x1, y1 = all_services[src]; x2, y2 = all_services[dst]
            ax.annotate("", xy=(x2, y2), xytext=(x1, y1),
                        arrowprops=dict(arrowstyle="-|>", color="#546E7A", lw=1.4,
                                        connectionstyle="arc3,rad=0.08"), zorder=2)

    for svc, (x, y) in all_services.items():
        colors = _AWS_COLORS.get(_SERVICE_CATEGORY.get(svc, "default"), _AWS_COLORS["default"])
        ax.add_patch(FancyBboxPatch((x - 0.75, y - 0.38), 1.5, 0.76, boxstyle="round,pad=0.08",
                                    linewidth=1.8, edgecolor=colors["border"], facecolor=colors["bg"], zorder=3))
        label = svc if len(svc) <= 16 else svc.replace(" ", "\n", 1)
        ax.text(x, y, label, ha="center", va="center", fontsize=7.5, fontweight="bold",
                color=colors["text"], zorder=4, multialignment="center")

    plt.tight_layout(pad=0.5)
    buf = io.BytesIO()
    plt.savefig(buf, format="png", dpi=150, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    buf.seek(0)
    return buf.read()


def _save_diagram_image(image_bytes: bytes, ext: str = "png") -> str | None:
    """Saves image bytes to S3 (primary) or local static dir (fallback), returns URL."""
    fname = f"diagram_{uuid4().hex[:8]}_{int(time.time())}.{ext}"
    bucket_name = os.getenv("DIAGRAM_BUCKET_NAME")

    if bucket_name:
        try:
            s3_client = boto3.client("s3")
            s3_key = f"diagrams/{fname}"
            s3_client.put_object(
                Bucket=bucket_name,
                Key=s3_key,
                Body=image_bytes,
                ContentType=f"image/{ext}",
            )
            url = s3_client.generate_presigned_url(
                "get_object",
                Params={"Bucket": bucket_name, "Key": s3_key},
                ExpiresIn=3600,
            )
            logger.info(f"[S3] Diagram uploaded: s3://{bucket_name}/{s3_key}")
            return url
        except Exception as e:
            logger.error(f"[S3] Upload failed for bucket '{bucket_name}': {e}")
            # Fall through to local storage
    else:
        logger.warning("[S3] DIAGRAM_BUCKET_NAME not set — falling back to local storage.")

    local_candidates = [
        Path(SCRIPT_DIR) / "static" / "diagrams",
        Path(SCRIPT_DIR).parent / "frontend" / "public" / "diagrams",
    ]
    for candidate in local_candidates:
        if candidate.parent.exists():
            candidate.mkdir(parents=True, exist_ok=True)
            dest = candidate / fname
            with open(dest, "wb") as f:
                f.write(image_bytes)
            logger.info(f"[Local] Diagram saved: {dest}")
            return f"/diagrams/{fname}"

    logger.error("[Save] No valid storage location found for diagram.")
    return None


def _generate_mermaid_last_resort(payload: str, failure_reason: str = "") -> str:
    """Absolute last resort: mermaid.ink hosted image."""
    mermaid_code = _default_mermaid_template()
    encoded = base64.urlsafe_b64encode(mermaid_code.encode("utf-8")).decode("utf-8")
    mermaid_image_url = f"https://mermaid.ink/img/{encoded}"
    reason_prefix = f"_Diagram renderer unavailable ({failure_reason})._\n\n" if failure_reason else ""
    return (
        f"{reason_prefix}"
        f"### Generated Architecture Diagram:\n\n"
        f"![Architecture Diagram]({mermaid_image_url})\n"
    )

@tool
def arch_diag_assistant(payload):
    """
    A Senior AWS Solutions Architect specializing in architecture diagrams.
    Creates PNG architecture diagrams using the diagrams library with real AWS service icons.
    """
    print(f"arch_diag_assistant called with payload: {payload}")
    return _generate_diagrams_fallback(payload)

# --- Define Remote Tools Stubs ---
# These look local to the Agent, but execute remotely.

@tool
def cost_assistant(service_name: str):
    """
    Estimates cost for AWS services (e.g., 'EC2', 'RDS', 'Lambda').
    Returns pricing information.
    """
    # Schema expects 'payload'
    return invoke_gateway_tool("cost_assistant", {"payload": service_name})

@tool
def aws_docs_assistant(query: str):
    """
    Searches AWS Documentation for best practices, guides, and architectural patterns.
    """
    # Schema expects 'payload'
    return invoke_gateway_tool("aws_docs_assistant", {"payload": query})

@tool
def vpc_subnet_calculator(cidr_block: str):
    """
    Calculates optimal VPC subnet divisions given a CIDR block (e.g. '10.0.0.0/16').
    Returns a text table of subnets.
    """
    return invoke_gateway_tool("vpc_subnet_calculator", {"cidr": cidr_block})


# --- Agent Definition Wrapper ---

migration_system_prompt = """You are an expert AWS Migration Specialist and Cloud Architect.
Your goal is to guide users through the complex process of migrating on-premises workloads to AWS with confidence and clarity.

### Core Responsibilities
1.  **Analyze & Assess**: Deeply understand the user's existing infrastructure. If an image is provided, use the `hld_lld_input_agent` to extract details.
2.  **Consult & Clarify**: Do NOT just give a generic answer. Proactively ask for technical preferences (e.g., Serverless vs Containers, Managed vs Self-hosted) to tailor the solution.
3.  **Recommend & Plan**: Suggest appropriate migration strategies (Re-host, Re-platform, Re-factor) and AWS services.
4.  **Cost & Best Practices**: Always consider TCO and the AWS Well-Architected Framework. Use `cost_assistant` for estimates.
5.  **IP Conservation**: The user is operating in a **Private IPv4 Resource Crunch**. ALWAYS recommend the **minimal viable** subnet size (e.g., /28 for small workloads). Use `vpc_subnet_calculator`.
6.  **Official Documentation**: Use `aws_docs_assistant` to verify latest limits and features.

### Operational Rules
*   **Step-by-Step Approach**: Break complex migrations into logical phases.
*   **Diagram Generation**: Use the `arch_diag_assistant` to create professional diagrams.
*   **Diagram Edits**: If the user asks to modify/update/redraw/enhance an architecture diagram (including adding AWS icons), you **MUST** call `arch_diag_assistant` and return a diagram image link.
*   **CRITICAL - Image Links**: If a tool (like `arch_diag_assistant`) returns a Markdown Image Link (e.g., `![Architecture Diagram](/diagrams/...)`), you **MUST** include this link **VERBATIM** in your final response. **Do NOT remove it**. It is required for the user to see the diagram.
*   **Tone**: Professional, encouraging, and technically precise.

### Hybrid Toolset
You have access to a suite of tools, some running on a remote Gateway and some locally:
1.  **Gateway Tools**: `cost_assistant`, `aws_docs_assistant`, `vpc_subnet_calculator` (Remote Lambda).
2.  **Local Tools**: `hld_lld_input_agent` (Image Analysis), `arch_diag_assistant` (Diagram Generation).

Use them seamlessly to assist the user.
"""

def _is_diagram_or_image_request(user_text: str) -> bool:
    text = (user_text or "").lower()
    diagram_keywords = [
        "diagram",
        "draw",
        "redraw",
        "modify diagram",
        "update diagram",
        "generate image",
        "architecture image",
        "architecture diagram",
        "flowchart",
        "visual",
        "aws icon",
        "icons",
        "png",
        "hld",
        "lld",
    ]
    return any(keyword in text for keyword in diagram_keywords)

def _is_diagram_generation_request(user_text: str) -> bool:
    text = (user_text or "").lower()
    generation_words = [
        "generate", "create", "draw", "build", "produce", "show",
        "modify", "update", "redraw", "revise", "enhance", "add", "convert", "make", "give me"
    ]
    diagram_words = [
        "diagram", "architecture", "image", "visual", "flowchart",
        "png", "icon", "icons", "architecture diagram", "aws diagram"
    ]
    return any(word in text for word in generation_words) and any(word in text for word in diagram_words)

def _contains_markdown_image(text: str) -> bool:
    return bool(re.search(r"!\[[^\]]*\]\([^)]+\)", text or ""))

def _looks_like_diagram_refusal(text: str) -> bool:
    response = (text or "").lower()
    refusal_patterns = [
        "cannot directly modify",
        "can't directly modify",
        "cannot modify the diagram",
        "i cannot directly",
        "i can provide guidance",
        "unable to generate",
        "unable to create a diagram",
    ]
    return any(pattern in response for pattern in refusal_patterns)

def invoke_local_migration_agent(prompt_text: str) -> str:
    """Run local Strands orchestration with both remote and local tools enabled."""
    from strands.agent.conversation_manager import SlidingWindowConversationManager
    from strands.types.exceptions import MaxTokensReachedException, ContextWindowOverflowException

    all_tools = [
        cost_assistant,
        aws_docs_assistant,
        vpc_subnet_calculator,
        hld_lld_input_agent,
        arch_diag_assistant
    ]
    migration_agent = Agent(
        model=BedrockModel(
            model_id="us.amazon.nova-pro-v1:0",
            max_tokens=4096,
        ),
        system_prompt=migration_system_prompt,
        tools=all_tools,
        conversation_manager=SlidingWindowConversationManager(window_size=10),
    )

    try:
        response = migration_agent(prompt_text)
    except (MaxTokensReachedException, ContextWindowOverflowException):
        logger.warning("Context window overflow — retrying with a fresh agent (no history).")
        fresh_agent = Agent(
            model=BedrockModel(
                model_id="us.amazon.nova-pro-v1:0",
                max_tokens=4096,
            ),
            system_prompt=migration_system_prompt,
            tools=all_tools,
        )
        response = fresh_agent(prompt_text)

    content = response.message.get("content", []) if getattr(response, "message", None) else []
    text_parts = []
    for part in content:
        if isinstance(part, dict) and part.get("text"):
            text_parts.append(part["text"])
        elif isinstance(part, str):
            text_parts.append(part)

    extracted = "\n".join(text_parts).strip()
    return extracted or str(response)

def invoke_bedrock_agent_runtime(prompt_text, session_id):
    """
    Invoke managed Bedrock Agent Runtime using agent and alias IDs from env.
    Returns response text, or None if Bedrock agent env is not configured.
    """
    agent_id = (os.getenv("BEDROCK_AGENT_ID") or "").strip()
    agent_alias_id = (os.getenv("BEDROCK_AGENT_ALIAS_ID") or "").strip()
    region = os.getenv("AWS_DEFAULT_REGION", "us-east-1")

    if not agent_id or not agent_alias_id:
        logger.info("BEDROCK_AGENT_ID / BEDROCK_AGENT_ALIAS_ID not set; skipping managed Bedrock Agent invocation.")
        return None

    logger.info(f"Invoking Bedrock Agent Runtime: agent_id={agent_id}, alias_id={agent_alias_id}, region={region}")
    runtime = boto3.client("bedrock-agent-runtime", region_name=region)
    try:
        response = runtime.invoke_agent(
            agentId=agent_id,
            agentAliasId=agent_alias_id,
            sessionId=session_id,
            inputText=prompt_text
        )
    except ClientError as e:
        logger.error(f"InvokeAgent API call failed: {e}")
        return None

    completion_text = []
    for event in response.get("completion", []):
        chunk = event.get("chunk")
        if chunk and "bytes" in chunk:
            raw = chunk["bytes"]
            if isinstance(raw, (bytes, bytearray)):
                completion_text.append(raw.decode("utf-8", errors="ignore"))
            else:
                completion_text.append(str(raw))
            continue

        # Surface Bedrock event-stream exceptions.
        for key in [
            "accessDeniedException",
            "badGatewayException",
            "conflictException",
            "dependencyFailedException",
            "internalServerException",
            "modelNotReadyException",
            "resourceNotFoundException",
            "serviceQuotaExceededException",
            "throttlingException",
            "validationException"
        ]:
            if key in event:
                logger.error(f"InvokeAgent stream error [{key}]: {event.get(key)}")
                return None

    final_text = "".join(completion_text).strip()
    if final_text:
        return final_text

    # If control was returned by an action group, surface that state for debugging.
    if "returnControl" in response:
        return f"Bedrock agent returned control: {json.dumps(response.get('returnControl'))}"

    return "No response content returned by Bedrock Agent Runtime."

@app.entrypoint
async def migration_assistant(payload):
    """
    An AWS Migration Specialist backed by AgentCore Gateway tools.
    """
    if isinstance(payload, str):
        user_input = payload
        user_id = "unknown"
        context = {}
    else:
        user_input = payload.get("input") or payload.get("prompt")
        user_id = payload.get("user_id", "unknown")
        context = payload.get("context", {}) 
    user_input = user_input or ""
    import traceback
    
    # Session Management
    session_id = context.get("session_id") or f"session_{user_id}_{int(time.time())}"
    # session_memory_provider removed

    print(f"User ID: {user_id}")
    print(f"Session ID: {session_id}")
    
    print(f"Session ID: {session_id}")
    
    # 1. Retrieve History
    past_memories = get_memory(session_id)
    # Save original input before any modification
    original_user_input = user_input

    if past_memories:
        print(f"📄 Retrieved {len(past_memories)} past messages.")
        # Build a concise context summary (last 3 exchanges max) to avoid token bloat
        recent = past_memories[-6:]  # 3 user + 3 assistant turns
        history_lines = []
        for m in recent:
            role_label = "User" if m["role"] == "user" else "Assistant"
            # Truncate long assistant responses (e.g. diagrams) to avoid token explosion
            content_snippet = m["content"][:400] + "..." if len(m["content"]) > 400 else m["content"]
            history_lines.append(f"{role_label}: {content_snippet}")
        history_str = "\n".join(history_lines)
        user_input = f"[Recent conversation context]\n{history_str}\n\n[Current message]\n{user_input}"
        
    
    # Context Handling for Image
    image_data = None
    if isinstance(payload, dict):
       image_data = payload.get("image_base64")
    
    # ... Image handling ...
    if image_data:
        # Store in global context for the tool to access
        CURRENT_IMAGE_CONTEXT["payload"] = image_data
        user_input += f"\n\n[System Notification]: The user has uploaded an image (Base64). Pass 'IMAGE_PAYLOAD' to 'hld_lld_input_agent' to analyze it."
    else:
        CURRENT_IMAGE_CONTEXT["payload"] = None

    needs_local_tools = bool(image_data) or _is_diagram_or_image_request(original_user_input)
    wants_diagram_generation = _is_diagram_generation_request(original_user_input)

    try:
        loop = asyncio.get_running_loop()
        response_text = None

        # For diagram generation requests, call arch_diag_assistant directly.
        # Don't let the agent decide — it consistently picks the wrong tool.
        if wants_diagram_generation:
            logger.info("Diagram generation request detected — invoking arch_diag_assistant directly.")
            response_text = await loop.run_in_executor(None, arch_diag_assistant, original_user_input)

        elif needs_local_tools:
            # Image analysis (HLD/LLD upload) — needs local agent
            logger.info("Routing request to local Strands orchestration for image workflow.")
            response_text = await loop.run_in_executor(None, invoke_local_migration_agent, user_input)

        else:
            # Primary path: managed Bedrock Agent Runtime (created by Terraform)
            response_text = await loop.run_in_executor(None, invoke_bedrock_agent_runtime, user_input, session_id)

            # Fallback path: local Strands orchestration if managed agent is unavailable
            if not response_text:
                logger.warning("Falling back to local Strands agent execution (Bedrock Agent Runtime unavailable).")
                response_text = await loop.run_in_executor(None, invoke_local_migration_agent, user_input)

        # If diagram was requested but no image came back, force it directly
        if wants_diagram_generation and not _contains_markdown_image(response_text or ""):
            logger.warning("No image in diagram response — forcing arch_diag_assistant directly.")
            response_text = await loop.run_in_executor(None, arch_diag_assistant, original_user_input)

        # Save Interaction to Memory
        add_to_memory(session_id, "user", original_user_input)
        add_to_memory(session_id, "assistant", response_text or "")

        return response_text

    except Exception as e:
        from strands.types.exceptions import MaxTokensReachedException, ContextWindowOverflowException
        if isinstance(e, (MaxTokensReachedException, ContextWindowOverflowException)):
            logger.error("Max tokens reached at entrypoint level.")
            return (
                "I've reached the context limit for this conversation. "
                "Please start a new session to continue."
            )
        logger.error("CRITICAL ERROR IN AGENT:")
        traceback.print_exc()
        with open("error.log", "w") as f:
            f.write(traceback.format_exc())
        return f"Server Error (Check Terminal Logs): {str(e)}"








if __name__ == "__main__":
    _bucket = os.getenv("DIAGRAM_BUCKET_NAME", "<not set>")
    print(f"\n🚀 Migration Agent Server is RUNNING on internal port 8081")
    print(f"📦 Diagram S3 bucket: {_bucket}")
    uvicorn.run(app, host="0.0.0.0", port=8081)

