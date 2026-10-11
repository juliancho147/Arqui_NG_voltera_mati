# Valores pensados SOLO para acelerar el Exp. 2 (copiar a experiment.tfvars y usar con -var-file).
# Los defaults de variables.tf siguen siendo los seguros.

# Con el default (6 x 30 s = 180 s) y maxReceiveCount=3, un mensaje tarda ~9 min en llegar a la DLQ.
# Con 40 s (>= timeout de la Lambda de 30 s) llega en ~2 min.
# RIESGO: con 40 s un throttle/reintento puede hacer que el mensaje se entregue dos veces;
# la idempotencia por facturaId (ms-comprobante-factura) lo cubre.
comprobantes_queue_visibility_timeout = 40
