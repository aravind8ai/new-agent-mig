# Terraform deployment for AWS Migration Assistant

This Terraform stack provisions the same runtime components as the Python scripts in `migration_assistant_final/infrastructure`:

- New VPC, Internet Gateway, public route table, and public subnets
- Tools Lambda (`<app_name>-tools`)
- S3 bucket for diagrams (`<app_name>-diagrams-<account_id>`) with 1-day lifecycle on `diagrams/`
- ECR repository for the app image
- ECS Fargate cluster, task definition, and service
- Application Load Balancer + target group + HTTP listener
- IAM roles/policies for ECS and Lambda

## Prerequisites

- Terraform `>= 1.5`
- AWS credentials configured (`aws configure` or environment variables)
- Docker installed (to build and push the app image)

## Usage

```bash
cd terraform
cp terraform.tfvars.example terraform.tfvars
terraform init
terraform plan
terraform apply
```

After apply, push the app image to ECR (use output `ecr_repository_url`) and trigger deployment:

```bash
cd ../migration_assistant_final
./deploy.sh
```

`desired_count` defaults to `0` for infra-first bootstrap (to avoid ECS pull failures before an image exists).  
`deploy.sh` scales the ECS service to `DESIRED_COUNT` (default `1`) after pushing the image.

Access the app using output `app_url` (ALB DNS over HTTP).

If you push a new `latest` image and want Terraform to trigger ECS rollout, set:

```hcl
force_new_deployment = true
```

for one apply, then set it back to `false`.

## Notes

- No default VPC is required; Terraform creates and manages networking for this stack.
- No ACM certificate and no Route53 records are created.
- Lambda code is packaged from `../migration_assistant_final/backend/tools_lambda.py`.
