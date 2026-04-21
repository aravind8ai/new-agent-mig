terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.4"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

data "aws_caller_identity" "current" {}

data "aws_region" "current" {}

data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
}

locals {
  app_name            = var.app_name
  ecs_cluster_name    = "${local.app_name}-cluster"
  ecs_service_name    = "${local.app_name}-service"
  ecs_task_family     = "${local.app_name}-task"
  ecr_repository_name = local.app_name
  tools_lambda_name   = "${local.app_name}-tools"
  lambda_role_name    = "${local.app_name}-lambda-role"
  execution_role_name = "${local.app_name}-execution-role"
  task_role_name      = "${local.app_name}-task-role"
  diagram_bucket_name = "${local.app_name}-diagrams-${data.aws_caller_identity.current.account_id}"
  container_name      = local.app_name
  container_port      = 8000
  ecs_log_group_name  = "/ecs/${local.app_name}"
  target_group_name   = substr("${local.app_name}-tg", 0, 32)
  alb_name            = substr("${local.app_name}-alb", 0, 32)
  image_uri           = "${aws_ecr_repository.app.repository_url}:${var.container_image_tag}"
  lambda_source_file  = "${path.module}/../migration_assistant_final/backend/tools_lambda.py"
  lambda_output_zip   = "${path.module}/tools_lambda.zip"
}

resource "aws_s3_bucket" "diagrams" {
  bucket = local.diagram_bucket_name
}

resource "aws_s3_bucket_public_access_block" "diagrams" {
  bucket = aws_s3_bucket.diagrams.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_lifecycle_configuration" "diagrams" {
  bucket = aws_s3_bucket.diagrams.id

  rule {
    id     = "DeleteOldDiagrams"
    status = "Enabled"

    filter {
      prefix = "diagrams/"
    }

    expiration {
      days = 1
    }
  }
}

resource "aws_ecr_repository" "app" {
  name                 = local.ecr_repository_name
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "aws_ecr_lifecycle_policy" "app" {
  repository = aws_ecr_repository.app.name

  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Keep only the latest 25 images"
        selection = {
          tagStatus   = "any"
          countType   = "imageCountMoreThan"
          countNumber = 25
        }
        action = {
          type = "expire"
        }
      }
    ]
  })
}

resource "aws_cloudwatch_log_group" "ecs" {
  name              = local.ecs_log_group_name
  retention_in_days = var.log_retention_days
}

resource "aws_iam_role" "ecs_execution" {
  name = local.execution_role_name

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Service = "ecs-tasks.amazonaws.com"
        }
        Action = "sts:AssumeRole"
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "ecs_execution_managed" {
  role       = aws_iam_role.ecs_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role" "ecs_task" {
  name = local.task_role_name

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Service = "ecs-tasks.amazonaws.com"
        }
        Action = "sts:AssumeRole"
      }
    ]
  })
}

resource "aws_iam_role_policy" "ecs_task_inline" {
  name = "MigrationAgentPolicy"
  role = aws_iam_role.ecs_task.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = ["s3:PutObject", "s3:GetObject", "s3:ListBucket"]
        Resource = [
          aws_s3_bucket.diagrams.arn,
          "${aws_s3_bucket.diagrams.arn}/*"
        ]
      },
      {
        Effect   = "Allow"
        Action   = ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"]
        Resource = "*"
      },
      {
        Effect   = "Allow"
        Action   = ["lambda:InvokeFunction"]
        Resource = [aws_lambda_function.tools.arn]
      }
    ]
  })
}

resource "aws_iam_role" "tools_lambda" {
  name = local.lambda_role_name

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Service = "lambda.amazonaws.com"
        }
        Action = "sts:AssumeRole"
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "tools_lambda_basic" {
  role       = aws_iam_role.tools_lambda.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy" "tools_lambda_pricing" {
  name = "PricingAccess"
  role = aws_iam_role.tools_lambda.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["pricing:GetProducts", "pricing:GetAttributeValues"]
        Resource = "*"
      }
    ]
  })
}

data "archive_file" "tools_lambda" {
  type        = "zip"
  output_path = local.lambda_output_zip

  source {
    content  = file(local.lambda_source_file)
    filename = "lambda_function.py"
  }
}

resource "aws_lambda_function" "tools" {
  function_name = local.tools_lambda_name
  role          = aws_iam_role.tools_lambda.arn
  handler       = "lambda_function.lambda_handler"
  runtime       = "python3.11"
  timeout       = 30
  memory_size   = 128

  filename         = data.archive_file.tools_lambda.output_path
  source_code_hash = data.archive_file.tools_lambda.output_base64sha256

  depends_on = [aws_iam_role_policy_attachment.tools_lambda_basic]
}

resource "aws_ecs_cluster" "app" {
  name = local.ecs_cluster_name
}

resource "aws_security_group" "alb" {
  name        = "${local.app_name}-alb-sg"
  description = "ALB security group"
  vpc_id      = data.aws_vpc.default.id

  ingress {
    description = "HTTP"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "HTTPS"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_security_group" "ecs" {
  name        = "${local.app_name}-ecs-sg"
  description = "ECS task security group"
  vpc_id      = data.aws_vpc.default.id

  ingress {
    description     = "App traffic from ALB"
    from_port       = local.container_port
    to_port         = local.container_port
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_lb" "app" {
  name               = local.alb_name
  internal           = false
  load_balancer_type = "application"
  security_groups    = [aws_security_group.alb.id]
  subnets            = data.aws_subnets.default.ids
}

resource "aws_lb_target_group" "app" {
  name        = local.target_group_name
  port        = local.container_port
  protocol    = "HTTP"
  vpc_id      = data.aws_vpc.default.id
  target_type = "ip"

  health_check {
    protocol            = "HTTP"
    path                = "/"
    matcher             = "200-499"
    interval            = 30
    timeout             = 5
    healthy_threshold   = 2
    unhealthy_threshold = 2
  }
}

resource "aws_lb_listener" "http_forward" {
  load_balancer_arn = aws_lb.app.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.app.arn
  }
}

resource "aws_ecs_task_definition" "app" {
  family                   = local.ecs_task_family
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = tostring(var.task_cpu)
  memory                   = tostring(var.task_memory)
  execution_role_arn       = aws_iam_role.ecs_execution.arn
  task_role_arn            = aws_iam_role.ecs_task.arn

  container_definitions = jsonencode([
    {
      name      = local.container_name
      image     = local.image_uri
      essential = true
      portMappings = [
        {
          containerPort = local.container_port
          protocol      = "tcp"
        }
      ]
      environment = [
        { name = "DIAGRAM_BUCKET_NAME", value = aws_s3_bucket.diagrams.bucket },
        { name = "GATEWAY_URL", value = var.gateway_url },
        { name = "TOOLS_LAMBDA_NAME", value = aws_lambda_function.tools.function_name },
        { name = "AWS_DEFAULT_REGION", value = data.aws_region.current.name }
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.ecs.name
          awslogs-region        = data.aws_region.current.name
          awslogs-stream-prefix = "ecs"
        }
      }
    }
  ])
}

resource "aws_ecs_service" "app" {
  name            = local.ecs_service_name
  cluster         = aws_ecs_cluster.app.id
  task_definition = aws_ecs_task_definition.app.arn
  desired_count   = var.desired_count
  launch_type     = "FARGATE"

  force_new_deployment = var.force_new_deployment

  network_configuration {
    subnets          = data.aws_subnets.default.ids
    security_groups  = [aws_security_group.ecs.id]
    assign_public_ip = true
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.app.arn
    container_name   = local.container_name
    container_port   = local.container_port
  }

  depends_on = [
    aws_lb_listener.http_forward
  ]
}
