"""
Brújula Metodológica — motor de revisión automática de capítulos de
metodología de investigación.

Cómo funciona:
  1. El estudiante pega su capítulo de metodología (y opcionalmente su
     planteamiento del problema / objetivos, y su marco teórico) en la app.
  2. La app llama a la API de Claude (Anthropic) con una rúbrica de 13
     criterios inspirada en 25 años de experiencia evaluando trabajos de
     investigación en español.
  3. Devuelve un informe estructurado, descargable, con observaciones
     priorizadas.

Requiere una clave de API de Anthropic (https://console.anthropic.com/)
guardada como ANTHROPIC_API_KEY en los "Secrets" de Streamlit Community
Cloud (ver instrucciones de despliegue en el plan de negocio).
"""

import os
from datetime import datetime

import streamlit as st
from anthropic import Anthropic

# ----------------------------------------------------------------------
# Configuración
# ----------------------------------------------------------------------

st.set_page_config(
    page_title="Brújula Metodológica",
    page_icon="🧭",
    layout="centered",
)

PRICE_USD = 12
MODEL = "claude-sonnet-4-5"

RUBRIC_SYSTEM_PROMPT = """\
Eres una asesora experta en metodología de la investigación con más de 25
años de experiencia formando investigadores de pregrado, maestría y
doctorado en español. Tu trabajo es revisar capítulos de metodología de
tesis y trabajos de investigación con el mismo rigor y calidez con que lo
harías como profesora universitaria, señalando tanto lo que está bien
como lo que hay que corregir, de forma constructiva y específica (nunca
genérica).

Evalúa el texto que te entrega el usuario contra estos TRECE criterios,
en este orden:

1. Coherencia con el planteamiento del problema y los objetivos
2. Fundamentación teórica de las variables/dimensiones (el marco teórico
   desarrolla explícitamente las variables, dimensiones o categorías que
   aparecen en los objetivos de la investigación; no basta con mencionarlas
   de pasada)
3. Definición conceptual de las variables/dimensiones en el marco teórico
   (cada variable o dimensión está definida con claridad, citando autor y
   fuente, y no solo enunciada como título de subsección)
4. Pertinencia de las definiciones teóricas respecto al objeto de estudio
   (las teorías y definiciones citadas se conectan explícitamente con el
   caso particular que aborda la investigación —su contexto, población o
   fenómeno— y no quedan como teoría genérica desconectada del estudio)
5. Tipo y diseño de investigación (enfoque, alcance, diseño, justificación)
6. Población y muestra (definición, técnica de muestreo, tamaño, criterios)
7. Operacionalización de variables o categorías de estudio (definición
   operacional, dimensiones, indicadores e ítems en el capítulo de
   metodología)
8. Instrumentos de recolección de datos (validez, confiabilidad, ficha técnica)
9. Procedimiento (pasos claros, replicables, secuencia lógica)
10. Plan de análisis de datos (pertinencia respecto a hipótesis/preguntas)
11. Consideraciones éticas (consentimiento informado, confidencialidad)
12. Redacción académica (claridad, cohesión, registro impersonal)
13. Formato y citación (consistencia con APA vigente)

Si el usuario no proporcionó planteamiento del problema u objetivos,
evalúa el criterio 1 basándote solo en la coherencia interna del texto y
dilo explícitamente.

Si el usuario no proporcionó el marco teórico, evalúa los criterios 2, 3
y 4 únicamente a partir de lo que sea inferible del capítulo de
metodología (por ejemplo, la tabla de operacionalización o las variables
mencionadas en los objetivos), déjalo dicho explícitamente, y recomienda
en "Qué corregir primero" que comparta el marco teórico completo para una
evaluación más precisa de esos tres criterios.

Formato de salida (usa markdown):

## Resumen ejecutivo
2-3 frases: nivel general del capítulo y las 2-3 prioridades más urgentes.

## Revisión por criterio
Para cada uno de los 13 criterios, un subtítulo con el nombre del
criterio y un ícono de estado al inicio: ✅ (bien encaminado), ⚠️ (necesita
ajustes) o ❌ (ausente o con problema grave). Debajo, máximo 4-5 frases
específicas citando o parafraseando el texto del estudiante (no más de
dos citas textuales breves por criterio), nunca observaciones genéricas
que aplicarían a cualquier tesis. Sé precisa y concisa: prioriza la
observación más útil sobre la exhaustividad, y no repitas en un criterio
algo ya señalado en otro.

CRÍTICO — coherencia entre ícono y texto: el ícono debe reflejar
exactamente lo que dice el párrafo. Si el párrafo describe una ausencia
total o un problema grave (por ejemplo, "no existe un apartado de...",
"está completamente ausente"), el ícono DEBE ser ❌, nunca ✅ ni ⚠️. Si
describe que algo existe pero necesita ajustes o le falta un detalle
puntual, usa ⚠️. Usa ✅ solo si no hay pendientes sustanciales que
mencionar. Antes de escribir el ícono, decide primero qué vas a decir en
el párrafo y elige el ícono que corresponda a esa conclusión — nunca al
revés.

## Qué corregir primero
Lista priorizada (máximo 5 puntos) de las acciones concretas con mayor
impacto, ordenadas de más a menos urgente.

IMPORTANTE: Debes completar SIEMPRE las tres secciones, incluyendo los
13 criterios y "Qué corregir primero" al final. Si el espacio empieza a
faltar, sé más breve en los criterios menos críticos (los marcados ✅)
para dejar espacio a completar el informe entero — nunca dejes el
informe incompleto o cortado a mitad de una frase.

Sé honesta pero constructiva: el objetivo es que el estudiante llegue
mejor preparado ante su asesor o jurado, no desanimarlo.
"""


# ----------------------------------------------------------------------
# Acceso (control simple de pago)
# ----------------------------------------------------------------------

def get_valid_codes() -> set:
    """Lee los códigos de acceso válidos desde los Secrets de Streamlit.

    En Streamlit Community Cloud, agrega en Settings -> Secrets:

        ACCESS_CODES = "codigo-uno,codigo-dos,codigo-tres"

    Genera y entrega un código distinto por cada venta en Gumroad/Payhip
    (ambos permiten enviar automáticamente un código único al comprador).
    """
    raw = st.secrets.get("ACCESS_CODES", os.environ.get("ACCESS_CODES", ""))
    return {c.strip() for c in raw.split(",") if c.strip()}


def check_access(code: str) -> bool:
    valid_codes = get_valid_codes()
    if not valid_codes:
        # Si no se ha configurado ningún código todavía (fase de pruebas),
        # no bloquear el acceso.
        return True
    return code.strip() in valid_codes


# ----------------------------------------------------------------------
# Llamada al modelo
# ----------------------------------------------------------------------

def run_review(chapter_text: str, context_text: str, theory_text: str) -> str:
    api_key = st.secrets.get("ANTHROPIC_API_KEY", os.environ.get("ANTHROPIC_API_KEY"))
    if not api_key:
        raise RuntimeError(
            "Falta configurar ANTHROPIC_API_KEY en los Secrets de la app."
        )

    client = Anthropic(api_key=api_key)

    user_message = "## Capítulo de metodología a revisar\n\n" + chapter_text.strip()
    if context_text.strip():
        user_message += (
            "\n\n## Planteamiento del problema / objetivos (contexto)\n\n"
            + context_text.strip()
        )
    if theory_text.strip():
        user_message += (
            "\n\n## Marco teórico (contexto, para evaluar los criterios 2, 3 y 4)\n\n"
            + theory_text.strip()
        )

    response = client.messages.create(
        model=MODEL,
        max_tokens=6500,
        system=RUBRIC_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )
    return response.content[0].text


# ----------------------------------------------------------------------
# Interfaz
# ----------------------------------------------------------------------

st.title("🧭 Brújula Metodológica")
st.caption(
    "Revisión automática de tu capítulo de metodología, con los criterios "
    "de una asesora de investigación con 25 años de experiencia."
)

if "review_result" not in st.session_state:
    st.session_state.review_result = None

with st.expander("¿Cómo funciona y cuánto cuesta?", expanded=False):
    st.markdown(
        f"""
        1. Pega tu capítulo de metodología (y opcionalmente tu planteamiento
           del problema u objetivos, y tu marco teórico, para una revisión
           más precisa).
        2. Ingresa tu código de acceso (lo recibes al pagar).
        3. Recibe tu informe en menos de un minuto, con los 13 criterios
           evaluados y una lista priorizada de qué corregir primero.

        **Precio:** ${PRICE_USD} USD por revisión, pago único.
        """
    )

access_code = st.text_input(
    "Código de acceso",
    type="password",
    help="Lo recibes automáticamente al completar tu pago.",
)

context_text = st.text_area(
    "Planteamiento del problema / objetivos (opcional, mejora la revisión)",
    height=120,
    placeholder="Pega aquí tu planteamiento del problema y objetivos de investigación...",
)

theory_text = st.text_area(
    "Marco teórico (opcional, necesario para evaluar la fundamentación "
    "teórica de tus variables — criterios 2, 3 y 4)",
    height=200,
    placeholder="Pega aquí el texto completo de tu marco teórico (bases teóricas)...",
)

chapter_text = st.text_area(
    "Tu capítulo de metodología",
    height=320,
    placeholder="Pega aquí el texto completo de tu capítulo de metodología...",
)

col1, col2 = st.columns([1, 1])
with col1:
    submitted = st.button("Generar revisión", type="primary", use_container_width=True)

if submitted:
    if not chapter_text.strip():
        st.error("Pega el texto de tu capítulo de metodología antes de continuar.")
    elif not check_access(access_code):
        st.error(
            "Código de acceso no válido. Si ya pagaste y el código no funciona, "
            "escribe a pattybeco0765@gmail.com."
        )
    else:
        with st.spinner("Revisando tu capítulo con los 13 criterios..."):
            try:
                st.session_state.review_result = run_review(
                    chapter_text, context_text, theory_text
                )
            except Exception as exc:  # noqa: BLE001
                st.session_state.review_result = None
                st.error(f"No se pudo generar la revisión: {exc}")

if st.session_state.review_result:
    st.divider()
    st.markdown(st.session_state.review_result)
    st.download_button(
        "Descargar revisión (.md)",
        data=st.session_state.review_result,
        file_name=f"revision_metodologia_{datetime.now():%Y%m%d_%H%M}.md",
        mime="text/markdown",
        use_container_width=True,
    )

st.divider()
st.caption(
    "Brújula Metodológica no reemplaza a tu asesor de tesis: es una primera "
    "revisión para que llegues mejor preparado."
)
