import boto3
import json
import os
import time
import shutil
from dotenv import load_dotenv

load_dotenv()

# Configuration
APP_NAME = os.getenv("APP_NAME", "migration-agent-serverless")
REGION = os.getenv("AWS_DEFAULT_REGION", "us-east-1")
ACCOUNT_ID = boto3.client("sts").get_caller_identity()["Account"]

BUCKET_NAME = f"{APP_NAME}-frontend-{ACCOUNT_ID}"
LAMBDA_FUNC_NAME = f"{APP_NAME}-backend"
LAMBDA_ROLE_NAME = f"{APP_NAME}-backend-role"
API_NAME = f"{APP_NAME}-api"

def create_frontend_bucket():
    s3 = boto3.client("s3", region_name=REGION)
    try:
        s3.create_bucket(Bucket=BUCKET_NAME)
        print(f"[SUCCESS] Created Frontend Bucket: {BUCKET_NAME}")
    except s3.exceptions.BucketAlreadyOwnedByYou:
        print(f"[INFO] Bucket {BUCKET_NAME} already exists")
    except s3.exceptions.BucketAlreadyExists:
        print(f"[ERROR] Bucket {BUCKET_NAME} globally exists.")
        return None

    # Enable Static Website Hosting
    s3.put_bucket_website(
        Bucket=BUCKET_NAME,
        WebsiteConfiguration={
            'ErrorDocument': {'Key': 'index.html'},
            'IndexDocument': {'Suffix': 'index.html'},
        }
    )

    # Public Access via Policy (Or CloudFront OAI - for simplicity we use Public Read + Website)
    # WARNING: Ideally use CloudFront. For MVP, we enable public read.
    s3.put_public_access_block(
        Bucket=BUCKET_NAME,
        PublicAccessBlockConfiguration={
            'BlockPublicAcls': False,
            'IgnorePublicAcls': False,
            'BlockPublicPolicy': False,
            'RestrictPublicBuckets': False
        }
    )
    
    policy = {
        "Version": "2012-10-17",
        "Statement": [{
            "Sid": "PublicReadGetObject",
            "Effect": "Allow",
            "Principal": "*",
            "Action": "s3:GetObject",
            "Resource": f"arn:aws:s3:::{BUCKET_NAME}/*"
        }]
    }
    s3.put_bucket_policy(Bucket=BUCKET_NAME, Policy=json.dumps(policy))
    
    website_url = f"http://{BUCKET_NAME}.s3-website-{REGION}.amazonaws.com"
    print(f"[SUCCESS] Website URL: {website_url}")
    return website_url

def create_lambda_role():
    iam = boto3.client("iam", region_name=REGION)
    processed_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {"Effect": "Allow", "Principal": {"Service": "lambda.amazonaws.com"}, "Action": "sts:AssumeRole"}
        ]
    }
    
    try:
        iam.create_role(RoleName=LAMBDA_ROLE_NAME, AssumeRolePolicyDocument=json.dumps(processed_policy))
        print(f"[SUCCESS] Created Lambda Role: {LAMBDA_ROLE_NAME}")
    except iam.exceptions.EntityAlreadyExistsException:
        print(f"[INFO] Lambda Role {LAMBDA_ROLE_NAME} exists")

    # Permissions
    # Basic Execution
    iam.attach_role_policy(RoleName=LAMBDA_ROLE_NAME, PolicyArn="arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole")
    
    # Needs permissions similar to the ECS Task (Invoke Tools, Bedrock, S3 Diagrams)
    policy_doc = {
        "Version": "2012-10-17",
        "Statement": [
            {"Effect": "Allow", "Action": ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"], "Resource": "*"},
            {"Effect": "Allow", "Action": ["lambda:InvokeFunction"], "Resource": "*"},
            # Ensure it can access the diagram bucket (reusing name or new env)
            {"Effect": "Allow", "Action": ["s3:PutObject", "s3:GetObject", "s3:ListBucket"], "Resource": "*"} 
        ]
    }
    iam.put_role_policy(RoleName=LAMBDA_ROLE_NAME, PolicyName="BackendPolicy", PolicyDocument=json.dumps(policy_doc))
    
    print("[INFO] Waiting 10s for IAM propagation...")
    time.sleep(10)
    return iam.get_role(RoleName=LAMBDA_ROLE_NAME)["Role"]["Arn"]

def create_backend_lambda(role_arn):
    lambda_client = boto3.client("lambda", region_name=REGION)
    
    # We construct a placeholder function first. Deployment script will update code.
    # Creating a minimal zip
    zip_filename = "init_backend.zip"
    import zipfile
    with zipfile.ZipFile(zip_filename, 'w') as z:
        z.writestr("lambda_function.py", "def lambda_handler(event, context): return {'statusCode': 200, 'body': 'Init'}")
    
    with open(zip_filename, "rb") as f:
        zip_bytes = f.read()

    try:
        lambda_client.create_function(
            FunctionName=LAMBDA_FUNC_NAME,
            Runtime="python3.11",
            Role=role_arn,
            Handler="lambda_main.handler", # Pointing to Mangum handler
            Code={"ZipFile": zip_bytes},
            Timeout=60,
            MemorySize=512,
            Environment={
                "Variables": {
                    "TOOLS_LAMBDA_NAME": f"{APP_NAME}-tools", # Might need to match existing if reusing
                    # "GATEWAY_URL": ... (If using Gateway pattern)
                    # "GATEWAY_CLIENT_ID": ... (Inject secrets here later)
                }
            }
        )
        print(f"[SUCCESS] Created Backend Lambda: {LAMBDA_FUNC_NAME}")
    except lambda_client.exceptions.ResourceConflictException:
        print(f"[INFO] Backend Lambda {LAMBDA_FUNC_NAME} exists.")
    
    if os.path.exists(zip_filename):
        os.remove(zip_filename)
        
    return lambda_client.get_function(FunctionName=LAMBDA_FUNC_NAME)["Configuration"]["FunctionArn"]

def create_api_gateway(lambda_arn):
    apigatewayv2 = boto3.client("apigatewayv2", region_name=REGION)
    
    # Create API
    try:
        # Check if exists (simple check by name retrieval is hard, assume create or idempotent fail logic usually required but API Gateway allows dup names)
        # We'll just create.
        api = apigatewayv2.create_api(
            Name=API_NAME,
            ProtocolType="HTTP",
            Target=lambda_arn # value matches expected integration? No, 'Target' is strictly for quick create?
            # Actually efficient way:
        )
        api_id = api["ApiId"]
        api_endpoint = api["ApiEndpoint"]
        print(f"[SUCCESS] Created HTTP API: {API_NAME} ({api_endpoint})")
    except Exception as e:
        print(f"[ERROR] API Creation failed: {e}")
        return None

    # Integration
    integration = apigatewayv2.create_integration(
        ApiId=api_id,
        IntegrationType="AWS_PROXY",
        IntegrationUri=lambda_arn,
        PayloadFormatVersion="2.0"
    )
    integration_id = integration["IntegrationId"]
    
    # Route (Catch-All)
    apigatewayv2.create_route(
        ApiId=api_id,
        RouteKey="ANY /{proxy+}",
        Target=f"integrations/{integration_id}"
    )
    
    # Permission for API Gateway to invoke Lambda
    lambda_client = boto3.client("lambda", region_name=REGION)
    try:
        lambda_client.add_permission(
            FunctionName=LAMBDA_FUNC_NAME,
            StatementId=f"apigateway-invoke-{api_id}",
            Action="lambda:InvokeFunction",
            Principal="apigateway.amazonaws.com",
            SourceArn=f"arn:aws:execute-api:{REGION}:{ACCOUNT_ID}:{api_id}/*/*"
        )
        print("[SUCCESS] Added Lambda Permission for API Gateway")
    except lambda_client.exceptions.ResourceConflictException:
        pass

    return api_endpoint

if __name__ == "__main__":
    print("--- Provisioning Serverless Stack ---")
    website_url = create_frontend_bucket()
    role_arn = create_lambda_role()
    lambda_arn = create_backend_lambda(role_arn)
    api_url = create_api_gateway(lambda_arn)
    
    print("\n[SUCCESS] Infrastructure Provisioned!")
    print(f"Frontend URL: {website_url}")
    print(f"Backend API URL: {api_url}")
    
    # Write to .env or .serverless_config for deploy script
    with open(".serverless_output", "w") as f:
        f.write(f"FRONTEND_BUCKET={BUCKET_NAME}\n")
        f.write(f"BACKEND_LAMBDA={LAMBDA_FUNC_NAME}\n")
        f.write(f"API_URL={api_url}\n")
