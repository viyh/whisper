variable "region" {
  description = "AWS region."
  type        = string
  default     = "us-east-1"
}

variable "domain_name" {
  description = "Domain to serve whisper on, e.g. whisper.example.com. Must be in the Route 53 hosted zone below."
  type        = string
}

variable "route53_zone_id" {
  description = "Route 53 hosted zone ID for the domain (used for the ACM certificate and the alias record)."
  type        = string
}

variable "name" {
  description = "Name prefix for all resources."
  type        = string
  default     = "whisper"
}

variable "image" {
  description = "Container image to run."
  type        = string
  default     = "docker.io/viyh/whisper:0.5.0"
}

variable "vpc_cidr" {
  description = "CIDR for the VPC created for whisper."
  type        = string
  default     = "10.42.0.0/16"
}

variable "task_cpu" {
  description = "Fargate task CPU units."
  type        = number
  default     = 512
}

variable "task_memory" {
  description = "Fargate task memory (MiB). 1024 is the least Fargate allows with 512 CPU units, and the password hashing runs in the browser, so it leaves plenty of room."
  type        = number
  default     = 1024
}
