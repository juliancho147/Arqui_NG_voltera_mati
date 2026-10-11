############################ VPC mínima SIN NAT Gateway ############################
# Justificación: un NAT Gateway cuesta ~0,045 USD/h + datos (más que 1/3 del presupuesto horario del stack).
# En su lugar los nodos van en subredes PÚBLICAS con IP pública (~0,005 USD/h c/u) y salen a internet
# (ECR, quay.io, Docker Hub, API de AWS) por el Internet Gateway. La exposición se controla con security
# groups: el SG del clúster (que usan los nodos) NO tiene ningún ingreso desde internet, solo desde sí mismo
# y desde la VPC (NodePort del NLB interno hacia Kafka). Es aceptable para un entorno efímero de laboratorio;
# NO es un patrón de producción.
resource "aws_vpc" "this" {
  cidr_block           = var.vpc_cidr
  enable_dns_support   = true
  enable_dns_hostnames = true

  tags = { Name = "${local.cluster_name}-vpc" }
}

resource "aws_internet_gateway" "this" {
  vpc_id = aws_vpc.this.id
  tags   = { Name = "${local.cluster_name}-igw" }
}

resource "aws_subnet" "public" {
  count = var.az_count

  vpc_id                  = aws_vpc.this.id
  availability_zone       = local.azs[count.index]
  cidr_block              = cidrsubnet(var.vpc_cidr, 8, count.index)
  map_public_ip_on_launch = true

  tags = {
    Name                                          = "${local.cluster_name}-public-${local.azs[count.index]}"
    "kubernetes.io/cluster/${local.cluster_name}" = "shared"
    "kubernetes.io/role/elb"                      = "1"
    # El NLB INTERNO de Kafka (listener "vpc") se coloca en estas subredes.
    "kubernetes.io/role/internal-elb" = "1"
  }
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.this.id
  tags   = { Name = "${local.cluster_name}-public" }
}

resource "aws_route" "internet" {
  route_table_id         = aws_route_table.public.id
  destination_cidr_block = "0.0.0.0/0"
  gateway_id             = aws_internet_gateway.this.id
}

resource "aws_route_table_association" "public" {
  count          = var.az_count
  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}

# Endpoints de tipo Gateway: gratis. DynamoDB lo necesita el relay (Lambda en VPC sin internet) para marcar
# el outbox; S3 acelera la descarga de capas de ECR.
resource "aws_vpc_endpoint" "dynamodb" {
  vpc_id            = aws_vpc.this.id
  service_name      = "com.amazonaws.${var.aws_region}.dynamodb"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = [aws_route_table.public.id]
  tags              = { Name = "${local.cluster_name}-dynamodb" }
}

resource "aws_vpc_endpoint" "s3" {
  vpc_id            = aws_vpc.this.id
  service_name      = "com.amazonaws.${var.aws_region}.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = [aws_route_table.public.id]
  tags              = { Name = "${local.cluster_name}-s3" }
}

############################ Security groups ############################
# SG para la Lambda outbox-relay (base) cuando se adjunte a esta VPC. Solo egreso: al rango NodePort del
# NLB interno de Kafka (VPC) y a DynamoDB (prefix list del endpoint). Sin ingreso.
resource "aws_security_group" "relay" {
  name        = "${local.cluster_name}-relay"
  description = "outbox-relay (Lambda) hacia Kafka interno y DynamoDB"
  vpc_id      = aws_vpc.this.id
  tags        = { Name = "${local.cluster_name}-relay" }
}

resource "aws_vpc_security_group_egress_rule" "relay_kafka" {
  security_group_id = aws_security_group.relay.id
  description       = "Kafka vpc listener (NLB interno a NodePort)"
  ip_protocol       = "tcp"
  from_port         = 9094
  to_port           = 9094
  cidr_ipv4         = var.vpc_cidr
}

resource "aws_vpc_security_group_egress_rule" "relay_nodeport" {
  security_group_id = aws_security_group.relay.id
  description       = "NodePort range (cliente IP preservado por el NLB)"
  ip_protocol       = "tcp"
  from_port         = 30000
  to_port           = 32767
  cidr_ipv4         = var.vpc_cidr
}

resource "aws_vpc_security_group_egress_rule" "relay_dynamodb" {
  security_group_id = aws_security_group.relay.id
  description       = "DynamoDB via gateway endpoint"
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
  prefix_list_id    = aws_vpc_endpoint.dynamodb.prefix_list_id
}

# El SG del clúster (nodos) recibe tráfico del NLB interno solo desde la VPC, en el rango NodePort.
# (La salida a internet de los nodos es el egreso "all" por defecto del SG.)
resource "aws_vpc_security_group_ingress_rule" "nodeport_from_vpc" {
  security_group_id = aws_eks_cluster.this.vpc_config[0].cluster_security_group_id
  description       = "NodePort range desde la VPC (NLB interno de Kafka + relay)"
  ip_protocol       = "tcp"
  from_port         = 30000
  to_port           = 32767
  cidr_ipv4         = var.vpc_cidr
}

# El SG de las Lambdas (relay + microservicios que publican eventos) también se admite por referencia de SG
# en los nodos (el NLB interno preserva la IP de origen, así que el SG de origen es el de la Lambda).
resource "aws_vpc_security_group_ingress_rule" "nodeport_from_lambdas" {
  security_group_id            = aws_eks_cluster.this.vpc_config[0].cluster_security_group_id
  description                  = "NodePort Kafka desde el SG de las Lambdas"
  ip_protocol                  = "tcp"
  from_port                    = 30000
  to_port                      = 32767
  referenced_security_group_id = aws_security_group.relay.id
}

############################ Endpoints de interfaz para Lambdas en VPC (sin NAT) ############################
# Las Lambdas adjuntas a la VPC no tienen internet. DynamoDB ya tiene endpoint gateway (gratis). X-Ray y SQS
# necesitan endpoint de interfaz (~0,01 USD/h por endpoint y AZ). Se crean en UNA sola subred (una AZ) para
# abaratar; el DNS privado los resuelve desde toda la VPC. Vacía la lista para no crearlos.
resource "aws_security_group" "endpoints" {
  count       = length(var.lambda_interface_endpoints) > 0 ? 1 : 0
  name        = "${local.cluster_name}-endpoints"
  description = "HTTPS desde la VPC hacia los endpoints de interfaz"
  vpc_id      = aws_vpc.this.id
  tags        = { Name = "${local.cluster_name}-endpoints" }
}

resource "aws_vpc_security_group_ingress_rule" "endpoints_https" {
  count             = length(var.lambda_interface_endpoints) > 0 ? 1 : 0
  security_group_id = aws_security_group.endpoints[0].id
  description       = "HTTPS desde la VPC"
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
  cidr_ipv4         = var.vpc_cidr
}

resource "aws_vpc_endpoint" "interface" {
  for_each            = toset(var.lambda_interface_endpoints)
  vpc_id              = aws_vpc.this.id
  service_name        = "com.amazonaws.${var.aws_region}.${each.key}"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = [aws_subnet.public[0].id]
  security_group_ids  = [aws_security_group.endpoints[0].id]
  private_dns_enabled = true
  tags                = { Name = "${local.cluster_name}-${each.key}" }
}

resource "aws_vpc_security_group_egress_rule" "relay_https_vpc" {
  security_group_id = aws_security_group.relay.id
  description       = "HTTPS a endpoints de interfaz (X-Ray/SQS)"
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
  cidr_ipv4         = var.vpc_cidr
}
