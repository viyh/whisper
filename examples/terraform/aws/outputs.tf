output "url" {
  description = "Whisper URL."
  value       = "https://${var.domain_name}/"
}

output "bucket" {
  value = aws_s3_bucket.secrets.id
}

output "log_group" {
  value = aws_cloudwatch_log_group.whisper.name
}
