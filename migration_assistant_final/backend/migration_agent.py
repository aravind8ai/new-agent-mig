import os
import boto3
import asyncio
import time
import logging
import json
import re
import shutil
import sys
from botocore.exceptions import ClientError
from dotenv import load_dotenv
# Load environment variables
load_dotenv()

from strands import Agent
from strands.tools.mcp import MCPClient
from mcp.client.streamable_http import streamablehttp_client
from bedrock_agentcore.runtime import BedrockAgentCoreApp
import uvicorn
from strands.models import BedrockModel
from bedrock_agentcore.memory import MemoryClient
from strands.hooks import AgentInitializedEvent, HookProvider, MessageAddedEvent

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
# Point to frontend public dir so they are accessible? 
# or just a local folder and we serve it. For now local folder.
DIAGRAM_OUTPUT_DIR = Path(os.path.join(SCRIPT_DIR, "generated-diagrams"))
DIAGRAM_OUTPUT_DIR.mkdir(exist_ok=True)

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

def _generate_mermaid_fallback_diagram(payload, failure_reason="") -> str:
    """
    Fallback path used when MCP/uvx diagram rendering is unavailable.
    Generates Mermaid code with Nova and returns a hosted Mermaid image URL.
    """
    mermaid_code = ""
    try:
        bedrock_client = boto3.client(
            "bedrock-runtime",
            region_name=os.getenv("AWS_DEFAULT_REGION", "us-east-1")
        )
        prompt = f"""
Create Mermaid syntax for an AWS architecture diagram.
Return ONLY Mermaid code. No markdown fences. No explanation.
Use flowchart LR.
Rules:
- One statement per line.
- Never place two node declarations on the same line unless connected by an arrow.
- Use node IDs with letters/numbers/underscores only.
- Prefer labels quoted in square brackets, for example: EC2_1["Web Server 1"].

User request:
{payload}
""".strip()

        response = bedrock_client.invoke_model(
            modelId="us.amazon.nova-pro-v1:0",
            contentType="application/json",
            accept="application/json",
            body=json.dumps(
                {
                    "messages": [
                        {
                            "role": "user",
                            "content": [{"text": prompt}]
                        }
                    ],
                    "inferenceConfig": {"max_new_tokens": 900, "temperature": 0.2}
                }
            ),
        )
        result = json.loads(response["body"].read())
        text = (
            result.get("output", {})
            .get("message", {})
            .get("content", [{}])[0]
            .get("text", "")
        )
        mermaid_code = _extract_mermaid_code(text)
    except Exception as e:
        logger.warning(f"Mermaid fallback generation via Nova failed: {e}")

    if not mermaid_code:
        logger.warning("Generated Mermaid code failed validation. Using default template.")
        mermaid_code = _default_mermaid_template()

    encoded = base64.urlsafe_b64encode(mermaid_code.encode("utf-8")).decode("utf-8")
    mermaid_image_url = f"https://mermaid.ink/img/{encoded}"

    reason_prefix = ""
    if failure_reason:
        reason_prefix = f"Native diagram renderer unavailable ({failure_reason}). Showing Mermaid fallback.\n\n"

    return (
        f"{reason_prefix}"
        f"### Generated Architecture Diagram:\n\n"
        f"![Architecture Diagram]({mermaid_image_url})\n\n"
        "<details><summary>View Mermaid source</summary>\n\n"
        "```mermaid\n"
        f"{mermaid_code}\n"
        "```\n"
        "</details>"
    )

@tool
def arch_diag_assistant(payload):
    """
    A Senior AWS Solutions Architect specializing in architecture diagrams.
    Creates PNG architecture diagrams using AWS Diagram MCP server.
    """
    print(f"arch_diag_assistant called with payload: {payload}")
    try:
        uvx_path = shutil.which("uvx")
        if uvx_path:
            diagram_command = uvx_path
            diagram_args = [
                "--with", "jschema-to-python",
                "awslabs.aws-diagram-mcp-server@latest"
            ]
        else:
            try:
                import uv  # noqa: F401
                diagram_command = sys.executable
                diagram_args = [
                    "-m", "uv", "tool", "run",
                    "--with", "jschema-to-python",
                    "awslabs.aws-diagram-mcp-server@latest"
                ]
            except Exception:
                raise RuntimeError("uvx binary not found in runtime and `uv` module is unavailable")

        diagram_mcp_client = MCPClient(
            lambda: stdio_client(
                StdioServerParameters(
                    command=diagram_command,
                    args=diagram_args
                )
            )
        )
        
        print("Initializing architecture diagram agent...")
        
        with diagram_mcp_client:
            diagram_tools = diagram_mcp_client.list_tools_sync()
            
            agent = Agent(
                model="us.amazon.nova-pro-v1:0",
                tools=diagram_tools,
                system_prompt="""You are a Senior AWS Solutions Architect.
                Create professional AWS architecture diagrams.
                - Use generate_diagram tool ONCE.
                - Follow AWS Well-Architected Framework.
                - Generate only ONE diagram per request.
                """
            )
            
            response = agent(payload)
            
            # Extract Images
            text_parts = []
            saved_images = []
            
            # Cloud Storage Configuration
            bucket_name = os.getenv("DIAGRAM_BUCKET_NAME")
            s3_client = boto3.client('s3') if bucket_name else None
            
            # Local fallback (for /tmp scanning)
            tmp_diagram_dir = Path("/tmp/generated-diagrams")
            if not tmp_diagram_dir.exists(): 
                 tmp_diagram_dir.mkdir(parents=True, exist_ok=True)

            # Local fallback locations:
            # 1) Container runtime: /app/static/diagrams (served by nginx root /app/static)
            # 2) Local dev: ../frontend/public/diagrams (served by Vite static public directory)
            local_diagram_dir = None
            local_candidates = [
                Path(SCRIPT_DIR) / "static" / "diagrams",
                Path(SCRIPT_DIR).parent / "frontend" / "public" / "diagrams",
            ]
            for candidate in local_candidates:
                if candidate.parent.exists():
                    candidate.mkdir(parents=True, exist_ok=True)
                    local_diagram_dir = candidate
                    break

            def save_generated_image(image_bytes, ext="png"):
                fname = f"diagram_{uuid4().hex[:8]}_{int(time.time())}.{ext}"
                
                # 1. Upload to S3 (Priority for Cloud)
                if bucket_name:
                    try:
                        s3_key = f"diagrams/{fname}"
                        s3_client.put_object(
                            Bucket=bucket_name,
                            Key=s3_key,
                            Body=image_bytes,
                            ContentType=f"image/{ext}"
                        )
                        # Generate Presigned URL (valid for 1 hour)
                        url = s3_client.generate_presigned_url(
                            'get_object',
                            Params={'Bucket': bucket_name, 'Key': s3_key},
                            ExpiresIn=3600
                        )
                        print(f"[SUCCESS] Uploaded diagram to s3://{bucket_name}/{s3_key}")
                        return url
                    except Exception as e:
                        print(f"[WARNING] Failed to upload to S3: {e}")
                
                # 2. Local Fallback
                if local_diagram_dir:
                    dest = local_diagram_dir / fname
                    with open(dest, "wb") as f:
                        f.write(image_bytes)
                    print(f"[SUCCESS] Saved diagram locally to {dest}")
                    return f"/diagrams/{fname}"
                
                return None

            for part in response.message.get("content", []):
                if not isinstance(part, dict):
                    continue

                if part.get("type") == "text":
                    text_parts.append(part["text"])
                
                # Handle Base64 Image (if returned)
                b64_data = part.get("data") or part.get("base64_data")
                if b64_data:
                    try:
                        image_bytes = base64.b64decode(b64_data)
                        ext = (part.get("format") or "png").replace(".", "").lower()
                        if "/" in ext:
                            ext = ext.split("/")[-1]
                        url = save_generated_image(image_bytes, ext)
                        if url:
                            saved_images.append(url)
                    except Exception as e:
                        print(f"Failed to process image data: {e}")
            
            # CHECK TMP DIR (Hybrid Fallback)
            if tmp_diagram_dir.exists():
                for tmp_file in tmp_diagram_dir.glob("*.png"):
                    try:
                        with open(tmp_file, "rb") as f:
                            image_bytes = f.read()
                        
                        url = save_generated_image(image_bytes, "png")
                        if url:
                            saved_images.append(url)
                        
                        # Cleanup tmp
                        os.remove(tmp_file) 
                    except Exception as e:
                        print(f"Failed to process tmp file {tmp_file}: {e}")

            result = "\n\n".join(text_parts).strip()
            if saved_images:
                result += "\n\n### Generated Architecture Diagram:\n"
                for img_path in saved_images:
                   result += f"\n![Architecture Diagram]({img_path})\n"
                return result

            raise RuntimeError("Diagram MCP tool completed but did not return any image bytes.")
    except Exception as e:
        logger.warning(f"arch_diag_assistant failed, using Mermaid fallback: {e}")
        return _generate_mermaid_fallback_diagram(payload, str(e))

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
        "generate", "create", "draw", "build", "produce",
        "modify", "update", "redraw", "revise", "enhance", "add", "convert"
    ]
    diagram_words = ["diagram", "architecture", "image", "visual", "flowchart", "png", "icon", "icons"]
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
    all_tools = [
        cost_assistant,
        aws_docs_assistant,
        vpc_subnet_calculator,
        hld_lld_input_agent,
        arch_diag_assistant
    ]
    migration_agent = Agent(
        model="us.amazon.nova-pro-v1:0",
        system_prompt=migration_system_prompt,
        tools=all_tools
    )
    response = migration_agent(prompt_text)

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
    if past_memories:
        history_str = "\n".join([f"{m['role'].upper()}: {m['content']}" for m in past_memories])
        print(f"📄 Retrieved {len(past_memories)} past messages.")
        
        # Save original input for storage later
        original_user_input = user_input
        
        # Prepend context to prompt
        user_input = f"""Earlier Conversation History:
{history_str}

Current User Input:
{user_input}"""
    else:
        original_user_input = user_input
        
    
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

        # Diagram/image tasks require local-only tools, so route these directly.
        if needs_local_tools:
            logger.info("Routing request to local Strands orchestration for diagram/image workflow.")
            response_text = await loop.run_in_executor(None, invoke_local_migration_agent, user_input)
        else:
            # Primary path: managed Bedrock Agent Runtime (created by Terraform)
            response_text = await loop.run_in_executor(None, invoke_bedrock_agent_runtime, user_input, session_id)

            # Fallback path: local Strands orchestration if managed agent is unavailable
            if not response_text:
                logger.warning("Falling back to local Strands agent execution (Bedrock Agent Runtime unavailable).")
                response_text = await loop.run_in_executor(None, invoke_local_migration_agent, user_input)

        # Safety: if a diagram/image request somehow returned no image link, try local toolchain once.
        if wants_diagram_generation and not _contains_markdown_image(response_text):
            logger.warning("No image link detected in response. Re-trying locally to force diagram generation.")
            response_text = await loop.run_in_executor(None, invoke_local_migration_agent, user_input)

        # Hard fallback: if still no image for a diagram generation/edit request, invoke diagram tool directly.
        if needs_local_tools and wants_diagram_generation and not _contains_markdown_image(response_text):
            if _looks_like_diagram_refusal(response_text):
                logger.warning("Diagram refusal detected. Invoking arch_diag_assistant directly.")
            else:
                logger.warning("No image after retries for diagram task. Invoking arch_diag_assistant directly.")
            direct_diagram = await loop.run_in_executor(None, arch_diag_assistant, original_user_input)
            if direct_diagram:
                response_text = direct_diagram
        
        # 2. Save Interaction to Memory
        add_to_memory(session_id, "user", original_user_input)
        add_to_memory(session_id, "assistant", response_text)
        
        return response_text

    except Exception as e:
        logger.error("CRITICAL ERROR IN AGENT:")
        traceback.print_exc() 
        # Write to file for debugging
        with open("error.log", "w") as f:
            f.write(traceback.format_exc())
            
        return f"Server Error (Check Terminal Logs): {str(e)}"








if __name__ == "__main__":
    print("\n🚀 Migration Agent Server is RUNNING on internal port 8081")
    # Run on 8081 so Nginx can proxy to it from 8000
    uvicorn.run(app, host="0.0.0.0", port=8081)

