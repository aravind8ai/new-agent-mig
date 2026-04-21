# IAM Role for Bedrock POC
resource "aws_iam_role" "bedrock_poc" {
  name = "bedrock_poc"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Service = "sagemaker.amazonaws.com"
        }
        Action = "sts:AssumeRole"
      },
      {
        Effect = "Allow"
        Principal = {
          Service = "cloudformation.amazonaws.com"
        }
        Action = "sts:AssumeRole"
      }
    ]
  })

  tags = {
    Name        = "bedrock_poc"
    Environment = "poc"
  }
}

# IAM Policy for Bedrock POC
resource "aws_iam_policy" "bedrock_poc_policy" {
  name        = "bedrock_poc_policy"
  description = "Policy for Bedrock POC with comprehensive AWS service permissions"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid = "CoreAWSServices"
        Action = [
          "aws-marketplace:Unsubscribe",
          "aws-marketplace:ViewSubscriptions",
          "cloudformation:*",
          "cloudtrail:*",
          "cloudwatch:*",
          "cognito-identity:*",
          "dynamodb:*",
          "es:*",
          "events:*",
          "execute-api:*",
          "lambda:*",
          "logs:*",
          "s3:*",
          "ecr:*",
          "sagemaker:*",
          "sts:*",
          "tag:*",
          "xray:*",
          "codebuild:*",
          "cognito-idp:*",
          "ssm:*",
          "secretsmanager:*"
        ]
        Effect   = "Allow"
        Resource = "*"
      },
      {
        Sid = "BedrockAgentCorePermission"
        Effect = "Allow"
        Action = [
          "bedrock-agentcore:Get*",
          "bedrock-agentcore:List*",
          "bedrock-agentcore:Delete*",
          "bedrock-agentcore:Create*",
          "bedrock-agentcore:Retrieve*",
          "bedrock-agentcore:Invoke*",
          "bedrock-agentcore:UpdateAgentRuntime",
          "bedrock-agentcore:ConnectBrowserAutomationStream",
          "bedrock-agentcore:ConnectBrowserLiveViewStream",
          "bedrock-agentcore:DeleteBrowser"
        ]
        Resource = "*"
      },
      {
        Sid = "ECRAccess"
        Effect = "Allow"
        Action = [
          "ecr:BatchGetImage",
          "ecr:GetDownloadUrlForLayer",
          "ecr:GetAuthorizationToken"
        ]
        Resource = "*"
      },
      {
        Sid = "BedrockAgentCoreWorkloadAccess"
        Effect = "Allow"
        Action = [
          "bedrock-agentcore:GetWorkloadAccessToken",
          "bedrock-agentcore:GetWorkloadAccessTokenForJWT",
          "bedrock-agentcore:GetWorkloadAccessTokenForUserId"
        ]
        Resource = "*"
      },
      {
        Sid = "BedrockAgentCoreObservability"
        Effect = "Allow"
        Action = [
          "application-signals:StartDiscovery"
        ]
        Resource = "*"
      },
      {
        Sid = "AmazonBedrockReadOnly"
        Effect = "Allow"
        Action = [
          "bedrock:Get*",
          "bedrock:List*",
          "bedrock:PutUseCaseForModelAccess",
          "aws-marketplace:ViewSubscriptions"
        ]
        Resource = "*"
      },
      {
        Sid = "EC2Permissions"
        Effect = "Allow"
        Action = [
          "ec2:DescribeVpcs",
          "ec2:DescribeSubnets"
        ]
        Resource = "*"
      },
      {
        Sid = "BedrockPolicies"
        Effect = "Allow"
        Action = [
          "bedrock:InvokeModel",
          "bedrock:InvokeModelWithResponseStream",
          "bedrock:TagResource",
          "bedrock:UntagResource",
          "bedrock:ListFoundationModelAgreementOffers",
          "bedrock:PutFoundationModelEntitlement",
          "bedrock:CreateFoundationModelAgreement"
        ]
        Resource = "*"
      },
      {
        Sid = "BedrockModelSubscriptions"
        Effect = "Allow"
        Action = [
          "aws-marketplace:Subscribe",
          "aws-marketplace:Unsubscribe"
        ]
        Resource = "*"
        Condition = {
          "ForAnyValue:StringEquals" = {
            "aws-marketplace:ProductId" = [
              "prod-cx7ovbu5wex7g",
              "prod-5oba7y7jpji56",
              "prod-4dlfvry4v5hbi",
              "b7568428-a1ab-46d8-bab3-37def50f6f6a",
              "38e55671-c3fe-4a44-9783-3584906e7cad"
            ]
          }
        }
      },
      {
        Sid = "DenyXXLInstances"
        Condition = {
          StringLike = {
            "ec2:InstanceType" = [
              "*6xlarge",
              "*8xlarge",
              "*10xlarge",
              "*12xlarge",
              "*16xlarge",
              "*18xlarge",
              "*24xlarge",
              "f1.4xlarge",
              "x1*",
              "z1*",
              "*metal"
            ]
          }
        }
        Resource = [
          "arn:aws:ec2:*:*:instance/*"
        ]
        Action = "ec2:RunInstances"
        Effect = "Deny"
      },
      {
        Sid = "DontBuyEC2ReservationsPlz"
        Resource = [
          "arn:aws:ec2:*:*:*"
        ]
        Action = [
          "ec2:ModifyReservedInstances",
          "ec2:PurchaseHostReservation",
          "ec2:PurchaseReservedInstancesOffering",
          "ec2:PurchaseScheduledInstances"
        ]
        Effect = "Deny"
      },
      {
        Sid = "DontBuyRDSReservationsPlz"
        Resource = [
          "arn:aws:rds:*:*:*"
        ]
        Action = [
          "rds:PurchaseReservedDBInstancesOffering"
        ]
        Effect = "Deny"
      },
      {
        Sid = "DontBuyDynamodbReservationsPlz"
        Resource = [
          "arn:aws:dynamodb:*:*:*"
        ]
        Action = [
          "dynamodb:PurchaseReservedCapacityOfferings"
        ]
        Effect = "Deny"
      },
      {
        Sid = "PassRoleToBedrock"
        Effect = "Allow"
        Action = [
          "iam:*"
        ]
        Resource = [
          "arn:aws:iam::*:role/*",
          "arn:aws:iam::*:policy/*"
        ]
      },
      {
        Sid = "PassRole"
        Resource = "arn:aws:iam::*:role/*"
        Action = "iam:PassRole"
        Effect = "Allow"
      },
      {
        Sid = "DenyBedrockModelAccessForOtherModels"
        Effect = "Deny"
        Action = [
          "bedrock:InvokeModel",
          "bedrock:InvokeModelWithResponseStream",
          "bedrock:ListFoundationModelAgreementOffers",
          "bedrock:PutFoundationModelEntitlement",
          "bedrock:CreateFoundationModelAgreement"
        ]
        Resource = [
          "arn:aws:bedrock:*::foundation-model/anthropic.claude-3-opus-20240229-v1:0",
          "arn:aws:bedrock:*::foundation-model/anthropic.claude-3-sonnet-20240229-v1:0",
          "arn:aws:bedrock:*::foundation-model/anthropic.claude-3-haiku-20240307-v1:0",
          "arn:aws:bedrock:*::foundation-model/anthropic.claude-sonnet-4-20250514-v1:0",
          "arn:aws:bedrock:*::foundation-model/anthropic.claude-v2:1",
          "arn:aws:bedrock:*::foundation-model/anthropic.claude-v2",
          "arn:aws:bedrock:*::foundation-model/anthropic.claude-instant-v1",
          "arn:aws:bedrock:*::foundation-model/meta*",
          "arn:aws:bedrock:*::foundation-model/mistral*",
          "arn:aws:bedrock:*::foundation-model/cohere.*",
          "arn:aws:bedrock:*::foundation-model/stability*",
          "arn:aws:bedrock:*::foundation-model/amazon.titan-image-*",
          "arn:aws:bedrock:*::foundation-model/amazon.titan-embed-image-v1"
        ]
      }
    ]
  })
}

# Attach the custom policy to the role
resource "aws_iam_role_policy_attachment" "bedrock_poc_attachment" {
  role       = aws_iam_role.bedrock_poc.name
  policy_arn = aws_iam_policy.bedrock_poc_policy.arn
}

# Attach AWS managed policy - AmazonSageMakerFullAccess
resource "aws_iam_role_policy_attachment" "sagemaker_full_access" {
  role       = aws_iam_role.bedrock_poc.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSageMakerFullAccess"
}

# Attach AWS managed policy - AmazonBedrockLimitedAccess
resource "aws_iam_role_policy_attachment" "bedrock_limited_access" {
  role       = aws_iam_role.bedrock_poc.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonBedrockLimitedAccess"
}

# Output the role ARN for reference
output "bedrock_poc_role_arn" {
  value       = aws_iam_role.bedrock_poc.arn
  description = "ARN of the Bedrock POC IAM role"
}
