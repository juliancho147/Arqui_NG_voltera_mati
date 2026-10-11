# Perfil RAPIDO del Exp. 2 (corrida de 3-5 min): la DLQ de comprobantes se llena en ~20 s (2 intentos x 10 s).
# RIESGO: con visibility corta un reintento puede entregar el mensaje dos veces; la idempotencia por facturaId lo cubre.
comprobantes_queue_visibility_timeout = 10
comprobante_timeout_seconds           = 8
max_receive_count                     = 2
