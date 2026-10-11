############################ Roles del clúster y de los nodos ############################
data "aws_iam_policy_document" "eks_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["eks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "cluster" {
  name               = "${local.cluster_name}-cluster"
  assume_role_policy = data.aws_iam_policy_document.eks_assume.json
}

resource "aws_iam_role_policy_attachment" "cluster" {
  role       = aws_iam_role.cluster.name
  policy_arn = "arn:${data.aws_partition.current.partition}:iam::aws:policy/AmazonEKSClusterPolicy"
}

data "aws_iam_policy_document" "ec2_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "node" {
  name               = "${local.cluster_name}-node"
  assume_role_policy = data.aws_iam_policy_document.ec2_assume.json
}

resource "aws_iam_role_policy_attachment" "node" {
  for_each = toset([
    "AmazonEKSWorkerNodePolicy",
    "AmazonEKS_CNI_Policy",
    "AmazonEC2ContainerRegistryReadOnly", # el nodo hace pull de la imagen de ms-process-billing desde ECR
  ])
  role       = aws_iam_role.node.name
  policy_arn = "arn:${data.aws_partition.current.partition}:iam::aws:policy/${each.key}"
}

############################ EKS Pod Identity ############################
data "aws_iam_policy_document" "pod_identity_assume" {
  statement {
    actions = ["sts:AssumeRole", "sts:TagSession"]
    principals {
      type        = "Service"
      identifiers = ["pods.eks.amazonaws.com"]
    }
  }
}

# ms-process-billing: dedup/estado en DynamoDB y puente hacia la cola SQS de transacciones.
resource "aws_iam_role" "process_billing" {
  name               = "${local.cluster_name}-ms-process-billing"
  assume_role_policy = data.aws_iam_policy_document.pod_identity_assume.json
}

resource "aws_iam_role_policy" "process_billing" {
  name = "ms-process-billing"
  role = aws_iam_role.process_billing.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "DedupYEstadoDelCiclo"
        Effect   = "Allow"
        Action   = ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:Query", "dynamodb:ConditionCheckItem"]
        Resource = [local.process_billing_table_arn]
      },
      {
        # Reconciliacion del ciclo: Scan de solo lectura sobre la idempotencia de ms-comprobante-factura (sin escritura).
        Sid      = "ReconciliacionLecturaIdemComprobante"
        Effect   = "Allow"
        Action   = ["dynamodb:Scan"]
        Resource = [local.idem_comprobante_table_arn]
      },
      {
        Sid      = "PublicarEnColaDeTransacciones"
        Effect   = "Allow"
        Action   = ["sqs:SendMessage", "sqs:GetQueueAttributes", "sqs:GetQueueUrl"]
        Resource = [local.transactions_queue_arn]
      },
      {
        Sid      = "PublicarMetricasEnCloudWatch"
        Effect   = "Allow"
        Action   = ["cloudwatch:PutMetricData"]
        Resource = "*"
        Condition = {
          StringEquals = { "cloudwatch:namespace" = var.metrics_namespace }
        }
      },
    ]
  })

  depends_on = [terraform_data.base_inputs]
}

resource "aws_eks_pod_identity_association" "process_billing" {
  cluster_name    = aws_eks_cluster.this.name
  namespace       = var.app_namespace
  service_account = var.process_billing_service_account
  role_arn        = aws_iam_role.process_billing.arn

  depends_on = [aws_eks_addon.pod_identity_agent]
}

# Roles de los add-ons (EBS CSI y CloudWatch) vía Pod Identity.
resource "aws_iam_role" "ebs_csi" {
  name               = "${local.cluster_name}-ebs-csi"
  assume_role_policy = data.aws_iam_policy_document.pod_identity_assume.json
}

resource "aws_iam_role_policy_attachment" "ebs_csi" {
  role       = aws_iam_role.ebs_csi.name
  policy_arn = "arn:${data.aws_partition.current.partition}:iam::aws:policy/service-role/AmazonEBSCSIDriverPolicy"
}

resource "aws_iam_role" "cloudwatch_agent" {
  count              = var.enable_container_insights ? 1 : 0
  name               = "${local.cluster_name}-cloudwatch-agent"
  assume_role_policy = data.aws_iam_policy_document.pod_identity_assume.json
}

resource "aws_iam_role_policy_attachment" "cloudwatch_agent" {
  count      = var.enable_container_insights ? 1 : 0
  role       = aws_iam_role.cloudwatch_agent[0].name
  policy_arn = "arn:${data.aws_partition.current.partition}:iam::aws:policy/CloudWatchAgentServerPolicy"
}
