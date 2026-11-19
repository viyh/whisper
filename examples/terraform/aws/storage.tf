resource "aws_s3_bucket" "secrets" {
  bucket_prefix = "${var.name}-secrets-"
}

resource "aws_s3_bucket_public_access_block" "secrets" {
  bucket                  = aws_s3_bucket.secrets.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "secrets" {
  bucket = aws_s3_bucket.secrets.id
  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "secrets" {
  bucket = aws_s3_bucket.secrets.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# Versioning is deliberately left off: deleted secrets must really be gone.

# Backstop for the in-app cleaner. Whisper keeps unread one-time secrets for
# 30 days, so this must be longer than that.
resource "aws_s3_bucket_lifecycle_configuration" "secrets" {
  bucket = aws_s3_bucket.secrets.id

  rule {
    id     = "expire-secrets"
    status = "Enabled"
    filter {
      prefix = "secrets/"
    }
    expiration {
      days = 31
    }
  }
}

# Refuse any request to the bucket that isn't made over TLS
data "aws_iam_policy_document" "secrets_tls_only" {
  statement {
    sid = "DenyInsecureTransport"
    effect = "Deny"
    actions = ["s3:*"]
    resources = [
      aws_s3_bucket.secrets.arn,
      "${aws_s3_bucket.secrets.arn}/*",
    ]
    principals {
      type = "*"
      identifiers = ["*"]
    }
    condition {
      test = "Bool"
      variable = "aws:SecureTransport"
      values = ["false"]
    }
  }
}

resource "aws_s3_bucket_policy" "secrets" {
  bucket = aws_s3_bucket.secrets.id
  policy = data.aws_iam_policy_document.secrets_tls_only.json

  # after the public access block: S3 can reject two access changes made to
  # one bucket at the same time
  depends_on = [aws_s3_bucket_public_access_block.secrets]
}
