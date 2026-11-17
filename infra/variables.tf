variable "bucket_name" {
  description = "Globally unique name of the S3 bucket that holds pipeline outputs and the STAC catalogue. The bucket is private: reads need AWS credentials (ADR 0017)."
  type        = string
}

variable "github_repository" {
  description = "GitHub repository allowed to assume the pipeline role, in the immutable subject form <owner>@<owner_id>/<name>@<repo_id>."
  type        = string

  validation {
    condition     = can(regex("^[A-Za-z0-9_.-]+@[0-9]+/[A-Za-z0-9_.-]+@[0-9]+$", var.github_repository))
    error_message = "The github_repository value must be in the form <owner>@<owner_id>/<name>@<repo_id> with numeric ids."
  }
}

variable "aws_region" {
  description = "AWS region for the bucket and the provider."
  type        = string
}

variable "create_oidc_provider" {
  description = "Create the account-wide GitHub OIDC provider. Set to false when the AWS account already has one, so it is looked up and left unmanaged."
  type        = bool
  default     = true
}
