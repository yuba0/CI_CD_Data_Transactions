output "bucket" {
  description = "Bucket où déposer les fichiers : aws s3 cp data/ s3://<bucket>/incoming/ --recursive"
  value       = aws_s3_bucket.incoming.bucket
}

output "db_endpoint" {
  value = aws_db_instance.postgres.endpoint
}

output "db_password" {
  value     = random_password.db.result
  sensitive = true
}

output "vm_public_ip" {
  value = aws_instance.processor.public_ip
}
