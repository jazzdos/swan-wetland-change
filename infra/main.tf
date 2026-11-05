resource "aws_s3_bucket" "outputs" {
  bucket = var.bucket_name
}

# Anonymous GetObject needs a bucket policy that is allowed to be public, so
# only the policy-related blocks are off. ACL blocks stay on: no object or
# bucket ACL can make anything public.
resource "aws_s3_bucket_public_access_block" "outputs" {
  bucket = aws_s3_bucket.outputs.id

  block_public_acls       = true
  ignore_public_acls      = true
  block_public_policy     = false
  restrict_public_buckets = false
}

resource "aws_s3_bucket_ownership_controls" "outputs" {
  bucket = aws_s3_bucket.outputs.id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

data "aws_iam_policy_document" "public_read" {
  statement {
    sid       = "PublicReadObjects"
    effect    = "Allow"
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.outputs.arn}/*"]

    principals {
      type        = "*"
      identifiers = ["*"]
    }
  }
}

resource "aws_s3_bucket_policy" "public_read" {
  bucket = aws_s3_bucket.outputs.id
  policy = data.aws_iam_policy_document.public_read.json

  depends_on = [aws_s3_bucket_public_access_block.outputs]
}

resource "aws_s3_bucket_cors_configuration" "outputs" {
  bucket = aws_s3_bucket.outputs.id

  cors_rule {
    allowed_methods = ["GET", "HEAD"]
    allowed_origins = ["*"]
    allowed_headers = ["*"]
    expose_headers  = ["ETag", "Content-Length", "Content-Range", "Accept-Ranges"]
    max_age_seconds = 3600
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
