output "region" {
  value = var.aws_region
}

output "cluster_name" {
  value = aws_eks_cluster.this.name
}

output "cluster_endpoint" {
  value = aws_eks_cluster.this.endpoint
}

output "cluster_ca_data" {
  value = aws_eks_cluster.this.certificate_authority[0].data
}

output "kubeconfig_command" {
  value = "aws eks update-kubeconfig --region ${var.aws_region} --name ${aws_eks_cluster.this.name}"
}

output "vpc_id" {
  value = aws_vpc.this.id
}

output "vpc_cidr" {
  value = var.vpc_cidr
}

output "subnet_ids" {
  value = aws_subnet.public[*].id
}

output "tags" {
  value = local.tags
}

output "app_namespace" {
  value = var.app_namespace
}

# Valores que debe consumir el stack BASE para adjuntar outbox-relay a la VPC (ver README, "Cambios en base").
output "relay_vpc_config" {
  description = "subnet_ids y security_group_ids para el vpc_config de la Lambda outbox-relay del stack base."
  value = {
    subnet_ids         = aws_subnet.public[*].id
    security_group_ids = [aws_security_group.relay.id]
  }
}

output "relay_security_group_id" {
  value = aws_security_group.relay.id
}

# Para el stack base (variables lambda_subnet_ids / lambda_security_group_ids). No hay subredes privadas
# (sin NAT): las Lambdas usan las subredes públicas, que da igual porque sus ENI nunca tienen IP pública.
output "lambda_subnet_ids" {
  value = aws_subnet.public[*].id
}

output "lambda_security_group_ids" {
  description = "SG compartido por todas las Lambdas que publican a Kafka."
  value       = [aws_security_group.relay.id]
}

output "container_insights_enabled" {
  value = var.enable_container_insights
}
