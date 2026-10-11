# Los add-ons "por defecto" (vpc-cni, kube-proxy, coredns) ya existen al crear el clúster; aquí se adoptan
# (OVERWRITE) para fijarlos como add-ons administrados. Se crean DESPUÉS del node group.

resource "aws_eks_addon" "vpc_cni" {
  cluster_name                = aws_eks_cluster.this.name
  addon_name                  = "vpc-cni"
  resolve_conflicts_on_create = "OVERWRITE"
  resolve_conflicts_on_update = "OVERWRITE"
  depends_on                  = [aws_eks_node_group.main]
}

resource "aws_eks_addon" "kube_proxy" {
  cluster_name                = aws_eks_cluster.this.name
  addon_name                  = "kube-proxy"
  resolve_conflicts_on_create = "OVERWRITE"
  resolve_conflicts_on_update = "OVERWRITE"
  depends_on                  = [aws_eks_node_group.main]
}

resource "aws_eks_addon" "coredns" {
  cluster_name                = aws_eks_cluster.this.name
  addon_name                  = "coredns"
  resolve_conflicts_on_create = "OVERWRITE"
  resolve_conflicts_on_update = "OVERWRITE"
  depends_on                  = [aws_eks_node_group.main]
}

resource "aws_eks_addon" "pod_identity_agent" {
  cluster_name = aws_eks_cluster.this.name
  addon_name   = "eks-pod-identity-agent"
  depends_on   = [aws_eks_node_group.main]
}

# Driver EBS CSI: necesario para los PVC de Kafka. Los volúmenes llevan los tags del proyecto
# (extraVolumeTags) para poder encontrar huérfanos con el script de cierre.
resource "aws_eks_addon" "ebs_csi" {
  cluster_name = aws_eks_cluster.this.name
  addon_name   = "aws-ebs-csi-driver"

  configuration_values = jsonencode({
    controller = {
      extraVolumeTags = local.tags
    }
  })

  pod_identity_association {
    role_arn        = aws_iam_role.ebs_csi.arn
    service_account = "ebs-csi-controller-sa"
  }

  resolve_conflicts_on_create = "OVERWRITE"
  resolve_conflicts_on_update = "OVERWRITE"
  depends_on                  = [aws_eks_node_group.main, aws_eks_addon.pod_identity_agent]
}

############################ Container Insights (métricas/logs hacia CloudWatch) ############################
# Se pre-crean los log groups con retención corta y se destruyen junto con el stack
# (si no, el agente los crea sin expiración y quedan huérfanos).
resource "aws_cloudwatch_log_group" "container_insights" {
  for_each          = var.enable_container_insights ? toset(["performance", "application", "dataplane", "host"]) : toset([])
  name              = "/aws/containerinsights/${local.cluster_name}/${each.key}"
  retention_in_days = var.log_retention_days
}

resource "aws_eks_addon" "cloudwatch_observability" {
  count = var.enable_container_insights ? 1 : 0

  cluster_name = aws_eks_cluster.this.name
  addon_name   = "amazon-cloudwatch-observability"

  pod_identity_association {
    role_arn        = aws_iam_role.cloudwatch_agent[0].arn
    service_account = "cloudwatch-agent"
  }

  resolve_conflicts_on_create = "OVERWRITE"
  resolve_conflicts_on_update = "OVERWRITE"

  depends_on = [
    aws_eks_node_group.main,
    aws_eks_addon.pod_identity_agent,
    aws_cloudwatch_log_group.container_insights,
  ]
}

# Agente CloudWatch dedicado a Prometheus (kafka-exporter -> kafka_consumergroup_lag_sum). Pod Identity.
resource "aws_cloudwatch_log_group" "prometheus" {
  count             = var.enable_container_insights ? 1 : 0
  name              = "/aws/containerinsights/${local.cluster_name}/prometheus"
  retention_in_days = var.log_retention_days
}

resource "aws_eks_pod_identity_association" "cwagent_prometheus" {
  count           = var.enable_container_insights ? 1 : 0
  cluster_name    = aws_eks_cluster.this.name
  namespace       = "amazon-cloudwatch"
  service_account = "cwagent-prometheus"
  role_arn        = aws_iam_role.cloudwatch_agent[0].arn

  depends_on = [aws_eks_addon.pod_identity_agent]
}
