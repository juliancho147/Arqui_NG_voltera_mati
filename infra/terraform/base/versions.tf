terraform {
  required_version = ">= 1.7"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.60, < 7.0"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.4"
    }
  }

  # Estado local por ahora (decisión del usuario). Migrar a S3 + lock más adelante.
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = local.tags
  }
}
