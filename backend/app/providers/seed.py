"""
Semilla de la taxonomía: modelos, movimientos de cámara y estilos visuales.

El catálogo vive **aquí en Python** y `backend/seeds/taxonomy.sql` se genera desde este
fichero (`python -m app.providers.seed --emit-sql`). Podría haber sido al revés, pero
`credits_per_unit` se deriva de `cost_per_second` con `credits_per_usd` y
`credit_margin` de la config, y SQL no puede leer la config. Con el catálogo en SQL a
mano, cambiar el margen obligaría a recalcular treinta números en un fichero de texto,
que es la clase de tarea que sale mal en silencio.

Sobre los precios: el informe 06 marca cada cifra con [V] verificado, [S] secundario o
[I] inferido. Esa marca viaja hasta aquí en `price_confidence` y acaba en un comentario
del SQL generado, porque un precio [S] equivocado no da error — solo margen negativo.

Los `description_llm` están escritos para decidir, no para describir. El modelo ya ve
resolución y duración en el JSON Schema; lo que no puede deducir de ahí es cuándo un
plano pide Kling en vez de Veo. Repetir specs en la descripción es gastar contexto en
información que ya está estructurada.
"""

from __future__ import annotations

import argparse
import math
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import ROUND_CEILING, Decimal
from typing import Literal

PriceConfidence = Literal["verified", "secondary", "inferred"]


@dataclass(slots=True, frozen=True)
class SeedModel:
    id: str
    family: str
    provider: str
    modality: str
    label: str
    description_llm: str
    cost_per_second: Decimal
    """
    Coste de API por segundo de vídeo. **Derivado** cuando el proveedor factura por clip:
    en ese caso no se escribe a mano, lo calcula `resolve_cost_per_second()` a partir de
    `cost_per_clip`. Ver ahí el porqué.
    """
    price_confidence: PriceConfidence
    cost_per_image: Decimal | None = None
    cost_per_clip: Decimal | None = None
    """
    Tarifa **plana por clip**, para los proveedores que facturan así (MiniMax).

    Existe porque el modelo de precio por segundo no puede representar una tarifa plana
    sin perder dinero por un lado o cobrar de más por el otro, y hasta ahora se estaba
    perdiendo. MiniMax cobra lo mismo por un clip de 6 s que por uno de 10 s; el seed lo
    modeló dividiendo la tarifa entre la duración máxima, así que a 6 s —el mínimo, y la
    duración que más se pide— se cobraba el 60 % de lo que el proveedor nos factura al
    100 %. Con el margen de 1.6 aplicado encima, `hailuo-2.3` salía a 0.96x: cada plano
    de 6 s se generaba **por debajo de coste**, en silencio y sin ningún error.
    """
    min_duration_s: float | None = None
    max_duration_s: float | None = None
    resolutions: tuple[str, ...] = ()
    aspects: tuple[str, ...] = ("16:9", "9:16", "1:1")
    supports_i2v: bool = False
    supports_last_frame: bool = False
    supports_char_ref: bool = False
    supports_audio: bool = False
    min_plan: str = "free"
    status: str = "active"
    sunset_at: str | None = None
    sort: int = 100
    note: str | None = None
    """Se emite como comentario SQL. Sirve para dejar constancia de lo que no cuadra."""


@dataclass(slots=True, frozen=True)
class SeedMotion:
    id: str
    label: str
    description_llm: str
    category: str
    supports_strength: bool = True
    sort: int = 100


@dataclass(slots=True, frozen=True)
class SeedStyle:
    id: str
    dimension: str
    label: str
    description_llm: str
    prompt_fragment: str
    sort: int = 100


# =========================================================================== #
# Modelos                                                                     #
# =========================================================================== #
#
# Cobertura frente a la UI (`modelFamilies` en src/main.jsx): se siembran las familias
# que tienen adaptador. Quedan fuera a propósito Grok Imagine, HappyHorse, Luma y Pika:
# la UI las lista, pero no hay adaptador ni API verificada para ellas, y sembrarlas
# haría que el LLM las ofreciera y que el submit fallara con UnknownProviderError —
# peor experiencia que no ofrecerlas. Runway sí se siembra pese a no tener adaptador,
# porque su sunset (2026-07-30) es justamente lo que hay que tener registrado.

MODELS: tuple[SeedModel, ...] = (
    # --- Google -------------------------------------------------------------
    SeedModel(
        id="veo-3.1-generate-preview",
        family="Google Veo",
        provider="google",
        modality="video",
        label="Google Veo 3.1",
        description_llm=(
            "Elige este cuando el plano tenga que quedar bien a la primera y el "
            "presupuesto lo permita: es el más fiable en fisica, manos y texto legible, "
            "y el unico que genera dialogo y ambiente sincronizados sin pasar por una "
            "capa de audio aparte. Es de los caros, asi que reservalo para los planos "
            "que el espectador va a mirar de verdad, no para pruebas de encuadre."
        ),
        cost_per_second=Decimal("0.40"),
        price_confidence="verified",
        min_duration_s=4,
        max_duration_s=8,
        resolutions=("720p", "1080p", "4K"),
        aspects=("16:9", "9:16"),
        supports_i2v=True,
        supports_last_frame=True,
        supports_char_ref=True,
        supports_audio=True,
        min_plan="pro",
        sort=10,
    ),
    SeedModel(
        id="veo-3.1-lite-generate-preview",
        family="Google Veo",
        provider="google",
        modality="video",
        label="Google Veo 3.1 Lite",
        description_llm=(
            "El caballo de batalla: ocho veces mas barato que Veo 3.1 y con el mismo "
            "criterio de composicion, a cambio de menos detalle fino y menos aguante en "
            "movimiento rapido. Usalo para iterar encuadre y ritmo, y sube a Veo 3.1 "
            "solo el plano que ya sabes que se queda."
        ),
        cost_per_second=Decimal("0.05"),
        price_confidence="verified",
        min_duration_s=4,
        max_duration_s=8,
        resolutions=("720p", "1080p"),
        aspects=("16:9", "9:16"),
        supports_i2v=True,
        supports_last_frame=True,
        supports_char_ref=True,
        supports_audio=True,
        sort=11,
    ),
    SeedModel(
        # Sustituye a `veo-3-fast`, que apuntaba a Veo 3.0: apagado el 30 de junio de
        # 2026. Ofrecerlo era prometer al usuario un modelo que ya no responde.
        id="veo-3.1-fast-generate-preview",
        family="Google Veo",
        provider="google",
        modality="video",
        label="Google Veo 3.1 Fast",
        description_llm=(
            "Generacion mas rapida de la familia, pensada para tanteo. Si el usuario "
            "esta explorando ideas y va a descartar la mayoria, esto le da respuesta en "
            "el menor tiempo posible. No lo uses para el corte final."
        ),
        cost_per_second=Decimal("0.10"),
        price_confidence="verified",
        min_duration_s=4,
        max_duration_s=8,
        resolutions=("720p", "1080p", "4K"),
        aspects=("16:9", "9:16"),
        supports_i2v=True,
        supports_last_frame=True,
        supports_char_ref=True,
        supports_audio=True,
        sort=12,
    ),
    SeedModel(
        id="gemini-omni-flash",
        family="Gemini",
        provider="google",
        modality="video",
        label="Gemini Omni Flash",
        description_llm=(
            "El mejor del catalogo manteniendo la misma cara entre planos distintos: "
            "Google lo posiciona explicitamente por encima de Veo 3.1 en consistencia de "
            "personaje y en refinamiento iterativo. Es la eleccion por defecto cuando la "
            "secuencia sigue a un personaje a lo largo de varios planos y la continuidad "
            "importa mas que el acabado de cada uno."
        ),
        cost_per_second=Decimal("0.10"),
        price_confidence="verified",
        min_duration_s=4,
        max_duration_s=10,
        resolutions=("720p",),
        supports_i2v=True,
        supports_char_ref=True,
        supports_audio=True,
        sort=13,
    ),
    # --- OpenAI -------------------------------------------------------------
    SeedModel(
        id="sora-2",
        family="OpenAI Sora",
        provider="openai",
        modality="video",
        label="OpenAI Sora 2",
        description_llm=(
            "Fuerte en escenas con varios personajes actuando a la vez y con dialogo "
            "que suena natural. AVISO: OpenAI apaga toda la Videos API el 24 de "
            "septiembre de 2026. No lo propongas para un proyecto que el usuario vaya a "
            "seguir editando despues de esa fecha; si ya hay planos hechos con el, "
            "avisale de que no podra regenerarlos."
        ),
        cost_per_second=Decimal("0.10"),
        price_confidence="verified",
        min_duration_s=4,
        max_duration_s=12,
        resolutions=("720p",),
        aspects=("16:9", "9:16"),
        supports_i2v=True,
        supports_char_ref=True,
        supports_audio=True,
        status="deprecated",
        sunset_at="2026-09-24",
        sort=20,
    ),
    SeedModel(
        id="sora-2-pro",
        family="OpenAI Sora",
        provider="openai",
        modality="video",
        label="OpenAI Sora 2 Pro",
        description_llm=(
            "Version larga y de mas resolucion de Sora 2: admite hasta 25 segundos, lo "
            "que lo hace el unico del catalogo capaz de sostener una escena entera sin "
            "cortar. Comparte la fecha de apagado del 24 de septiembre de 2026, asi que "
            "vale para entregar ya, no para construir encima."
        ),
        cost_per_second=Decimal("0.30"),
        price_confidence="verified",
        min_duration_s=10,
        max_duration_s=25,
        resolutions=("720p", "1024p", "1080p"),
        aspects=("16:9", "9:16"),
        supports_i2v=True,
        supports_char_ref=True,
        supports_audio=True,
        min_plan="pro",
        status="deprecated",
        sunset_at="2026-09-24",
        sort=21,
    ),
    # --- OpenAI (imagen) ----------------------------------------------------
    #
    # Es el único bloque de imagen que funciona con la clave que el usuario ya tiene, y
    # por tanto la puerta de entrada real al producto: los elements (personajes,
    # localizaciones, objetos) son imágenes, y sin crearlas no hay continuidad que probar.
    #
    # PRECIOS: la página oficial ya no publica coste por imagen; solo $/1M tokens y una
    # calculadora. Las cifras de abajo son de fuentes secundarias de julio de 2026 y son
    # el precio de calidad MEDIA a 1024x1024. El adaptador ajusta por calidad y tamaño en
    # `estimate_cost`, así que esto es el punto de referencia, no la tarifa completa.
    SeedModel(
        id="gpt-image-2",
        family="OpenAI GPT Image",
        provider="openai_image",
        modality="image",
        label="OpenAI GPT Image 2",
        description_llm=(
            "Empieza por aqui para CREAR un element: la cara de un personaje, una "
            "localizacion o un objeto que despues va a repetirse en toda la pieza. "
            "Tambien es el que hay que usar para generar el fotograma de referencia que "
            "luego se anima con un modelo de video. Entiende instrucciones largas y "
            "literales mejor que ningun otro del catalogo, asi que es el indicado cuando "
            "el usuario describe con precision lo que quiere ver. Si le pasas elements "
            "existentes, los toma como referencia y conserva la identidad en vez de "
            "inventar una cara nueva, que es lo que da continuidad entre vinetas."
        ),
        cost_per_second=Decimal("0.053"),
        cost_per_image=Decimal("0.053"),
        price_confidence="secondary",
        resolutions=("1024x1024", "1536x1024", "1024x1536"),
        aspects=("1:1", "16:9", "9:16"),
        supports_char_ref=True,
        sort=1,
        note=(
            "Precio de calidad media a 1024x1024 segun fuentes secundarias (jul 2026): "
            "low $0.006 / medium $0.053 / high $0.211. OpenAI factura por tokens de "
            "imagen de salida, no por imagen; ver _PRICE_BY_QUALITY en openai_image.py."
        ),
    ),
    SeedModel(
        id="gpt-image-1.5",
        family="OpenAI GPT Image",
        provider="openai_image",
        modality="image",
        label="OpenAI GPT Image 1.5",
        description_llm=(
            "Generacion anterior a GPT Image 2, algo mas barata y con el mismo criterio "
            "de composicion. Sirve como plan B si GPT Image 2 esta saturado, y como "
            "escalon intermedio cuando el usuario quiere iterar varias veces sobre la "
            "misma idea antes de fijar el element definitivo. Para el element que se "
            "queda, sube a GPT Image 2."
        ),
        cost_per_second=Decimal("0.042"),
        cost_per_image=Decimal("0.042"),
        price_confidence="inferred",
        resolutions=("1024x1024", "1536x1024", "1024x1536"),
        aspects=("1:1", "16:9", "9:16"),
        supports_char_ref=True,
        sort=2,
        note="Precio INFERIDO por analogia con gpt-image-2; no hay tarifa por imagen publicada.",
    ),
    SeedModel(
        id="gpt-image-1-mini",
        family="OpenAI GPT Image",
        provider="openai_image",
        modality="image",
        label="OpenAI GPT Image 1 Mini",
        description_llm=(
            "El escalon barato de la familia. Es una herramienta de tanteo: sirve para "
            "comprobar si una descripcion de personaje o de localizacion produce algo "
            "parecido a lo que el usuario tiene en la cabeza, antes de gastar en el "
            "modelo bueno. No lo uses para el element definitivo, porque la cara que "
            "salga de aqui es la que habra que mantener en todos los planos siguientes."
        ),
        cost_per_second=Decimal("0.015"),
        cost_per_image=Decimal("0.015"),
        price_confidence="inferred",
        resolutions=("1024x1024", "1536x1024", "1024x1536"),
        aspects=("1:1", "16:9", "9:16"),
        supports_char_ref=True,
        sort=3,
        note="Precio INFERIDO. Oficial: $2.50/1M tokens de entrada, frente a $8.00 de los grandes.",
    ),
    SeedModel(
        id="gpt-image-1",
        family="OpenAI GPT Image",
        provider="openai_image",
        modality="image",
        label="OpenAI GPT Image 1",
        description_llm=(
            "RETIRADO POR EL PROVEEDOR el 23 de octubre de 2026. No lo propongas. Si el "
            "usuario lo pide por nombre, explicale que OpenAI lo apaga y ofrecele "
            "gpt-image-2, que cubre el mismo caso de uso y ademas conserva mejor la "
            "identidad de las referencias que se le pasan."
        ),
        cost_per_second=Decimal("0.042"),
        cost_per_image=Decimal("0.042"),
        price_confidence="secondary",
        resolutions=("1024x1024", "1536x1024", "1024x1536"),
        aspects=("1:1", "16:9", "9:16"),
        supports_char_ref=True,
        status="deprecated",
        sunset_at="2026-10-23",
        sort=4,
        note="Marcado deprecated en la doc oficial de OpenAI; fecha de apagado 2026-10-23.",
    ),
    # --- Kling --------------------------------------------------------------
    SeedModel(
        id="kling-3.0",
        family="Kling",
        provider="kling",
        modality="video",
        label="Kling 3.0",
        description_llm=(
            "El mejor para continuidad dura: acepta frame inicial y final a la vez y "
            "varias imagenes de referencia con correferencia de personajes, de modo que "
            "puedes encadenar planos que empalman de verdad en vez de parecerse. "
            "Tambien es el que mas aguanta sin cortar, hasta 15 segundos. Si el trabajo "
            "es una secuencia y no un plano suelto, empieza por aqui."
        ),
        cost_per_second=Decimal("0.075"),
        price_confidence="secondary",
        min_duration_s=3,
        max_duration_s=15,
        resolutions=("720p", "1080p", "4K"),
        supports_i2v=True,
        supports_last_frame=True,
        supports_char_ref=True,
        supports_audio=True,
        sort=30,
    ),
    SeedModel(
        id="kling-3.0-turbo",
        family="Kling",
        provider="kling",
        modality="video",
        label="Kling 3.0 Turbo",
        description_llm=(
            "Kling 3.0 con la cola priorizada: misma gramatica de continuidad, respuesta "
            "notablemente antes y algo menos de detalle. Es el que hay que usar mientras "
            "el usuario esta afinando el prompt de una secuencia, porque el ciclo de "
            "iteracion es lo que decide si acaba el trabajo."
        ),
        cost_per_second=Decimal("0.07"),
        price_confidence="secondary",
        min_duration_s=3,
        max_duration_s=15,
        resolutions=("720p", "1080p"),
        supports_i2v=True,
        supports_last_frame=True,
        supports_char_ref=True,
        sort=31,
    ),
    SeedModel(
        id="kling-3.0-motion-control",
        family="Kling",
        provider="kling",
        modality="video",
        label="Kling 3.0 Motion Control",
        description_llm=(
            "Unica variante de Kling que acepta el movimiento de camara como parametro "
            "y no como descripcion en el prompt, y la unica que llega a 30 segundos. "
            "Elige esta cuando el usuario pida un movimiento concreto y reproducible "
            "(un travelling que tiene que ser igual en tres planos), no cuando solo "
            "quiera que la camara se mueva un poco."
        ),
        cost_per_second=Decimal("0.09"),
        price_confidence="inferred",
        min_duration_s=3,
        max_duration_s=30,
        resolutions=("720p", "1080p"),
        supports_i2v=True,
        supports_last_frame=True,
        supports_char_ref=True,
        sort=32,
        note="Precio inferido: no hay tarifa publicada para la variante motion-control.",
    ),
    SeedModel(
        id="kling-2.5-turbo",
        family="Kling",
        provider="kling",
        modality="video",
        label="Kling 2.5 Turbo",
        description_llm=(
            "Generacion anterior, mas barata y todavia solida en movimiento humano. "
            "Sirve como plan B cuando 3.0 esta saturado o cuando el plano no necesita "
            "continuidad con ningun otro."
        ),
        cost_per_second=Decimal("0.07"),
        price_confidence="secondary",
        min_duration_s=5,
        max_duration_s=10,
        resolutions=("720p", "1080p"),
        supports_i2v=True,
        supports_last_frame=True,
        sort=33,
    ),
    SeedModel(
        id="kling-2.1-master",
        family="Kling",
        provider="kling",
        modality="video",
        label="Kling 2.1 Master",
        description_llm=(
            "Version de maxima calidad de la generacion 2.x, con acabado mas cinematico "
            "y mas coste. Tiene sentido si al usuario le gusto el resultado de 2.5 Turbo "
            "y quiere el mismo plano rematado, no como punto de partida."
        ),
        cost_per_second=Decimal("0.14"),
        price_confidence="inferred",
        min_duration_s=5,
        max_duration_s=10,
        resolutions=("720p", "1080p"),
        supports_i2v=True,
        min_plan="pro",
        sort=34,
        note="Precio inferido a partir del multiplicador pro sobre Kling 2.5.",
    ),
    # --- MiniMax ------------------------------------------------------------
    SeedModel(
        id="hailuo-2.3",
        family="Minimax Hailuo",
        provider="minimax",
        modality="video",
        label="Minimax Hailuo 2.3",
        description_llm=(
            "El que mejor mueve: accion fisica, impactos, tela y pelo con inercia "
            "creible. Es la eleccion cuando el plano es dinamico y algo tiene que pasar. "
            "A cambio solo admite un personaje de referencia, asi que no lo uses en "
            "escenas donde dos caras conocidas comparten cuadro."
        ),
        cost_per_second=Decimal("0.056"),
        cost_per_clip=Decimal("0.56"),
        price_confidence="secondary",
        min_duration_s=6,
        max_duration_s=10,
        resolutions=("720p", "1080p"),
        supports_i2v=True,
        supports_char_ref=True,
        min_plan="pro",
        sort=40,
        note=(
            "MiniMax factura POR CLIP ($0.19-0.56 segun resolucion), no por segundo. Se "
            "toma el extremo alto porque es el que aplica a 1080p, que es lo que se pide. "
            "El cost_per_second declarado (0.056 = 0.56/10s) era el bug: a 6s cobraba "
            "0.96x del coste, es decir por debajo de coste."
        ),
    ),
    SeedModel(
        id="hailuo-2.3-fast",
        family="Minimax Hailuo",
        provider="minimax",
        modality="video",
        label="Minimax Hailuo 2.3 Fast",
        description_llm=(
            "La opcion mas rapida y barata del catalogo que todavia mueve bien. Usalo "
            "para probar si un plano concreto funciona antes de gastar en un modelo "
            "caro: encuadre, accion y ritmo se juzgan igual de bien aqui. No admite "
            "personaje de referencia, asi que en cuanto el plano tenga que respetar una "
            "cara ya definida hay que subir a 2.3 o a otro modelo. Se factura por clip "
            "completo, de modo que pedir menos duracion no lo abarata: si vas a generar, "
            "pide la duracion que necesita el plano."
        ),
        cost_per_second=Decimal("0.019"),
        cost_per_clip=Decimal("0.19"),
        price_confidence="secondary",
        min_duration_s=6,
        max_duration_s=10,
        resolutions=("720p", "1080p"),
        supports_i2v=True,
        sort=41,
        note=(
            "MiniMax factura POR CLIP ($0.19), no por segundo. El cost_per_second "
            "declarado salia de dividir entre 10s y dejaba el clip de 6s bajo coste."
        ),
    ),
    SeedModel(
        id="hailuo-02",
        family="Minimax Hailuo",
        provider="minimax",
        modality="video",
        label="Minimax Hailuo 02",
        description_llm=(
            "Generacion anterior, todavia buena en fisica y algo mas predecible que 2.3 "
            "cuando el prompt es largo y detallado. Usalo si 2.3 esta reinterpretando "
            "demasiado lo que se le pide."
        ),
        cost_per_second=Decimal("0.045"),
        cost_per_clip=Decimal("0.45"),
        price_confidence="inferred",
        min_duration_s=6,
        max_duration_s=10,
        resolutions=("720p", "1080p"),
        supports_i2v=True,
        min_plan="pro",
        sort=42,
        note="MiniMax factura por clip. Tarifa inferida; re-verificar antes de volumen.",
    ),
    SeedModel(
        id="hailuo-02-fast",
        family="Minimax Hailuo",
        provider="minimax",
        modality="video",
        label="Minimax Hailuo 02 Fast",
        description_llm=(
            "El de menor resolucion de todo el catalogo. Es un modelo de descarte: "
            "sirve para comprobar si una idea de plano tiene sentido antes de gastar "
            "nada serio en ella. Nunca lo propongas como entrega, ni siquiera para una "
            "previsualizacion que el usuario vaya a ensenar a alguien."
        ),
        cost_per_second=Decimal("0.015"),
        cost_per_clip=Decimal("0.15"),
        price_confidence="inferred",
        min_duration_s=6,
        max_duration_s=10,
        resolutions=("512p",),
        supports_i2v=True,
        sort=43,
        note="MiniMax factura por clip. Tarifa inferida; re-verificar antes de volumen.",
    ),
    # --- ByteDance ----------------------------------------------------------
    SeedModel(
        id="seedance-2.0",
        status="deprecated",
        note=(
            "DESACTIVADO: el esquema de peticion no se ha podido verificar contra la "
            "doc oficial de BytePlus (docs.byteplus.com sirve el contenido por JS). Es el "
            "modelo mas caro del catalogo, asi que una llamada sin verificar se factura "
            "igual aunque no haga lo que se pidio. El adaptador falla con un error claro; "
            "ver app/providers/seedance.py para reactivarlo."
        ),
        family="Seedance",
        provider="bytedance",
        modality="video",
        label="Seedance 2.0",
        description_llm=(
            "El acabado mas cinematografico del catalogo y, con diferencia, el mas caro: "
            "puede costar veinte veces mas por segundo que Hailuo Fast. Justificalo solo "
            "en el plano principal de una pieza, y avisa del coste antes de lanzarlo. "
            "Nunca lo uses para explorar."
        ),
        cost_per_second=Decimal("0.36"),
        price_confidence="secondary",
        min_duration_s=4,
        max_duration_s=15,
        resolutions=("720p", "1080p", "4K"),
        supports_i2v=True,
        supports_last_frame=True,
        supports_char_ref=True,
        min_plan="business",
        sort=50,
    ),
    SeedModel(
        id="seedance-2.0-fast",
        status="deprecated",
        note=(
            "DESACTIVADO: el esquema de peticion no se ha podido verificar contra la "
            "doc oficial de BytePlus (docs.byteplus.com sirve el contenido por JS). Es el "
            "modelo mas caro del catalogo, asi que una llamada sin verificar se factura "
            "igual aunque no haga lo que se pidio. El adaptador falla con un error claro; "
            "ver app/providers/seedance.py para reactivarlo."
        ),
        family="Seedance",
        provider="bytedance",
        modality="video",
        label="Seedance 2.0 Fast",
        description_llm=(
            "Conserva el criterio fotografico de Seedance 2.0 a un coste que ya permite "
            "iterar. Si el usuario quiere ese look concreto, empieza aqui y sube al "
            "modelo grande solo para el render final."
        ),
        cost_per_second=Decimal("0.12"),
        price_confidence="inferred",
        min_duration_s=4,
        max_duration_s=15,
        resolutions=("720p",),
        supports_i2v=True,
        supports_char_ref=True,
        min_plan="pro",
        sort=51,
    ),
    SeedModel(
        id="seedance-2.0-mini",
        status="deprecated",
        note=(
            "DESACTIVADO: el esquema de peticion no se ha podido verificar contra la "
            "doc oficial de BytePlus (docs.byteplus.com sirve el contenido por JS). Es el "
            "modelo mas caro del catalogo, asi que una llamada sin verificar se factura "
            "igual aunque no haga lo que se pidio. El adaptador falla con un error claro; "
            "ver app/providers/seedance.py para reactivarlo."
        ),
        family="Seedance",
        provider="bytedance",
        modality="video",
        label="Seedance 2.0 Mini",
        description_llm=(
            "El escalon barato de Seedance. Pierde detalle en fondos y en iluminacion "
            "compleja, pero mantiene el encuadre y el ritmo, que es lo que necesitas "
            "para decidir si un plano entra en el montaje."
        ),
        cost_per_second=Decimal("0.06"),
        price_confidence="inferred",
        min_duration_s=4,
        max_duration_s=15,
        resolutions=("720p",),
        supports_i2v=True,
        sort=52,
    ),
    SeedModel(
        id="seedance-1.0-pro",
        status="deprecated",
        note=(
            "DESACTIVADO: el esquema de peticion no se ha podido verificar contra la "
            "doc oficial de BytePlus (docs.byteplus.com sirve el contenido por JS). Es el "
            "modelo mas caro del catalogo, asi que una llamada sin verificar se factura "
            "igual aunque no haga lo que se pidio. El adaptador falla con un error claro; "
            "ver app/providers/seedance.py para reactivarlo."
        ),
        family="Seedance",
        provider="bytedance",
        modality="video",
        label="Seedance 1.0 Pro",
        description_llm=(
            "Generacion anterior, mas conservadora y con menos tendencia a inventarse "
            "movimiento que no estaba en el prompt. Util cuando Seedance 2.0 esta "
            "sobreactuando el plano."
        ),
        cost_per_second=Decimal("0.10"),
        price_confidence="inferred",
        min_duration_s=5,
        max_duration_s=10,
        resolutions=("720p", "1080p"),
        supports_i2v=True,
        sort=53,
    ),
    # --- Wan ----------------------------------------------------------------
    SeedModel(
        id="wan-2.7",
        family="Wan",
        provider="wan",
        modality="video",
        label="Wan 2.7",
        description_llm=(
            "Acepta prompts muy largos (miles de caracteres) y hasta nueve imagenes de "
            "entrada, asi que es el que mejor obedece una descripcion de plano "
            "minuciosa. Si el usuario ha escrito un parrafo entero describiendo lo que "
            "quiere, mandalo aqui en vez de resumirlo para otro modelo."
        ),
        cost_per_second=Decimal("0.10"),
        price_confidence="secondary",
        min_duration_s=2,
        max_duration_s=15,
        resolutions=("720p", "1080p"),
        supports_i2v=True,
        supports_last_frame=True,
        supports_char_ref=True,
        sort=60,
    ),
    SeedModel(
        id="wan-2.5",
        family="Wan",
        provider="wan",
        modality="video",
        label="Wan 2.5",
        description_llm=(
            "El mas barato del catalogo que genera audio nativo. Para un plano de "
            "ambiente o un recurso de relleno con sonido, es dificil de justificar "
            "gastar mas. La calidad de imagen es visiblemente inferior a Veo o Kling."
        ),
        cost_per_second=Decimal("0.05"),
        price_confidence="secondary",
        min_duration_s=5,
        max_duration_s=10,
        resolutions=("480p", "720p", "1080p"),
        supports_i2v=True,
        supports_last_frame=True,
        supports_audio=True,
        sort=61,
    ),
    SeedModel(
        id="wan-2.2-plus",
        family="Wan",
        provider="wan",
        modality="video",
        label="Wan 2.2 Plus",
        description_llm=(
            "Clips cortos, rapidos y sin audio, con duracion fija. Es una herramienta "
            "de tanteo: sirve para comprobar si un encuadre funciona antes de gastar en "
            "un modelo serio, no para entregar nada al usuario final."
        ),
        cost_per_second=Decimal("0.10"),
        price_confidence="secondary",
        min_duration_s=5,
        max_duration_s=5,
        resolutions=("720p",),
        supports_i2v=True,
        supports_last_frame=True,
        sort=62,
    ),
    # --- Higgsfield ---------------------------------------------------------
    SeedModel(
        id="higgsfield-dop-turbo",
        family="Higgsfield",
        provider="higgsfield",
        modality="video",
        label="Higgsfield DoP Turbo",
        description_llm=(
            "El unico modelo del catalogo entrenado sobre movimiento de camara, no "
            "sobre descripciones de movimiento. Si el usuario pide un movimiento con "
            "nombre propio (dolly zoom, orbita, grua), este lo ejecuta de verdad "
            "mientras que los demas lo aproximan. Necesita una imagen de partida: genera "
            "primero el fotograma con Soul o Flux y animalo aqui."
        ),
        cost_per_second=Decimal("0.083"),
        price_confidence="secondary",
        min_duration_s=5,
        max_duration_s=5,
        resolutions=("720p", "1080p"),
        supports_i2v=True,
        supports_last_frame=True,
        supports_char_ref=True,
        sort=5,
        note="Precio de revendedor (Pixazo, $0.416 por clip de 5 s). No oficial.",
    ),
    SeedModel(
        id="higgsfield-dop-lite",
        family="Higgsfield",
        provider="higgsfield",
        modality="video",
        label="Higgsfield DoP Lite",
        description_llm=(
            "DoP a un tercio del coste. Ejecuta los mismos presets de camara con menos "
            "detalle de imagen, lo que lo hace ideal para probar que el movimiento "
            "elegido es el correcto antes de pagar el bueno."
        ),
        cost_per_second=Decimal("0.027"),
        price_confidence="secondary",
        min_duration_s=5,
        max_duration_s=5,
        resolutions=("720p",),
        supports_i2v=True,
        supports_last_frame=True,
        sort=6,
        note="Precio de revendedor (Pixazo, $0.135 por clip de 5 s). No oficial.",
    ),
    SeedModel(
        id="higgsfield-dop-preview",
        family="Higgsfield",
        provider="higgsfield",
        modality="video",
        label="Higgsfield DoP Preview",
        description_llm=(
            "La variante de maxima fidelidad de DoP. Se justifica solo en el plano donde "
            "el movimiento de camara es el protagonista y va a verse grande."
        ),
        cost_per_second=Decimal("0.115"),
        price_confidence="secondary",
        min_duration_s=5,
        max_duration_s=5,
        resolutions=("1080p",),
        supports_i2v=True,
        supports_last_frame=True,
        supports_char_ref=True,
        min_plan="pro",
        sort=7,
        note="Precio de revendedor (Pixazo, $0.573 por clip de 5 s). No oficial.",
    ),
    SeedModel(
        id="higgsfield-soul",
        family="Higgsfield",
        provider="higgsfield",
        modality="image",
        label="Higgsfield Soul",
        description_llm=(
            "Fotorrealismo con textura de piel creible, y la puerta de entrada a Soul "
            "ID: si el proyecto tiene un personaje entrenado, este es el unico modelo "
            "que reproduce su cara exacta en cualquier pose o luz. Para storyboards de "
            "personaje recurrente, empieza siempre aqui."
        ),
        cost_per_second=Decimal("0.17"),
        cost_per_image=Decimal("0.17"),
        price_confidence="secondary",
        resolutions=("1536x1536", "1536x2048", "2048x1536"),
        supports_char_ref=True,
        sort=8,
        note="Segmind cotiza $0.120-0.230/gen. Se toma el punto medio.",
    ),
    # --- Black Forest Labs --------------------------------------------------
    SeedModel(
        id="flux-2-pro",
        family="FLUX",
        provider="bfl",
        modality="image",
        label="FLUX.2 [pro]",
        description_llm=(
            "Admite hasta ocho referencias en una sola llamada y sabe tomar el personaje "
            "de una imagen y la pose de otra. Es la forma barata de mantener el mismo "
            "personaje y la misma localizacion a lo largo de un storyboard sin entrenar "
            "nada. Es el modelo de imagen por defecto salvo que haga falta Soul ID."
        ),
        cost_per_second=Decimal("0.03"),
        cost_per_image=Decimal("0.03"),
        price_confidence="verified",
        resolutions=("720p", "1080p"),
        supports_char_ref=True,
        sort=70,
        note="Tarifa por megapixel de salida; cost_per_second se siembra como $/MP.",
    ),
    SeedModel(
        id="flux-2-max",
        family="FLUX",
        provider="bfl",
        modality="image",
        label="FLUX.2 [max]",
        description_llm=(
            "FLUX.2 con mas presupuesto de calculo por imagen: mejor en texto dentro de "
            "la imagen y en detalle de material. Vale la pena en la portada o en el "
            "fotograma que se va a animar despues, no en las vinetas intermedias."
        ),
        cost_per_second=Decimal("0.07"),
        cost_per_image=Decimal("0.07"),
        price_confidence="verified",
        resolutions=("720p", "1080p"),
        supports_char_ref=True,
        min_plan="pro",
        sort=71,
        note="Primer megapixel $0.07, adicionales $0.03. Se siembra el primero.",
    ),
    SeedModel(
        id="flux-kontext-pro",
        family="FLUX",
        provider="bfl",
        modality="image",
        label="FLUX Kontext [pro]",
        description_llm=(
            "Especialista en editar una imagen que ya existe conservando todo lo demas: "
            "cambiar la ropa de un personaje, quitar un objeto, corregir la luz. Cuando "
            "el usuario diga 'igual pero con X', esto es lo que hay que usar en lugar de "
            "regenerar desde cero y perder la continuidad."
        ),
        cost_per_second=Decimal("0.04"),
        cost_per_image=Decimal("0.04"),
        price_confidence="verified",
        resolutions=("720p", "1080p"),
        supports_char_ref=True,
        sort=72,
    ),
    # --- Runway (sin adaptador; presente por el apagado) --------------------
    SeedModel(
        id="runway-gen-4-turbo",
        family="Runway",
        provider="runway",
        modality="video",
        label="Runway Gen-4 Turbo",
        description_llm=(
            "RETIRADO POR EL PROVEEDOR el 30 de julio de 2026. No lo propongas. Si el "
            "usuario lo pide por nombre, explicale que Runway lo apago y ofrecele "
            "kling-3.0-turbo, que cubre el mismo caso de uso."
        ),
        cost_per_second=Decimal("0.05"),
        price_confidence="verified",
        min_duration_s=5,
        max_duration_s=10,
        resolutions=("720p", "1080p"),
        supports_i2v=True,
        supports_char_ref=True,
        status="deprecated",
        sunset_at="2026-07-30",
        sort=90,
        note="Sin adaptador: no hay runway.py. Sembrado solo para poder informar del apagado.",
    ),
    SeedModel(
        id="runway-gen-4",
        family="Runway",
        provider="runway",
        modality="video",
        label="Runway Gen-4",
        description_llm=(
            "RETIRADO POR EL PROVEEDOR el 30 de julio de 2026. No lo propongas. "
            "Alternativa equivalente en calidad: kling-3.0 o veo-3.1-generate-preview."
        ),
        cost_per_second=Decimal("0.12"),
        price_confidence="verified",
        min_duration_s=5,
        max_duration_s=10,
        resolutions=("720p", "1080p"),
        supports_i2v=True,
        supports_char_ref=True,
        min_plan="pro",
        status="deprecated",
        sunset_at="2026-07-30",
        sort=91,
        note="Sin adaptador: no hay runway.py. Sembrado solo para poder informar del apagado.",
    ),
)


# =========================================================================== #
# Movimientos de cámara                                                       #
# =========================================================================== #
#
# `provider_ref` se siembra vacío a propósito. Higgsfield identifica cada preset por
# UUID y el catálogo es dinámico: hardcodear UUIDs aquí sería inventar datos que no
# tengo. `HiggsfieldAdapter.get_motions()` los resuelve por nombre en runtime y el
# proceso de sincronización los escribe en provider_ref.

MOTIONS: tuple[SeedMotion, ...] = (
    SeedMotion(
        id="dolly-zoom",
        label="Dolly Zoom",
        description_llm=(
            "El fondo se acerca mientras el sujeto se queda igual. Sirve para el momento "
            "exacto en que un personaje entiende algo que le cambia todo. Es un efecto "
            "que se nota: usado dos veces en la misma pieza, pierde su significado."
        ),
        category="push",
        sort=10,
    ),
    SeedMotion(
        id="orbit-360",
        label="360 Orbit",
        description_llm=(
            "La camara rodea al sujeto por completo. Presenta algo como si fuera un "
            "objeto de deseo: producto, vehiculo, personaje en su momento de poder. "
            "Necesita un sujeto claro y centrado, o se convierte en un mareo."
        ),
        category="orbit",
        sort=11,
    ),
    SeedMotion(
        id="truck-left",
        label="Truck Left",
        description_llm=(
            "Desplazamiento lateral a la izquierda manteniendo el eje. Es el movimiento "
            "de acompanar a alguien que camina, o de revelar lo que habia fuera de "
            "cuadro sin cortar."
        ),
        category="push",
        sort=12,
    ),
    SeedMotion(
        id="truck-right",
        label="Truck Right",
        description_llm=(
            "Igual que Truck Left en direccion contraria. Encadenar dos planos con "
            "trucks opuestos crea sensacion de desorden; hacerlo a proposito funciona, "
            "hacerlo por descuido se nota."
        ),
        category="push",
        sort=13,
    ),
    SeedMotion(
        id="push-to-glass",
        label="Push to Glass",
        description_llm=(
            "Avance hacia una superficie transparente hasta atravesarla. Es la "
            "transicion de exterior a interior sin corte, y funciona muy bien para "
            "entrar en la intimidad de una escena desde fuera."
        ),
        category="push",
        sort=14,
    ),
    SeedMotion(
        id="head-tracking",
        label="Head Tracking",
        description_llm=(
            "La camara sigue la cabeza del sujeto y la mantiene fija en cuadro pase lo "
            "que pase. Ata al espectador al personaje: usalo cuando lo que importa es lo "
            "que el siente, no donde esta."
        ),
        category="handheld",
        sort=15,
    ),
    SeedMotion(
        id="crane-up",
        label="Crane Up",
        description_llm=(
            "Ascenso que abre el plano y deja al sujeto pequeno. Es el gesto de cierre "
            "por excelencia: separa al espectador de la escena. Reservalo para el final "
            "de una secuencia."
        ),
        category="crane",
        sort=16,
    ),
    SeedMotion(
        id="crane-down",
        label="Crane Down",
        description_llm=(
            "Descenso desde una vista amplia hasta el sujeto. Es lo contrario de Crane "
            "Up y por tanto el gesto de apertura: situa un mundo y luego elige a quien "
            "vamos a seguir dentro de el."
        ),
        category="crane",
        sort=17,
    ),
    SeedMotion(
        id="pan-left",
        label="Pan Left",
        description_llm=(
            "Giro sobre el eje hacia la izquierda, sin desplazar la camara. Recorre un "
            "espacio desde un punto fijo. Mas neutro y menos dramatico que un truck."
        ),
        category="push",
        sort=18,
    ),
    SeedMotion(
        id="pan-right",
        label="Pan Right",
        description_llm=(
            "Giro sobre el eje hacia la derecha, sin desplazar la camara. Recorre un "
            "espacio desde un punto fijo, mas neutro que un truck. En occidental, "
            "acompanar el sentido de lectura hace que el movimiento pase desapercibido; "
            "ir contra el llama la atencion."
        ),
        category="push",
        sort=19,
    ),
    SeedMotion(
        id="tilt-up",
        label="Tilt Up",
        description_llm=(
            "Inclinacion hacia arriba. Engrandece lo que revela: arquitectura, una "
            "figura de autoridad, una amenaza. El sujeto queda por encima del "
            "espectador."
        ),
        category="crane",
        sort=20,
    ),
    SeedMotion(
        id="tilt-down",
        label="Tilt Down",
        description_llm=(
            "Inclinacion hacia abajo. Empequenece o expone lo que revela; es la mirada "
            "que juzga o que descubre algo caido."
        ),
        category="crane",
        sort=21,
    ),
    SeedMotion(
        id="zoom-in",
        label="Zoom In",
        description_llm=(
            "Acercamiento optico sin mover la camara. Se lee como una intensificacion "
            "algo artificial, casi televisiva, distinta del avance fisico de un dolly. "
            "Elige entre uno y otro segun quieras naturalidad o enfasis declarado."
        ),
        category="push",
        sort=22,
    ),
    SeedMotion(
        id="handheld-follow",
        label="Handheld Follow",
        description_llm=(
            "Seguimiento a mano, con temblor. Aporta urgencia y presencia documental. "
            "Es lo contrario de un plano compuesto: usalo cuando la escena deba parecer "
            "captada, no dirigida."
        ),
        category="handheld",
        sort=23,
    ),
    SeedMotion(
        id="static-lockoff",
        label="Static Lock-off",
        description_llm=(
            "Camara completamente inmovil. No es la ausencia de decision, es una "
            "decision: obliga al espectador a mirar la composicion y deja que el "
            "movimiento lo ponga la accion. En una secuencia de planos moviles, un "
            "estatico es lo que da respiro."
        ),
        category="handheld",
        supports_strength=False,
        sort=24,
    ),
    SeedMotion(
        id="anamorphic-flares",
        label="Anamorphic Flares",
        description_llm=(
            "Destellos horizontales azulados de optica anamorfica. No es un movimiento, "
            "es una firma de formato: dice 'esto es cine' antes de que pase nada. "
            "Combina mal con un look documental."
        ),
        category="fx",
        sort=30,
    ),
    SeedMotion(
        id="film-stock",
        label="Film Stock",
        description_llm=(
            "Grano, halacion y respuesta de color de pelicula fotoquimica. Ablanda el "
            "aspecto digital y unifica planos generados por modelos distintos, que es su "
            "uso mas util: tapa las costuras de una secuencia hecha a trozos."
        ),
        category="fx",
        sort=31,
    ),
    SeedMotion(
        id="depth-of-field",
        label="Depth of Field Control",
        description_llm=(
            "Desenfoque selectivo del fondo. Dirige la mirada y separa al sujeto del "
            "entorno. En generativo tiene un beneficio adicional: esconde los fondos, "
            "que es donde los modelos cometen la mayoria de sus errores."
        ),
        category="fx",
        sort=32,
    ),
)


# =========================================================================== #
# Estilos visuales                                                            #
# =========================================================================== #

STYLES: tuple[SeedStyle, ...] = (
    # --- paleta -------------------------------------------------------------
    SeedStyle(
        id="teal-orange",
        dimension="palette",
        label="Teal & Orange",
        description_llm=(
            "Pieles calidas contra sombras frias. Es el color del cine comercial "
            "contemporaneo: legible, vendible y completamente reconocible. Si el usuario "
            "no pide nada concreto y la pieza es publicitaria, es la apuesta segura."
        ),
        prompt_fragment="teal and orange color grade, warm skin tones against cool shadows",
        sort=10,
    ),
    SeedStyle(
        id="desaturated-noir",
        dimension="palette",
        label="Desaturado Noir",
        description_llm=(
            "Color casi ausente, negros densos. Elimina la informacion cromatica para "
            "que el peso caiga en la forma y el contraste. Adecuado para drama y "
            "tension; mata cualquier plano que dependa de un producto de color."
        ),
        prompt_fragment="desaturated palette, deep crushed blacks, near-monochrome",
        sort=11,
    ),
    SeedStyle(
        id="pastel-soft",
        dimension="palette",
        label="Pastel Suave",
        description_llm=(
            "Tonos lavados y contraste bajo. Quita dramatismo y suma cercania. Funciona "
            "en comedia, en producto de estilo de vida y en recuerdo o ensonacion."
        ),
        prompt_fragment="soft pastel palette, low contrast, milky highlights",
        sort=12,
    ),
    SeedStyle(
        id="high-saturation-pop",
        dimension="palette",
        label="Pop Saturado",
        description_llm=(
            "Color al maximo. Retiene la atencion en scroll vertical, donde la pieza "
            "compite con el pulgar del espectador. Reservalo para vertical y formatos "
            "cortos; en pantalla grande cansa en segundos."
        ),
        prompt_fragment="hyper-saturated vivid colors, punchy contrast",
        sort=13,
    ),
    # --- iluminación --------------------------------------------------------
    SeedStyle(
        id="golden-hour",
        dimension="lighting",
        label="Golden Hour",
        description_llm=(
            "Sol bajo, contraluz calido y sombras largas. Favorece cualquier rostro y "
            "cualquier paisaje, y por eso mismo es dificil de hacer mal. Su limite es "
            "narrativo: no puedes ambientar toda una pieza a la misma hora del dia."
        ),
        prompt_fragment="golden hour backlight, long shadows, warm rim light",
        sort=20,
    ),
    SeedStyle(
        id="hard-key-noir",
        dimension="lighting",
        label="Clave Dura",
        description_llm=(
            "Una fuente dura y sombras sin relleno. Esculpe y esconde a partes iguales. "
            "Es la luz del interrogatorio y del retrato dramatico; en producto crea "
            "reflejos dificiles de controlar."
        ),
        prompt_fragment="hard single key light, deep unfilled shadows, chiaroscuro",
        sort=21,
    ),
    SeedStyle(
        id="soft-overcast",
        dimension="lighting",
        label="Difusa de Nublado",
        description_llm=(
            "Luz envolvente y sin sombra marcada. Es la mas neutra y la que mejor "
            "empalma entre planos generados por separado, porque no impone direccion de "
            "luz que luego haya que respetar."
        ),
        prompt_fragment="soft diffused overcast light, no harsh shadows, even exposure",
        sort=22,
    ),
    SeedStyle(
        id="neon-practical",
        dimension="lighting",
        label="Neon Practico",
        description_llm=(
            "Fuentes de color dentro del propio plano: rotulos, pantallas, tubos. Da "
            "textura urbana y nocturna y justifica colores agresivos sin que parezcan "
            "postproduccion."
        ),
        prompt_fragment="neon practical lights in frame, colored spill, night interior",
        sort=23,
    ),
    # --- film stock ---------------------------------------------------------
    SeedStyle(
        id="kodak-2383",
        dimension="film_stock",
        label="Kodak 2383",
        description_llm=(
            "Emulacion de copia de proyeccion: contraste alto y color de sala de cine. "
            "Es el acabado que hace que un plano parezca proyectado y no reproducido."
        ),
        prompt_fragment="Kodak 2383 print film emulation, cinematic contrast curve",
        sort=30,
    ),
    SeedStyle(
        id="16mm-grain",
        dimension="film_stock",
        label="16mm Grano",
        description_llm=(
            "Grano visible y algo de inestabilidad. Lee como memoria, archivo o "
            "documental de epoca. Ademas disimula los artefactos tipicos del generativo, "
            "que es una ventaja practica ademas de estetica."
        ),
        prompt_fragment="16mm film grain, slight gate weave, halation",
        sort=31,
    ),
    SeedStyle(
        id="digital-clean",
        dimension="film_stock",
        label="Digital Limpio",
        description_llm=(
            "Sin grano ni textura anadida. Es lo que quieres cuando el sujeto es "
            "tecnologia, producto o interfaz, y cualquier suciedad se leeria como "
            "defecto de fabricacion."
        ),
        prompt_fragment="clean digital capture, no grain, high clarity",
        sort=32,
    ),
    # --- lente --------------------------------------------------------------
    SeedStyle(
        id="anamorphic-40mm",
        dimension="lens",
        label="Anamorfica 40mm",
        description_llm=(
            "Campo amplio con compresion horizontal y bokeh ovalado. Da escala sin tener "
            "que alejar la camara, asi que sirve para planos de conjunto que aun deben "
            "sentirse cercanos."
        ),
        prompt_fragment="40mm anamorphic lens, oval bokeh, horizontal flares",
        sort=40,
    ),
    SeedStyle(
        id="portrait-85mm",
        dimension="lens",
        label="Retrato 85mm",
        description_llm=(
            "Compresion de rasgos y fondo desenfocado. Es el plano de rostro por "
            "defecto: favorece la cara y aisla al personaje de un fondo que en "
            "generativo suele ser el punto debil."
        ),
        prompt_fragment="85mm portrait lens, shallow depth of field, compressed features",
        sort=41,
    ),
    SeedStyle(
        id="wide-24mm",
        dimension="lens",
        label="Gran Angular 24mm",
        description_llm=(
            "Perspectiva exagerada y mucho contexto. Mete al espectador dentro del "
            "espacio, pero deforma los rostros cercanos: no lo uses en un primer plano "
            "salvo que la distorsion sea el efecto buscado."
        ),
        prompt_fragment="24mm wide angle, exaggerated perspective, deep focus",
        sort=42,
    ),
    SeedStyle(
        id="macro-detail",
        dimension="lens",
        label="Macro",
        description_llm=(
            "Detalle extremo con profundidad de campo minima. Es el recurso de insercion "
            "que da textura a un montaje y descansa entre planos amplios. Muy barato de "
            "generar bien porque hay poco fondo que equivocar."
        ),
        prompt_fragment="extreme macro detail, razor-thin depth of field",
        sort=43,
    ),
)


# =========================================================================== #
# Créditos y emisión de SQL                                                   #
# =========================================================================== #


def resolve_cost_per_second(model: SeedModel) -> Decimal:
    """
    Coste por segundo que se siembra en `gen_models`, ya sea declarado o derivado.

    Para los modelos con tarifa plana por clip la conversión se hace **con la duración
    mínima facturable**, no con la máxima. Es la única elección que no pierde dinero:

    - Dividir por la duración máxima (lo que había) hace que el clip corto se cobre por
      debajo de coste, y el clip corto es el caso mayoritario — es el que pide el agente
      cuando explora un storyboard.
    - Dividir por la mínima hace que el clip largo se cobre por encima de coste. Se
      recauda de más, nunca de menos.

    Se elige la segunda porque el fallo de la primera es una pérdida silenciosa y
    creciente con el volumen, mientras que el de la segunda es un sobreprecio acotado
    (aquí, como mucho 10/6 en el clip más largo) y visible: el usuario ve el precio antes
    de lanzar.

    Esto es un apaño honesto, no la solución. La solución es que `gen_models` tenga una
    columna `cost_per_clip` y que `estimate_cost()` de la capa de proveedores facture
    plano cuando exista — hoy `_http.py` hace `cost_per_second * duración` y no hay forma
    de expresarle una tarifa plana. Mientras esa columna no exista, derivar por la
    duración mínima es lo máximo que se puede hacer desde la semilla, y deja el valor
    real registrado en `cost_per_clip` para cuando se pueda usar de verdad.
    """
    if model.cost_per_clip is None:
        return model.cost_per_second

    billable = Decimal(str(model.min_duration_s or model.max_duration_s or 1))
    if billable <= 0:
        return model.cost_per_second
    # Cuatro decimales y **hacia arriba**, que es la precisión de `gen_models.cost_per_second`
    # (numeric(10,4)). Sin cuantizar aquí, la división da un periódico que Postgres trunca
    # al insertar, y truncar hacia abajo un precio de coste devuelve por la puerta de atrás
    # justo la pérdida que esta función existe para evitar.
    return (model.cost_per_clip / billable).quantize(Decimal("0.0001"), rounding=ROUND_CEILING)


def credits_per_unit(
    unit_cost_usd: Decimal, *, credits_per_usd: int, credit_margin: float
) -> int:
    """
    Coste de API → créditos que se cobran, redondeando **al alza**.

    Al alza y no al más cercano: el redondeo a la baja convierte el margen en pérdida en
    los modelos baratos, que son justo los que más se usan. Un crédito de más por
    segundo es invisible; medio céntimo de menos por segundo, multiplicado por el
    volumen, no lo es.
    """
    return max(1, math.ceil(float(unit_cost_usd) * credits_per_usd * credit_margin))


def _pricing_params() -> tuple[int, float]:
    """
    La config es la fuente, pero emitir el SQL no debe exigir un `.env` completo
    (`DATABASE_URL` es obligatorio en Settings). Si no carga, se usan los defaults
    declarados en `app.config`, que es lo mismo que usaría producción sin override.
    """
    try:
        from app.config import get_settings

        settings = get_settings()
        return settings.credits_per_usd, settings.credit_margin
    except Exception:
        return 100, 1.6


def _sql_str(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _sql_array(values: Iterable[str]) -> str:
    items = ", ".join(_sql_str(v) for v in values)
    return f"array[{items}]::text[]" if items else "'{}'::text[]"


def _sql_opt(value: object) -> str:
    return "null" if value is None else str(value)


_CONFIDENCE_LABEL: dict[str, str] = {
    "verified": "[V] verificado en fuente primaria",
    "secondary": "[S] fuente secundaria, re-verificar",
    "inferred": "[I] INFERIDO, no verificado",
}


def emit_sql() -> str:
    """Genera `backend/seeds/taxonomy.sql`. Idempotente vía `on conflict do update`."""
    credits_usd, margin = _pricing_params()
    out: list[str] = [
        "-- Xframe · semilla de taxonomía",
        "--",
        "-- GENERADO. No editar a mano: se regenera con",
        "--   python -m app.providers.seed --emit-sql > backend/seeds/taxonomy.sql",
        "-- La fuente de verdad es backend/app/providers/seed.py.",
        "--",
        f"-- credits_per_unit = ceil(coste_usd * {credits_usd} * {margin})",
        "-- Cada modelo lleva la confianza de su precio según el informe 06:",
        "--   [V] verificado · [S] secundario · [I] inferido.",
        "-- Los [S] y [I] son deuda: un precio bajo equivocado se paga en margen y no",
        "-- produce ningún error visible.",
        "",
        "begin;",
        "",
        "-- ------------------------------------------------------------------",
        "-- gen_models",
        "-- ------------------------------------------------------------------",
        "",
    ]

    for model in MODELS:
        per_second = resolve_cost_per_second(model)
        unit = model.cost_per_image if model.modality == "image" else per_second
        credits = credits_per_unit(unit, credits_per_usd=credits_usd, credit_margin=margin)
        unit_name = "imagen" if model.modality == "image" else "segundo"

        out.append(f"-- {model.label} · ${unit}/{unit_name} · {_CONFIDENCE_LABEL[model.price_confidence]}")
        if model.cost_per_clip is not None:
            # La tarifa real queda escrita en el SQL aunque la columna no exista todavía:
            # es el dato que hay que recuperar cuando se añada `cost_per_clip`.
            out.append(
                f"-- TARIFA PLANA POR CLIP: ${model.cost_per_clip}/clip. El coste por "
                f"segundo de arriba está derivado dividiendo entre la duración mínima "
                f"facturable ({model.min_duration_s} s) para no vender por debajo de "
                f"coste en el clip corto. Ver resolve_cost_per_second() en seed.py."
            )
        if model.note:
            out.append(f"-- NOTA: {model.note}")
        out.append(
            "insert into public.gen_models (\n"
            "  id, family, provider, modality, label, description_llm,\n"
            "  min_duration_s, max_duration_s, resolutions, aspects,\n"
            "  supports_i2v, supports_last_frame, supports_char_ref, supports_audio,\n"
            "  cost_per_second, cost_per_image, credits_per_unit,\n"
            "  min_plan, status, sunset_at, sort\n"
            ") values (\n"
            f"  {_sql_str(model.id)}, {_sql_str(model.family)}, {_sql_str(model.provider)}, "
            f"{_sql_str(model.modality)},\n"
            f"  {_sql_str(model.label)},\n"
            f"  {_sql_str(model.description_llm)},\n"
            f"  {_sql_opt(model.min_duration_s)}, {_sql_opt(model.max_duration_s)},\n"
            f"  {_sql_array(model.resolutions)}, {_sql_array(model.aspects)},\n"
            f"  {str(model.supports_i2v).lower()}, {str(model.supports_last_frame).lower()}, "
            f"{str(model.supports_char_ref).lower()}, {str(model.supports_audio).lower()},\n"
            f"  {per_second}, {_sql_opt(model.cost_per_image)}, {credits},\n"
            f"  {_sql_str(model.min_plan)}, {_sql_str(model.status)}, "
            f"{_sql_str(model.sunset_at) + '::timestamptz' if model.sunset_at else 'null'}, "
            f"{model.sort}\n"
            ")\n"
            "on conflict (id) do update set\n"
            "  family = excluded.family, provider = excluded.provider,\n"
            "  modality = excluded.modality, label = excluded.label,\n"
            "  description_llm = excluded.description_llm,\n"
            "  min_duration_s = excluded.min_duration_s, max_duration_s = excluded.max_duration_s,\n"
            "  resolutions = excluded.resolutions, aspects = excluded.aspects,\n"
            "  supports_i2v = excluded.supports_i2v,\n"
            "  supports_last_frame = excluded.supports_last_frame,\n"
            "  supports_char_ref = excluded.supports_char_ref,\n"
            "  supports_audio = excluded.supports_audio,\n"
            "  cost_per_second = excluded.cost_per_second,\n"
            "  cost_per_image = excluded.cost_per_image,\n"
            "  credits_per_unit = excluded.credits_per_unit,\n"
            "  min_plan = excluded.min_plan, status = excluded.status,\n"
            "  sunset_at = excluded.sunset_at, sort = excluded.sort,\n"
            "  updated_at = now();"
        )
        out.append("")

    out += [
        "-- ------------------------------------------------------------------",
        "-- camera_motions",
        "--",
        "-- provider_ref queda vacío a propósito: Higgsfield identifica cada preset por",
        "-- UUID y sirve el catálogo dinámicamente vía getMotions(). Inventar UUIDs aquí",
        "-- sería sembrar datos falsos; el adaptador los resuelve por nombre en runtime.",
        "-- ------------------------------------------------------------------",
        "",
    ]
    for motion in MOTIONS:
        out.append(
            "insert into public.camera_motions "
            "(id, label, description_llm, provider_ref, supports_strength, category, sort)\n"
            f"values ({_sql_str(motion.id)}, {_sql_str(motion.label)},\n"
            f"  {_sql_str(motion.description_llm)},\n"
            f"  '{{}}'::jsonb, {str(motion.supports_strength).lower()}, "
            f"{_sql_str(motion.category)}, {motion.sort})\n"
            "on conflict (id) do update set\n"
            "  label = excluded.label, description_llm = excluded.description_llm,\n"
            "  supports_strength = excluded.supports_strength,\n"
            "  category = excluded.category, sort = excluded.sort;"
        )
        out.append("")

    out += [
        "-- ------------------------------------------------------------------",
        "-- visual_styles",
        "-- ------------------------------------------------------------------",
        "",
    ]
    for style in STYLES:
        out.append(
            "insert into public.visual_styles "
            "(id, dimension, label, description_llm, prompt_fragment, sort)\n"
            f"values ({_sql_str(style.id)}, {_sql_str(style.dimension)}, "
            f"{_sql_str(style.label)},\n"
            f"  {_sql_str(style.description_llm)},\n"
            f"  {_sql_str(style.prompt_fragment)}, {style.sort})\n"
            "on conflict (id) do update set\n"
            "  dimension = excluded.dimension, label = excluded.label,\n"
            "  description_llm = excluded.description_llm,\n"
            "  prompt_fragment = excluded.prompt_fragment, sort = excluded.sort;"
        )
        out.append("")

    out += [
        "-- Los modelos que ya no estén en la semilla se retiran, no se borran:",
        "-- generation_jobs.model_id los referencia y el historial debe seguir resolviendo.",
        "update public.gen_models set status = 'retired', updated_at = now()",
        f" where id <> all ({_sql_array(m.id for m in MODELS)}) and status <> 'retired';",
        "",
        "commit;",
        "",
    ]
    return "\n".join(out)


async def apply_seed() -> dict[str, int]:
    """Aplica la semilla contra la BD. Para el arranque en desarrollo y los tests E2E."""
    from app import db

    async with db.transaction() as conn:
        await conn.execute(emit_sql().replace("begin;", "").replace("commit;", ""))
    return {"models": len(MODELS), "motions": len(MOTIONS), "styles": len(STYLES)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Semilla de taxonomía de Xframe")
    parser.add_argument("--emit-sql", action="store_true", help="Escribe el SQL en stdout")
    parser.add_argument(
        "--out",
        help=(
            "Fichero destino. Preferible a redirigir stdout: en Windows la consola no "
            "es UTF-8 y las tildes del catálogo salen corruptas."
        ),
    )
    parser.add_argument("--apply", action="store_true", help="Aplica la semilla contra DATABASE_URL")
    args = parser.parse_args()

    if args.apply:
        import asyncio

        from app import db

        async def run() -> None:
            await db.init_pool()
            try:
                print(await apply_seed())
            finally:
                await db.close_pool()

        asyncio.run(run())
        return

    sql = emit_sql()
    if args.out:
        from pathlib import Path

        Path(args.out).write_text(sql, encoding="utf-8")
        return
    print(sql)


if __name__ == "__main__":
    main()
