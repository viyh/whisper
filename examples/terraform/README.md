# Terraform examples

Two minimal, self-contained deployments of Whisper with bucket storage. Both
generate a random `secret_key`, store the full `config.yaml` in the cloud's
secret manager, and set `trusted_proxy_count: 1` for the platform's front end.

| | [GCP](gcp) | [AWS](aws) |
|---|---|---|
| Compute | Cloud Run | ECS Fargate (ARM64) |
| HTTPS | Cloud Run domain mapping (managed cert) | ALB + ACM certificate |
| Storage | GCS bucket | S3 bucket |
| Config | Secret Manager, mounted as a file | Secrets Manager, injected as `WHISPER_CONFIG` |
| Network | Cloud Run managed | New VPC, 2 public subnets, no NAT gateway |

Both buckets block public access, keep no versions or soft-deleted copies of
deleted secrets, and expire objects after 31 days as a backstop for Whisper's
own cleanup (unread one-time secrets are kept for 30 days).

## Usage

```bash
cd gcp   # or aws
cp terraform.tfvars.example terraform.tfvars   # then edit
terraform init
terraform apply
```

**GCP**: you must have verified ownership of the domain in Google Search Console
with the account running Terraform. After `apply`, create the records from the
`dns_records` output; the certificate is issued once DNS resolves, which can
take a while. The `run_app_url` output works immediately.

**AWS**: the domain must be in a Route 53 hosted zone (`route53_zone_id`). The
certificate, its validation records, and the alias record are created for you.

## After deploying

Check the client IP that Whisper sees, since rate limiting depends on it:

1. Open the site and request any secret link. The request's log line
   (`[<ip>] ...`) should show your public IP, not a Google, AWS, or private
   address. If it does, raise `trusted_proxy_count` by one.
2. Send a request with a fake header and check it is ignored:
   ```bash
   curl -s -H 'X-Forwarded-For: 1.2.3.4' -H 'Content-Type: application/json' \
     -d '{"password":"x"}' https://<domain>/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
   ```
   The log should show your real IP, not `1.2.3.4`.

## Notes

- **Terraform state contains `secret_key`.** Use a remote backend with
  encryption and restricted access. Changing `secret_key` makes existing
  secrets unreadable.
- **One instance.** Rate limits are kept in memory per instance, so both
  examples run a single instance (`max_instances` / `desired_count`).
- **Memory.** Each concurrent password hash uses 128 MB. The defaults (512Mi on
  Cloud Run, 1 GB on Fargate) fit the image's default `WEB_THREADS=2`.
- **Cost.** Cloud Run scales to zero. The AWS example has fixed costs: the ALB
  and one always-on Fargate task.
- These are starting points, not hardened production modules: there is no WAF,
  no custom logging retention policy on GCP, and no remote state configuration.
