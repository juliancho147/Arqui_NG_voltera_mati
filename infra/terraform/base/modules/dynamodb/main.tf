variable "name_prefix" { type = string }

variable "tables" {
  description = "Mapa clave -> definición. Todas las claves son String."
  type = map(object({
    hash_key         = string
    range_key        = optional(string)
    ttl_attribute    = optional(string)
    stream_view_type = optional(string)
  }))
}

resource "aws_dynamodb_table" "this" {
  for_each = var.tables

  name         = "${var.name_prefix}-${each.key}"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = each.value.hash_key
  range_key    = each.value.range_key

  dynamic "attribute" {
    for_each = compact([each.value.hash_key, each.value.range_key])
    content {
      name = attribute.value
      type = "S"
    }
  }

  dynamic "ttl" {
    for_each = each.value.ttl_attribute == null ? [] : [each.value.ttl_attribute]
    content {
      attribute_name = ttl.value
      enabled        = true
    }
  }

  stream_enabled   = each.value.stream_view_type != null
  stream_view_type = each.value.stream_view_type
}

output "table_names" {
  value = { for k, t in aws_dynamodb_table.this : k => t.name }
}

output "table_arns" {
  value = { for k, t in aws_dynamodb_table.this : k => t.arn }
}

output "stream_arns" {
  value = { for k, t in aws_dynamodb_table.this : k => t.stream_arn if t.stream_enabled }
}
