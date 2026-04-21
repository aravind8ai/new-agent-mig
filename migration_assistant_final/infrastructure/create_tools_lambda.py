import boto3
import json
import os
import time
import shutil
from zipfile import ZipFile
from dotenv import load_dotenv

load_dotenv()

# Configuration
APP_NAME = os.getenv("APP_NAME", "migration-agent-cloud")
REGION = os.getenv("AWS_DEFAULT_REGION", "us-east-1")
LAMBDA_FUNC_NAME = f"{APP_NAME}-tools"
LAMBDA_ROLE_NAME = f"{APP_NAME}-lambda-role"

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

    # Attach Basic Execution + Pricing Read Access
    iam.attach_role_policy(RoleName=LAMBDA_ROLE_NAME, PolicyArn="arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole")
    
    # Custom Policy for Pricing (Cost Assistant)
    pricing_policy = {
        "Version": "2012-10-17",
        "Statement": [{"Effect": "Allow", "Action": ["pricing:GetProducts", "pricing:GetAttributeValues"], "Resource": "*"}]
    }
    iam.put_role_policy(RoleName=LAMBDA_ROLE_NAME, PolicyName="PricingAccess", PolicyDocument=json.dumps(pricing_policy))
    
    print("[INFO] Waiting 15s for IAM Role propagation...")
    time.sleep(15) # Propagation (Increased to avoid race condition)
    return iam.get_role(RoleName=LAMBDA_ROLE_NAME)["Role"]["Arn"]

def deploy_lambda(role_arn):
    lambda_client = boto3.client("lambda", region_name=REGION)
    
    # Package
    zip_filename = "tools_lambda.zip"
    source_file = os.path.join(os.path.dirname(__file__), "../backend/tools_lambda.py")
    
    # We need to rename it to 'tools_lambda.py' inside the zip or match handler
    with ZipFile(zip_filename, 'w') as z:
        z.write(source_file, arcname="lambda_function.py")
        
    with open(zip_filename, "rb") as f:
        zip_bytes = f.read()

    # Retry logic for "Role defined for the function cannot be assumed by Lambda"
    max_retries = 5
    for attempt in range(max_retries):
        try:
            lambda_client.create_function(
                FunctionName=LAMBDA_FUNC_NAME,
                Runtime="python3.11",
                Role=role_arn,
                Handler="lambda_function.lambda_handler",
                Code={"ZipFile": zip_bytes},
                Timeout=30,
                MemorySize=128
            )
            print(f"[SUCCESS] Created Lambda: {LAMBDA_FUNC_NAME}")
            break
        except lambda_client.exceptions.ResourceConflictException:
            print(f"[INFO] Updating existing Lambda: {LAMBDA_FUNC_NAME}")
            lambda_client.update_function_code(FunctionName=LAMBDA_FUNC_NAME, ZipFile=zip_bytes)
            break
        except Exception as e:
            if "The role defined for the function cannot be assumed by Lambda" in str(e):
                print(f"[WARNING] IAM Role not ready yet. Retrying ({attempt+1}/{max_retries})...")
                time.sleep(10)
            else:
                # Other error, raise it
                raise e
    else:
        print("[ERROR] Failed to create Lambda after max retries due to IAM delays.")
        raise Exception("IAM Role Propagation Failed")
    
    # Clean up
    if os.path.exists(zip_filename):
        os.remove(zip_filename)
        
    return LAMBDA_FUNC_NAME

if __name__ == "__main__":
    print(f"--- Deploying Tools Lambda ({LAMBDA_FUNC_NAME}) ---")
    role_arn = create_lambda_role()
    func_name = deploy_lambda(role_arn)
    print(f"\n[SUCCESS] Tools Lambda Deployed: {func_name}")
    print("Next: Run 'python infrastructure/provision.py' to deploy the Agent App.")
