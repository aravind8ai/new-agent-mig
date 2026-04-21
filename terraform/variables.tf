variable "aws_region" {
  description = "AWS region for all resources"
  type        = string
  default     = "us-east-1"
}

variable "app_name" {
  description = "Base name prefix for resources"
  type        = string
  default     = "migration-agent-cloud"
}

variable "gateway_url" {
  description = "Gateway URL injected into ECS task environment"
  type        = string
  default     = ""
}

variable "container_image_tag" {
  description = "ECR image tag to deploy"
  type        = string
  default     = "latest"
}

variable "task_cpu" {
  description = "Fargate task CPU units"
  type        = number
  default     = 1024
}

variable "task_memory" {
  description = "Fargate task memory (MiB)"
  type        = number
  default     = 3072
}

variable "desired_count" {
  description = "Desired ECS task count"
  type        = number
  default     = 1
}

variable "log_retention_days" {
  description = "CloudWatch log retention for ECS logs"
  type        = number
  default     = 14
}

variable "force_new_deployment" {
  description = "Force ECS to redeploy tasks on apply"
  type        = bool
  default     = false
}
