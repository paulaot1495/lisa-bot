from anthropic import Anthropic

claude = Anthropic()

# ─────────────────────────────────────────
# AGENTE 1: REDACTOR
# Especializado en escribir cualquier texto
# ─────────────────────────────────────────
async def agente_redactor(peticion: str) -> str:
    respuesta = claude.messages.create(
        model="claude-haiku-4-5",
        max_tokens=1024,
        system="""Eres un redactor profesional experto. 
        Tu único trabajo es escribir textos de alta calidad.
        Emails, posts, mensajes, lo que te pidan.
        Siempre entregas el texto listo para usar, sin explicaciones extra.""",
        messages=[{"role": "user", "content": peticion}]
    )
    return respuesta.content[0].text


# ─────────────────────────────────────────
# AGENTE 2: RESUMEN
# Especializado en resumir y extraer lo clave
# ─────────────────────────────────────────
async def agente_resumen(peticion: str) -> str:
    respuesta = claude.messages.create(
        model="claude-haiku-4-5",
        max_tokens=512,
        system="""Eres un experto en síntesis de información.
        Tu único trabajo es resumir textos y extraer los puntos clave.
        Formato: primero un resumen de 2-3 líneas, luego bullets con lo más importante.
        Siempre en español, claro y directo. Que los bullets sean flechitas.""",
        messages=[{"role": "user", "content": peticion}]
    )
    return respuesta.content[0].text