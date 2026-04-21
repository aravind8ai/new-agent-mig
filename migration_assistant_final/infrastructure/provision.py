import boto3
import json
import time
import os
from dotenv import load_dotenv

load_dotenv()

# Configuration
# Configuration
APP_NAME = os.getenv("APP_NAME", "migration-agent-cloud")
REGION = os.getenv("AWS_DEFAULT_REGION", "us-east-1")
ACCOUNT_ID = boto3.client("sts").get_caller_identity()["Account"]
BUCKET_NAME = f"{APP_NAME}-diagrams-{ACCOUNT_ID}"
ECR_REPO_NAME = APP_NAME
ECS_CLUSTER_NAME = f"{APP_NAME}-cluster"
ECS_SERVICE_NAME = f"{APP_NAME}-service"
ECS_TASK_FAMILY = f"{APP_NAME}-task"

# IAM Roles
EXECUTION_ROLE_NAME = f"{APP_NAME}-execution-role"
TASK_ROLE_NAME = f"{APP_NAME}-task-role"

def create_iam_roles():
    iam = boto3.client("iam")
    
    # 1. Execution Role (for Fargate to pull images & logs)
    assume_role_policy = {
        "Version": "2012-10-17",
        "Statement": [{"Effect": "Allow", "Principal": {"Service": "ecs-tasks.amazonaws.com"}, "Action": "sts:AssumeRole"}]
    }
    
    try:
        iam.create_role(RoleName=EXECUTION_ROLE_NAME, AssumeRolePolicyDocument=json.dumps(assume_role_policy))
        print(f"[SUCCESS] Created Execution Role: {EXECUTION_ROLE_NAME}")
    except iam.exceptions.EntityAlreadyExistsException:
        print(f"[INFO] Execution Role {EXECUTION_ROLE_NAME} already exists")

    iam.attach_role_policy(RoleName=EXECUTION_ROLE_NAME, PolicyArn="arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy")

    # 2. Task Role (for the App to call AWS services)
    try:
        iam.create_role(RoleName=TASK_ROLE_NAME, AssumeRolePolicyDocument=json.dumps(assume_role_policy))
        print(f"[SUCCESS] Created Task Role: {TASK_ROLE_NAME}")
    except iam.exceptions.EntityAlreadyExistsException:
        print(f"[INFO] Task Role {TASK_ROLE_NAME} already exists")

    # Grant permissions (S3, Bedrock, Lambda Invoke)
    policy_doc = {
        "Version": "2012-10-17",
        "Statement": [
            {"Effect": "Allow", "Action": ["s3:PutObject", "s3:GetObject", "s3:ListBucket"], "Resource": [f"arn:aws:s3:::{BUCKET_NAME}", f"arn:aws:s3:::{BUCKET_NAME}/*"]},
            {"Effect": "Allow", "Action": ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"], "Resource": "*"}, 
            # Grant access to the Tools Lambda we just deployed
            {"Effect": "Allow", "Action": ["lambda:InvokeFunction"], "Resource": [f"arn:aws:lambda:{REGION}:{ACCOUNT_ID}:function:{APP_NAME}-tools"]}
        ]
    }
    
    time.sleep(1) # Consistency
    iam.put_role_policy(RoleName=TASK_ROLE_NAME, PolicyName="MigrationAgentPolicy", PolicyDocument=json.dumps(policy_doc))
    print("[SUCCESS] Attached policies to Task Role")
    
    # Return ARNs
    exec_arn = iam.get_role(RoleName=EXECUTION_ROLE_NAME)["Role"]["Arn"]
    task_arn = iam.get_role(RoleName=TASK_ROLE_NAME)["Role"]["Arn"]
    return exec_arn, task_arn

def create_s3_bucket():
    s3 = boto3.client("s3", region_name=REGION)
    try:
        s3.create_bucket(Bucket=BUCKET_NAME)
        print(f"[SUCCESS] Created S3 Bucket: {BUCKET_NAME}")
    except s3.exceptions.BucketAlreadyOwnedByYou:
        print(f"[INFO] Bucket {BUCKET_NAME} already exists")
    except s3.exceptions.BucketAlreadyExists: # Owned by someone else
        print(f"[ERROR] Bucket {BUCKET_NAME} globally exists. Skipping S3 setup.")
        return

    # Set Lifecycle Policy (Clean up diagrams after 1 day)
    s3.put_bucket_lifecycle_configuration(
        Bucket=BUCKET_NAME,
        LifecycleConfiguration={
            "Rules": [{
                "ID": "DeleteOldDiagrams",
                "Status": "Enabled",
                "Expiration": {"Days": 1},
                "Filter": {"Prefix": "diagrams/"}
            }]
        }
    )
    
    # Configure Public Access (Optional, or rely on presigned URLs - we use presigned in code, so Block Public Access is fine!)
    # Actually code uses generate_presigned_url, so we keep it private! Secure by default.
    print(f"[INFO] Bucket is private. Code will use Presigned URLs.")

def create_ecr_repo():
    ecr = boto3.client("ecr", region_name=REGION)
    try:
        ecr.create_repository(repositoryName=ECR_REPO_NAME)
        print(f"[SUCCESS] Created ECR Repo: {ECR_REPO_NAME}")
    except ecr.exceptions.RepositoryAlreadyExistsException:
        print(f"[INFO] ECR Repo {ECR_REPO_NAME} already exists")
    
    return f"{ACCOUNT_ID}.dkr.ecr.{REGION}.amazonaws.com/{ECR_REPO_NAME}"

    # ... (Previous IAM, S3, ECR code remains the same until create_ecs_resources) ... 

def get_acm_certificate(domain_name):
    acm = boto3.client("acm", region_name=REGION)
    print(f"[INFO] Searching for ACM certificate for {domain_name}...")
    try:
        paginator = acm.get_paginator('list_certificates')
        for page in paginator.paginate(CertificateStatuses=['ISSUED']):
            for cert in page['CertificateSummaryList']:
                cert_domain = cert['DomainName']
                # Check for exact match or wildcard match
                if domain_name == cert_domain or (cert_domain.startswith("*.") and domain_name.endswith(cert_domain[2:])):
                    print(f"[SUCCESS] Found Certificate: {cert['CertificateArn']} ({cert_domain})")
                    return cert['CertificateArn']
    except Exception as e:
        print(f"[WARNING] ACM Lookup failed: {e}")
    
    print("[WARNING] No matching certificate found. Fallback to HTTP.")
    return None

def create_load_balancer(vpc_id, subnet_ids, security_group_id):
    elbv2 = boto3.client("elbv2", region_name=REGION)
    
    # 1. Target Group
    tg_name = f"{APP_NAME}-tg"
    try:
        tg_response = elbv2.create_target_group(
            Name=tg_name,
            Protocol="HTTP",
            Port=8000,
            VpcId=vpc_id,
            TargetType="ip",
            HealthCheckProtocol="HTTP",
            HealthCheckPath="/", # Root is fine for now, or /health
            Matcher={"HttpCode": "200-499"}
        )
        tg_arn = tg_response["TargetGroups"][0]["TargetGroupArn"]
        print(f"[SUCCESS] Created Target Group: {tg_name}")
    except elbv2.exceptions.DuplicateTargetGroupNameException:
        print(f"[INFO] Target Group {tg_name} exists")
        tgs = elbv2.describe_target_groups(Names=[tg_name])
        tg_arn = tgs["TargetGroups"][0]["TargetGroupArn"]

    # 2. Load Balancer
    alb_name = f"{APP_NAME}-alb"
    try:
        alb_response = elbv2.create_load_balancer(
            Name=alb_name,
            Subnets=subnet_ids,
            SecurityGroups=[security_group_id],
            Scheme="internet-facing",
            Type="application",
            IpAddressType="ipv4"
        )
        alb_arn = alb_response["LoadBalancers"][0]["LoadBalancerArn"]
        alb_dns = alb_response["LoadBalancers"][0]["DNSName"]
        alb_zone_id = alb_response["LoadBalancers"][0]["CanonicalHostedZoneId"]
        print(f"[SUCCESS] Created ALB: {alb_name} ({alb_dns})")
    except elbv2.exceptions.DuplicateLoadBalancerNameException:
        print(f"[INFO] ALB {alb_name} exists")
        albs = elbv2.describe_load_balancers(Names=[alb_name])
        alb_arn = albs["LoadBalancers"][0]["LoadBalancerArn"]
        alb_dns = albs["LoadBalancers"][0]["DNSName"]
        alb_zone_id = albs["LoadBalancers"][0]["CanonicalHostedZoneId"]

    # 3. Listeners - Re-Apply Logic (Idempotent)
    # Fetch existing listeners to delete/update
    listeners = elbv2.describe_listeners(LoadBalancerArn=alb_arn)
    for listener in listeners.get("Listeners", []):
        port = listener["Port"]
        if port in [80, 443]:
            # Delete existing to recreate with new config (simplest way to enforce state)
            print(f"[INFO] Deleting existing listener on port {port} to apply updates...")
            elbv2.delete_listener(ListenerArn=listener["ListenerArn"])
            time.sleep(1)

    # 3. Listeners
    # Check for Certificate
    FULL_DOMAIN = os.getenv("DOMAIN_NAME", "migratecompanion.evidhai.com")
    # User provided specific certificate or generic lookup
    cert_arn = os.getenv("ACM_CERT_ARN")
    if not cert_arn:
         # Optional: Try lookup if not provided
         # cert_arn = get_acm_certificate(FULL_DOMAIN) 
         pass
    
    if cert_arn:
        # Create HTTP (80) -> Redirect to HTTPS
        elbv2.create_listener(
            LoadBalancerArn=alb_arn,
            Protocol="HTTP",
            Port=80,
            DefaultActions=[{
                "Type": "redirect",
                "RedirectConfig": {"Protocol": "HTTPS", "Port": "443", "StatusCode": "HTTP_301"}
            }]
        )
        print("[SUCCESS] Configured HTTP Listener (80) -> Redirect to HTTPS")

        # Create HTTPS (443) -> Target Group
        elbv2.create_listener(
            LoadBalancerArn=alb_arn,
            Protocol="HTTPS",
            Port=443,
            Certificates=[{"CertificateArn": cert_arn}],
            DefaultActions=[{"Type": "forward", "TargetGroupArn": tg_arn}]
        )
        print("[SUCCESS] Configured HTTPS Listener (443) -> Target Group")
    else:
        # No Certificate -> HTTP Only (80) -> Target Group
        elbv2.create_listener(
            LoadBalancerArn=alb_arn,
            Protocol="HTTP",
            Port=80,
            DefaultActions=[{"Type": "forward", "TargetGroupArn": tg_arn}]
        )
        print("[WARNING] No Certificate found. Configured HTTP Listener (80) -> Target Group (Not Secure)")

    return tg_arn, alb_dns, alb_zone_id

def update_route53(dns_name, zone_id):
    r53 = boto3.client("route53")
    domain = "evidhai.com."
    record_name = "migratecompanion.evidhai.com."
    
    # Find Hosted Zone
    hosted_zones = r53.list_hosted_zones_by_name(DNSName=domain)
    if not hosted_zones["HostedZones"]:
        print(f"[WARNING] No Hosted Zone found for {domain}")
        return

    hz_id = hosted_zones["HostedZones"][0]["Id"]
    
    change_batch = {
        "Changes": [{
            "Action": "UPSERT",
            "ResourceRecordSet": {
                "Name": record_name,
                "Type": "A",
                "AliasTarget": {
                    "HostedZoneId": zone_id,
                    "DNSName": dns_name,
                    "EvaluateTargetHealth": False
                }
            }
        }]
    }
    
    try:
        r53.change_resource_record_sets(HostedZoneId=hz_id, ChangeBatch=change_batch)
        print(f"[SUCCESS] Updated Route53: {record_name} -> {dns_name}")
    except Exception as e:
        print(f"[ERROR] Route53 Update Failed: {e}")

def create_security_group(vpc_id):
    ec2 = boto3.client("ec2", region_name=REGION)
    sg_name = f"{APP_NAME}-sg"
    
    try:
        res = ec2.describe_security_groups(Filters=[{"Name": "group-name", "Values": [sg_name]}, {"Name": "vpc-id", "Values": [vpc_id]}])
        if res["SecurityGroups"]:
            return res["SecurityGroups"][0]["GroupId"]
            
        sg = ec2.create_security_group(GroupName=sg_name, Description="Migration Agent SG", VpcId=vpc_id)
        sg_id = sg["GroupId"]
        
        # Inbound: Allow HTTP/HTTPS from anywhere
        ec2.authorize_security_group_ingress(GroupId=sg_id, IpPermissions=[
            {"IpProtocol": "tcp", "FromPort": 80, "ToPort": 80, "IpRanges": [{"CidrIp": "0.0.0.0/0"}]},
            {"IpProtocol": "tcp", "FromPort": 443, "ToPort": 443, "IpRanges": [{"CidrIp": "0.0.0.0/0"}]},
            {"IpProtocol": "tcp", "FromPort": 8000, "ToPort": 8000, "IpRanges": [{"CidrIp": "0.0.0.0/0"}]} # For testing, ideally only from ALB
        ])
        print(f"[SUCCESS] Created Security Group: {sg_name}")
        return sg_id
    except Exception as e:
        print(f"[ERROR] Security Group creation failed: {e}")
        return None

def create_ecs_resources(exec_role_arn, task_role_arn, image_uri, target_group_arn=None):
    ecs = boto3.client("ecs", region_name=REGION)
    ec2 = boto3.client("ec2", region_name=REGION)

    # ... (Cluster & Task Def logic same as before) ...
    try:
        ecs.create_cluster(clusterName=ECS_CLUSTER_NAME)
        print(f"[SUCCESS] Created ECS Cluster: {ECS_CLUSTER_NAME}")
    except Exception as e:
        print(f"[ERROR] Cluster creation failed: {e}")

    print("[INFO] Registering Task Definition...")
    response = ecs.register_task_definition(
        family=ECS_TASK_FAMILY,
        networkMode="awsvpc",
        requiresCompatibilities=["FARGATE"],
        cpu="1024", 
        memory="3072",
        executionRoleArn=exec_role_arn,
        taskRoleArn=task_role_arn,
        containerDefinitions=[
            {
                "name": APP_NAME,
                "image": image_uri + ":latest",
                "essential": True,
                "portMappings": [{"containerPort": 8000, "protocol": "tcp"}],
                "environment": [
                    {"name": "DIAGRAM_BUCKET_NAME", "value": BUCKET_NAME},
                    {"name": "GATEWAY_URL", "value": os.getenv("GATEWAY_URL", "")}, 
                    {"name": "TOOLS_LAMBDA_NAME", "value": f"{APP_NAME}-tools"},
                    {"name": "AWS_DEFAULT_REGION", "value": REGION}
                ],
                "logConfiguration": {
                    "logDriver": "awslogs",
                    "options": {
                        "awslogs-group": f"/ecs/{APP_NAME}",
                        "awslogs-region": REGION,
                        "awslogs-stream-prefix": "ecs"
                    }
                }
            }
        ]
    )
    print(f"[SUCCESS] Registered Task Definition: {ECS_TASK_FAMILY}")

    # Create Log Group
    try:
        boto3.client("logs", region_name=REGION).create_log_group(logGroupName=f"/ecs/{APP_NAME}")
    except:
        pass

    # VPC setup
    vpcs = ec2.describe_vpcs(Filters=[{"Name": "isDefault", "Values": ["true"]}])
    if vpcs["Vpcs"]:
        vpc_id = vpcs["Vpcs"][0]["VpcId"]
        subnets = ec2.describe_subnets(Filters=[{"Name": "vpc-id", "Values": [vpc_id]}])
        subnet_ids = [sn["SubnetId"] for sn in subnets["Subnets"]]
        
        # Create Security Group
        sg_id = create_security_group(vpc_id)
        
        # If we need ALB, create it now (if not passed externally, but flow suggests we do it before service)
        # Actually better to decouple, but for this script:
        if not target_group_arn:
             target_group_arn, alb_dns, alb_zone = create_load_balancer(vpc_id, subnet_ids, sg_id)
             update_route53(alb_dns, alb_zone)

    else:
        print("[ERROR] No Default VPC found.")
        return

    print(f"[INFO] Creating Service in VPC {vpc_id}...")
    
    lb_config = [{"targetGroupArn": target_group_arn, "containerName": APP_NAME, "containerPort": 8000}] if target_group_arn else []

    try:
        ecs.create_service(
            cluster=ECS_CLUSTER_NAME,
            serviceName=ECS_SERVICE_NAME,
            taskDefinition=ECS_TASK_FAMILY,
            desiredCount=1,
            launchType="FARGATE",
            networkConfiguration={
                "awsvpcConfiguration": {
                    "subnets": subnet_ids,
                    "securityGroups": [sg_id],
                    "assignPublicIp": "ENABLED"
                }
            },
            loadBalancers=lb_config
        )
        print(f"[SUCCESS] Created Service: {ECS_SERVICE_NAME}")
    except ecs.exceptions.InvalidParameterException as e:
        print(f"[INFO] CreateService failed ({e}). Assuming service exists, updating...")
        ecs.update_service(
             cluster=ECS_CLUSTER_NAME,
             service=ECS_SERVICE_NAME,
             taskDefinition=ECS_TASK_FAMILY,
             forceNewDeployment=True
        )
    return f"https://{alb_dns}" if os.getenv("ACM_CERT_ARN") else f"http://{alb_dns}"

if __name__ == "__main__":
    print("--- Starting Provisioning ---")
    create_s3_bucket()
    repo_uri = create_ecr_repo()
    exec_arn, task_arn = create_iam_roles()
    
    print("\n[WARNING] NOTE: Docker image must be pushed BEFORE Fargate can start tasks successfully.")
    
    # We call ECS creation which handles ALB/DNS internally now
    app_url = create_ecs_resources(exec_arn, task_arn, repo_uri)
    
    print("\n[SUCCESS] Provisioning Complete!")
    print(f"1. Run './deploy.sh' to push the image.")
    print(f"2. Visit: {app_url}")

