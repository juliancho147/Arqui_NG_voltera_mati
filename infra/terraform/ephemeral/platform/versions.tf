terraform {
  required_version = ">= 1.7"

  required_providers {
    helm = {
      source  = "hashicorp/helm"
      version = "~> 2.17"
    }
    kubectl = {
      # Fork mantenido de gavinbunney/kubectl. A diferencia de kubernetes_manifest, NO necesita que los CRDs
      # existan en el plan: por eso el plan/validate no depende de que Strimzi/KEDA estén instalados.
      source  = "alekc/kubectl"
      version = "~> 2.1"
    }
  }
}

locals {
  cluster = data.terraform_remote_state.cluster.outputs
}

provider "helm" {
  kubernetes {
    host                   = local.cluster.cluster_endpoint
    cluster_ca_certificate = base64decode(local.cluster.cluster_ca_data)
    exec {
      api_version = "client.authentication.k8s.io/v1beta1"
      command     = "aws"
      args        = ["eks", "get-token", "--cluster-name", local.cluster.cluster_name, "--region", local.cluster.region]
    }
  }
}

provider "kubectl" {
  host                   = local.cluster.cluster_endpoint
  cluster_ca_certificate = base64decode(local.cluster.cluster_ca_data)
  load_config_file       = false
  exec {
    api_version = "client.authentication.k8s.io/v1beta1"
    command     = "aws"
    args        = ["eks", "get-token", "--cluster-name", local.cluster.cluster_name, "--region", local.cluster.region]
  }
}
