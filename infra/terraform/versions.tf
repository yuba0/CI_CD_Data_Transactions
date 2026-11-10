terraform {
  required_version = ">= 1.6"
  required_providers {
    aws    = { source = "hashicorp/aws", version = "~> 6.0" }
    random = { source = "hashicorp/random", version = "~> 3.6" }
  }
  # Pour travailler à plusieurs, stocker l'état dans un bucket S3 :
  # backend "s3" { bucket = "mon-tfstate" key = "pipeline/terraform.tfstate" region = "eu-west-3" }
}

provider "aws" {
  region = var.region
  default_tags {
    tags = { Project = var.project, ManagedBy = "terraform" }
  }
}
