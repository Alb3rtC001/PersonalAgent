"""
Configuración global del asistente.
"""

# Confianza mínima para ejecutar una acción. Por debajo de este valor,
# el dispatcher no ejecuta nada aunque la intención predicha no sea
# "ninguna" (el modelo puede estar dudando entre una acción real y
# "ninguna"). Ajustado con datos reales del entrenamiento: las
# predicciones correctas rondaban 0.85-1.00, así que 0.70 da margen
# de seguridad sin ser demasiado estricto.
UMBRAL_CONFIANZA = 0.75

# Cuando el grabador detecte automáticamente la parte variable (slot)
# de una plantilla grabada, pregunta al usuario para confirmarlo.
# Ponlo a False cuando confíes en que la detección funciona bien sola.
CONFIRMAR_SLOT_DETECTADO = True
