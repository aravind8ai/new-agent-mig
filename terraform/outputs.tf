output "vpc_id" {
  description = "ID of the VPC created for the agent stack"
  value       = aws_vpc.main.id
}

output "public_subnet_ids" {
  description = "Public subnet IDs used by ALB and ECS"
  value       = aws_subnet.public[*].id
}

output "ecr_repository_url" {
  description = "ECR repository URL to push the container image"
  value       = aws_ecr_repository.app.repository_url
}

output "tools_lambda_name" {
  description = "Name of the deployed tools Lambda"
  value       = aws_lambda_function.tools.function_name
}

output "diagram_bucket_name" {
  description = "S3 bucket used for generated diagrams"
  value       = aws_s3_bucket.diagrams.bucket
}

output "alb_dns_name" {
  description = "Public DNS name of the application load balancer"
  value       = aws_lb.app.dns_name
}

output "app_url" {
  description = "Primary URL for the application"
  value       = "http://${aws_lb.app.dns_name}"
}

output "ecs_cluster_name" {
  description = "ECS cluster name"
  value       = aws_ecs_cluster.app.name
}

output "ecs_service_name" {
  description = "ECS service name"
  value       = aws_ecs_service.app.name
}
