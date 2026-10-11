terraform {
  required_version = ">= 1.7"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.80, < 7.0"
    }
  }

  # Estado local (igual que el stack base). El stack platform lo lee por ruta de archivo.
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = local.tags
  }
}
