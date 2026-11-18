# --- Config ------------------------------------------------------------------

resource "random_password" "secret_key" {
  length  = 48
  special = false
}

# The whole config.yaml lives in Secrets Manager and is injected as the
# WHISPER_CONFIG environment variable. Note: secret_key is also stored in
# Terraform state; protect your state.
resource "aws_secretsmanager_secret" "config" {
  name_prefix             = "${var.name}-config-"
  recovery_window_in_days = 0
}

resource "aws_secretsmanager_secret_version" "config" {
  secret_id = aws_secretsmanager_secret.config.id
  secret_string = yamlencode({
    secret_key    = random_password.secret_key.result
    storage_class = "whisper.storage.aws.s3"
    storage_config = {
      bucket_name = aws_s3_bucket.secrets.id
      bucket_path = "secrets"
    }
    # The ALB appends one X-Forwarded-For entry
    trusted_proxy_count = 1
  })
}

# --- IAM ---------------------------------------------------------------------

data "aws_iam_policy_document" "ecs_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

# Execution role: pull logs/secrets for ECS itself
resource "aws_iam_role" "execution" {
  name_prefix        = "${var.name}-exec-"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
}

resource "aws_iam_role_policy_attachment" "execution" {
  role       = aws_iam_role.execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

data "aws_iam_policy_document" "execution_secret" {
  statement {
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [aws_secretsmanager_secret.config.arn]
  }
}

resource "aws_iam_role_policy" "execution_secret" {
  role   = aws_iam_role.execution.id
  policy = data.aws_iam_policy_document.execution_secret.json
}

# Task role: what whisper itself can do (the secrets bucket only)
resource "aws_iam_role" "task" {
  name_prefix        = "${var.name}-task-"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
}

data "aws_iam_policy_document" "task_s3" {
  statement {
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.secrets.arn]
  }
  statement {
    actions = [
      "s3:GetObject",
      "s3:PutObject",
      "s3:DeleteObject",
      "s3:GetObjectTagging",
      "s3:PutObjectTagging",
    ]
    resources = ["${aws_s3_bucket.secrets.arn}/*"]
  }
}

resource "aws_iam_role_policy" "task_s3" {
  role   = aws_iam_role.task.id
  policy = data.aws_iam_policy_document.task_s3.json
}

# --- ECS ---------------------------------------------------------------------

resource "aws_cloudwatch_log_group" "whisper" {
  name              = "/ecs/${var.name}"
  retention_in_days = 30
}

resource "aws_ecs_cluster" "whisper" {
  name = var.name
}

resource "aws_ecs_task_definition" "whisper" {
  family                   = var.name
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.task_cpu
  memory                   = var.task_memory
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task.arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "ARM64"
  }

  container_definitions = jsonencode([{
    name      = "whisper"
    image     = var.image
    essential = true

    portMappings = [{ containerPort = 8000, protocol = "tcp" }]

    environment = [
      { name = "AWS_DEFAULT_REGION", value = var.region },
    ]
    secrets = [
      { name = "WHISPER_CONFIG", valueFrom = aws_secretsmanager_secret.config.arn },
    ]

    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.whisper.name
        awslogs-region        = var.region
        awslogs-stream-prefix = "whisper"
      }
    }
  }])
}

resource "aws_ecs_service" "whisper" {
  name            = var.name
  cluster         = aws_ecs_cluster.whisper.id
  task_definition = aws_ecs_task_definition.whisper.arn
  launch_type     = "FARGATE"
  # Rate limits are kept per task, so 1 gives a single consistent limit
  desired_count = 1

  network_configuration {
    subnets          = aws_subnet.public[*].id
    security_groups  = [aws_security_group.task.id]
    assign_public_ip = true
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.whisper.arn
    container_name   = "whisper"
    container_port   = 8000
  }

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  # the config secret must have a value before the first task starts
  depends_on = [aws_lb_listener.https, aws_secretsmanager_secret_version.config]
}
