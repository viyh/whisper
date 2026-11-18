output "url" {
  description = "Whisper URL (HTTPS is provisioned automatically once DNS is in place)."
  value       = "https://${var.domain_name}/"
}

output "run_app_url" {
  description = "Cloud Run's own URL, useful for testing before DNS is ready."
  value       = google_cloud_run_v2_service.whisper.uri
}

output "dns_records" {
  description = "DNS records to create for the domain mapping."
  value = [
    for r in google_cloud_run_domain_mapping.whisper.status[0].resource_records :
    { name = r.name, type = r.type, value = r.rrdata }
  ]
}

output "bucket" {
  value = google_storage_bucket.secrets.name
}
