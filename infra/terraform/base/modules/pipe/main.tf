variable "name" { type = string }
variable "source_queue_arn" { type = string }
variable "state_machine_arn" { type = string }
variable "sfn_type" { type = string }

data "aws_iam_policy_document" "assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["pipes.amazonaws.com"]
    }
  }
}

data "aws_iam_policy_document" "inline" {
  statement {
    sid       = "LeerCola"
    actions   = ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes"]
    resources = [var.source_queue_arn]
  }
  statement {
    sid       = "IniciarEjecucion"
    actions   = ["states:StartExecution"]
    resources = [var.state_machine_arn]
  }
}

resource "aws_iam_role" "this" {
  name               = "${var.name}-pipe-role"
  assume_role_policy = data.aws_iam_policy_document.assume.json
}

resource "aws_iam_role_policy" "this" {
  name   = "minimo-privilegio"
  role   = aws_iam_role.this.id
  policy = data.aws_iam_policy_document.inline.json
}

resource "aws_pipes_pipe" "this" {
  name     = var.name
  role_arn = aws_iam_role.this.arn
  source   = var.source_queue_arn
  target   = var.state_machine_arn

  source_parameters {
    sqs_queue_parameters {
      batch_size = 1
    }
  }

  target_parameters {
    step_function_state_machine_parameters {
      # Standard solo admite FIRE_AND_FORGET; Express puede esperar la respuesta (los fallos vuelven a la cola).
      invocation_type = var.sfn_type == "STANDARD" ? "FIRE_AND_FORGET" : "REQUEST_RESPONSE"
    }
  }

  depends_on = [aws_iam_role_policy.this]
}

output "pipe_arn" { value = aws_pipes_pipe.this.arn }
output "role_arn" { value = aws_iam_role.this.arn }
