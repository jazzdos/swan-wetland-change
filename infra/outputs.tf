output "role_arn" {
  description = "ARN of the role the pipeline assumes through GitHub OIDC. Set as the AWS_ROLE_ARN repository variable."
  value       = aws_iam_role.pipeline.arn
}

output "bucket_url" {
  description = "https URL of the bucket (virtual-hosted style, regional endpoint). The bucket is private under ADR 0017, so links to it need AWS credentials or a presigned URL."
  value       = "https://${aws_s3_bucket.outputs.bucket}.s3.${var.aws_region}.amazonaws.com"
}
