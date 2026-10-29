variable "bucket_name" {
  description = "Globally unique name of the public-read S3 bucket that holds pipeline outputs and the STAC catalogue."
  type        = string
}

variable "github_repository" {
  description = "GitHub repository allowed to assume the pipeline role, as owner/name."
  type        = string

  validation {
    condition     = can(regex("^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", var.github_repository))
    error_message = "github_repository must be in owner/name form."
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
