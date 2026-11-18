variable "project_id" {
  description = "GCP project to deploy into."
  type        = string
}

variable "region" {
  description = "Region for Cloud Run and the bucket. Cloud Run domain mappings are only available in some regions."
  type        = string
  default     = "us-central1"
}

variable "domain_name" {
  description = "Domain to serve whisper on, e.g. whisper.example.com. You must have verified ownership of it (Google Search Console) with the identity running Terraform."
  type        = string
}

variable "name" {
  description = "Name for the Cloud Run service, service account and secret."
  type        = string
  default     = "whisper"
}

variable "image" {
  description = "Container image to run."
  type        = string
  default     = "docker.io/viyh/whisper:0.3.2"
}

variable "bucket_name" {
  description = "Globally unique name for the secrets bucket. Defaults to <project_id>-<name>-secrets."
  type        = string
  default     = null
}

variable "max_instances" {
  description = "Maximum Cloud Run instances. Rate limits are kept per instance, so 1 gives a single consistent limit."
  type        = number
  default     = 1
}

variable "memory" {
  description = "Memory per instance. Each concurrent password hash uses 128 MB; 512Mi fits the default 2 threads."
  type        = string
  default     = "512Mi"
}
