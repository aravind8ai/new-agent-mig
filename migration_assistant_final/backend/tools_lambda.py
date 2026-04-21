import json
import boto3
import ipaddress
import math
import os

# --- Lambda Handler ---

def lambda_handler(event, context):
    """
    Main entry point for the Lambda function.
    AgentCore Gateway routes the request here based on the tool name.
    """
    # Debug logging
    print("Received event:", json.dumps(event))
    
    # Extract the tool name
    # The Gateway passes the tool name in the client context
    tool_name = ""
    # 1. Try context (Bedrock Agent)
    if context.client_context and context.client_context.custom:
        tool_name = context.client_context.custom.get('bedrockAgentCoreToolName', '')
    
    # 2. Try Event Body (Direct HTTP Invoke)
    if not tool_name and 'tool_name' in event:
        tool_name = event['tool_name']
    elif not tool_name and 'body' in event:
        # Gateway might wrap body as string
        try:
            body_json = json.loads(event['body'])
            tool_name = body_json.get('tool_name', '')
        except:
            pass

    # If using the "___" naming convention (TargetName___ToolName), strip the prefix
    if "___" in tool_name:
        tool_name = tool_name.split("___")[1]
    
    print(f"Routing to Tool: {tool_name}")
    
    try:
        if tool_name == 'cost_assistant':
            result = cost_assistant(event)
        elif tool_name == 'aws_docs_assistant':
            result = aws_docs_assistant(event)
        elif tool_name == 'vpc_subnet_calculator':
            result = vpc_subnet_calculator(event)
        else:
            # Fallback for testing or direct invocation
            return {
                'statusCode': 400,
                'body': f"Unknown or missing tool name: '{tool_name}'. Context: {context.client_context}"
            }
            
        return {
            'statusCode': 200,
            'body': result
        }
    except Exception as e:
        print(f"Error executing {tool_name}: {e}")
        return {
            'statusCode': 500,
            'body': f"Error executing tool: {str(e)}"
        }

# --- Tool Implementations ---

def cost_assistant(payload):
    """
    Cost Assistant using native boto3 (Replacing MCP Server).
    In Lambda, we use boto3 directly because running 'uvx' (MCP) is not supported.
    """
    client = boto3.client('pricing', region_name='us-east-1')
    
    # Example: Simple Price Lookup for EC2 (Real Boto3 Logic)
    # In a real app, you would parse 'payload' to find the specific service/instance type.
    try:
        response = client.get_products(
            ServiceCode='AmazonEC2',
            Filters=[
                {'Type': 'TERM_MATCH', 'Field': 'location', 'Value': 'US East (N. Virginia)'},
                {'Type': 'TERM_MATCH', 'Field': 'instanceType', 'Value': 'm5.large'},
                {'Type': 'TERM_MATCH', 'Field': 'operatingSystem', 'Value': 'Linux'}
            ],
            MaxResults=1
        )
        
        # Parse the complex JSON response from Pricing API
        price_list = response['PriceList'][0]
        # (Simplified parsing for demo purposes - real Pricing API output is very nested)
        return f"Real Boto3 Pricing Data: {price_list[:200]}..." 
    except Exception as e:
        # Fallback if credentials/permissions are missing in this demo environment
        return f"Error querying AWS Pricing API: {str(e)}. (Ensure Lambda Role has 'pricing:GetProducts' permission)"


def aws_docs_assistant(payload):
    """
    Simulated Docs Assistant.
    In the original agent, this used 'awslabs.aws-documentation-mcp-server'.
    """
    return f"AWS Documentation Search Results for '{payload}':\n\n1. Best Practices for Migration: https://aws.amazon.com/migration/ \n2. Serverless Architecture: https://aws.amazon.com/serverless/\n\n(Simulated response from Gateway Lambda)"

def vpc_subnet_calculator(payload):
    """
    Calculates optimized VPC subnet ranges.
    Ported strictly from the original Migration Agent logic.
    """
    print(f"vpc_subnet_calculator called with payload: {payload}")
    
    try:
        # 1. Parse Input
        # Gateway might pass payload as a dict or a string depending on how it was invoked
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except:
                # If string input is just CIDR, use defaults
                if "/" in payload:
                    payload = {"cidr": payload}
                else:
                    return "Error: Please provide a valid JSON payload or CIDR string (e.g., '10.0.0.0/16')"
        
        # 2. Extract parameters
        vpc_cidr = payload.get("cidr")
        if not vpc_cidr:
            return "Error: strict 'cidr' parameter is required. Example: {'cidr': '10.0.0.0/16'}"

        az_count = int(payload.get("az_count", 2))
        tiers = payload.get("tiers", ["Public", "Private", "Database"])
        
        # 3. Calculation Logic
        
        # Calculate total subnets needed
        total_subnets_needed = len(tiers) * az_count
        
        # Calculate next power of 2 for splitting
        split_bits = math.ceil(math.log2(total_subnets_needed))
        
        # Create network object
        network = ipaddress.ip_network(vpc_cidr)
        new_prefix = network.prefixlen + split_bits
        
        if new_prefix > 30:
            return f"Error: CIDR {vpc_cidr} is too small to split into {total_subnets_needed} subnets."
            
        # Generate subnets
        subnets = list(network.subnets(new_prefix=new_prefix))
        
        # 4. Format Output
        output = [f"### 🌐 VPC Subnet Plan: {vpc_cidr}"]
        output.append(f"**Configuration**: {az_count} AZs, {len(tiers)} Tiers ({', '.join(tiers)})")
        output.append(f"**Subnet Mask**: /{new_prefix} ({subnets[0].num_addresses - 5} usable IPs per subnet)\n")
        
        output.append("| Tier | Availability Zone | CIDR Block | Usable IPs |")
        output.append("|---|---|---|---|")
        
        subnet_idx = 0
        az_names = ["a", "b", "c", "d", "e", "f"]
        
        for tier in tiers:
            for az_i in range(az_count):
                if subnet_idx < len(subnets):
                    sn = subnets[subnet_idx]
                    az_suffix = az_names[az_i % len(az_names)]
                    output.append(f"| {tier} | AZ-{az_suffix} | `{sn}` | {sn.num_addresses - 5} |")
                    subnet_idx += 1
        
        unused = len(subnets) - subnet_idx
        if unused > 0:
            output.append(f"\n*Remaining spare capacity: {unused} x /{new_prefix} subnets available for future expansion.*")
            
        result = "\n".join(output)
        return result

    except Exception as e:
        return f"Error executing vpc_subnet_calculator: {str(e)}"
