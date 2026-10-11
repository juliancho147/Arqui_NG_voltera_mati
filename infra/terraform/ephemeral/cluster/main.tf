locals {
  tags = merge({
    proyecto    = "voltera"
    experimento = "exp2-eda"
    stack       = "efimero"
  }, var.tags)

  cluster_name = var.name_prefix
  azs          = slice(data.aws_availability_zones.available.names, 0, var.az_count)

  base = try(data.terraform_remote_state.base[0].outputs, {})

  process_billing_table_arn  = try(coalesce(var.base_overrides.process_billing_table_arn, try(local.base.dynamodb_tables.arns["process-billing"], null)), null)
  idem_comprobante_table_arn = try(coalesce(var.base_overrides.idem_comprobante_table_arn, try(local.base.dynamodb_tables.arns["idem-comprobante"], null)), null)
  transactions_queue_arn     = try(coalesce(var.base_overrides.transactions_queue_arn, try(local.base.sqs.transacciones.arn, null)), null)
}

data "aws_availability_zones" "available" {
  state = "available"
  filter {
    name   = "opt-in-status"
    values = ["opt-in-not-required"]
  }
}

data "aws_partition" "current" {}

# Estado del stack base (local). Solo se necesitan ARNs para el rol de ms-process-billing.
data "terraform_remote_state" "base" {
  count   = var.base_state_path == null ? 0 : 1
  backend = "local"
  config = {
    path = var.base_state_path
  }
}

resource "terraform_data" "base_inputs" {
  lifecycle {
    precondition {
      condition     = local.process_billing_table_arn != null && local.transactions_queue_arn != null && local.idem_comprobante_table_arn != null
      error_message = "Faltan ARNs del stack base. Aplica base primero (y revisa base_state_path) o pasa base_overrides."
    }
  }
}
