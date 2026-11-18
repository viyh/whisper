locals {
  bucket_name = coalesce(var.bucket_name, "${var.project_id}-${var.name}-secrets")
  config_path = "/etc/whisper"
}

resource "google_project_service" "services" {
  for_each = toset([
    "run.googleapis.com",
    "secretmanager.googleapis.com",
    "storage.googleapis.com",
  ])
  service            = each.value
  disable_on_destroy = false
}

# --- Storage -----------------------------------------------------------------

resource "google_storage_bucket" "secrets" {
  name                        = local.bucket_name
  location                    = var.region
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"

  # Deleted secrets must really be gone: no soft delete, no versioning.
  soft_delete_policy {
    retention_duration_seconds = 0
  }
  versioning {
    enabled = false
  }

  # Backstop for the in-app cleaner, which may rarely run on Cloud Run because
  # CPU is throttled between requests. Whisper keeps unread one-time secrets
  # for 30 days, so this must be longer than that.
  lifecycle_rule {
    condition {
      age = 31
    }
    action {
      type = "Delete"
    }
  }

  depends_on = [google_project_service.services]
}

# --- Identity ----------------------------------------------------------------

resource "google_service_account" "whisper" {
  account_id   = var.name
  display_name = "Whisper secret sharing"
}

# read/write/delete objects
resource "google_storage_bucket_iam_member" "objects" {
  bucket = google_storage_bucket.secrets.name
  role   = "roles/storage.objectUser"
  member = google_service_account.whisper.member
}

# storage.buckets.get, used at startup to fail fast on a missing bucket
resource "google_storage_bucket_iam_member" "bucket" {
  bucket = google_storage_bucket.secrets.name
  role   = "roles/storage.legacyBucketReader"
  member = google_service_account.whisper.member
}

# --- Config ------------------------------------------------------------------

resource "random_password" "secret_key" {
  length  = 48
  special = false
}

# The whole config.yaml lives in Secret Manager and is mounted as a file.
# Note: secret_key is also stored in Terraform state; protect your state.
resource "google_secret_manager_secret" "config" {
  secret_id = "${var.name}-config"
  replication {
    auto {}
  }
  depends_on = [google_project_service.services]
}

resource "google_secret_manager_secret_version" "config" {
  secret = google_secret_manager_secret.config.id
  secret_data = yamlencode({
    secret_key    = random_password.secret_key.result
    storage_class = "whisper.storage.gcp.gcs"
    storage_config = {
      gcp_project = var.project_id
      bucket_name = google_storage_bucket.secrets.name
      bucket_path = "secrets"
    }
    # Cloud Run's front end adds one X-Forwarded-For entry. Verify after
    # deploying: request logs should show your public IP. See the README.
    trusted_proxy_count = 1
  })
}

resource "google_secret_manager_secret_iam_member" "config" {
  secret_id = google_secret_manager_secret.config.id
  role      = "roles/secretmanager.secretAccessor"
  member    = google_service_account.whisper.member
}

# --- Cloud Run ---------------------------------------------------------------

resource "google_cloud_run_v2_service" "whisper" {
  name                = var.name
  location            = var.region
  ingress             = "INGRESS_TRAFFIC_ALL"
  deletion_protection = false

  # Public site: allow unauthenticated requests without an allUsers binding
  invoker_iam_disabled = true

  template {
    service_account = google_service_account.whisper.email

    # gunicorn runs 2 threads; Cloud Run queues the rest
    max_instance_request_concurrency = 10

    scaling {
      min_instance_count = 0
      max_instance_count = var.max_instances
    }

    containers {
      image = var.image

      ports {
        container_port = 8000
      }

      env {
        name  = "CONFIG_FILE"
        value = "${local.config_path}/config.yaml"
      }

      resources {
        limits = {
          cpu    = "1"
          memory = var.memory
        }
      }

      volume_mounts {
        name       = "config"
        mount_path = local.config_path
      }

      startup_probe {
        http_get {
          path = "/elb-status"
        }
      }

      liveness_probe {
        http_get {
          path = "/elb-status"
        }
      }
    }

    volumes {
      name = "config"
      secret {
        secret = google_secret_manager_secret.config.secret_id
        items {
          version = google_secret_manager_secret_version.config.version
          path    = "config.yaml"
        }
      }
    }
  }

  depends_on = [
    google_project_service.services,
    google_secret_manager_secret_iam_member.config,
    google_storage_bucket_iam_member.objects,
    google_storage_bucket_iam_member.bucket,
  ]
}

resource "google_cloud_run_domain_mapping" "whisper" {
  name     = var.domain_name
  location = var.region

  metadata {
    namespace = var.project_id
  }

  spec {
    route_name = google_cloud_run_v2_service.whisper.name
  }
}
