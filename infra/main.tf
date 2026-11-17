resource "aws_s3_bucket" "outputs" {
  bucket = var.bucket_name
}

# The bucket is private: all four settings are on, there is no bucket policy
# and no CORS rule, so objects are readable only with AWS credentials. The
# decision is ADR 0017 (docs/decisions/0017-private-output-bucket-again.md,
# which supersedes 0016 and keeps the configuration of 0011).
resource "aws_s3_bucket_public_access_block" "outputs" {
  bucket = aws_s3_bucket.outputs.id

  block_public_acls       = true
  ignore_public_acls      = true
  block_public_policy     = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "outputs" {
  bucket = aws_s3_bucket.outputs.id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

# A killed or failed write leaves multipart parts that S3 keeps and bills
# until they are aborted. The empty filter applies the rule to the whole bucket.
resource "aws_s3_bucket_lifecycle_configuration" "outputs" {
  bucket = aws_s3_bucket.outputs.id

  rule {
    id     = "abort-incomplete-multipart-uploads"
    status = "Enabled"

    filter {}

    abort_incomplete_multipart_upload {
      days_after_initiation = 1
    }
  }
}

# An AWS account holds one GitHub OIDC provider and other repositories usually
# share it. Set create_oidc_provider = false to look up the existing provider
# instead of managing it, so destroying this module never deletes it.
resource "aws_iam_openid_connect_provider" "github" {
  count = var.create_oidc_provider ? 1 : 0

  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]
}

data "aws_iam_openid_connect_provider" "github" {
  count = var.create_oidc_provider ? 0 : 1

  url = "https://token.actions.githubusercontent.com"
}

locals {
  github_oidc_provider_arn = (
    var.create_oidc_provider
    ? aws_iam_openid_connect_provider.github[0].arn
    : data.aws_iam_openid_connect_provider.github[0].arn
  )
}

data "aws_iam_policy_document" "pipeline_trust" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [local.github_oidc_provider_arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:${var.github_repository}:ref:refs/heads/main"]
    }
  }
}

resource "aws_iam_role" "pipeline" {
  name               = "swan-wetland-change-pipeline"
  assume_role_policy = data.aws_iam_policy_document.pipeline_trust.json

  # The pipeline job runs up to 120 minutes (timeout-minutes in
  # .github/workflows/pipeline.yml), and the 3600 s default session expires
  # mid-run. 3 hours covers the job plus the setup steps before the
  # credentials are minted. role-duration-seconds in pipeline.yml must equal
  # this value.
  max_session_duration = 10800
}

data "aws_iam_policy_document" "pipeline_access" {
  statement {
    sid       = "ListBucket"
    effect    = "Allow"
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.outputs.arn]
  }

  statement {
    sid       = "ReadWriteDeleteObjects"
    effect    = "Allow"
    actions   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
    resources = ["${aws_s3_bucket.outputs.arn}/*"]
  }
}

resource "aws_iam_role_policy" "pipeline" {
  name   = "bucket-access"
  role   = aws_iam_role.pipeline.id
  policy = data.aws_iam_policy_document.pipeline_access.json
}
