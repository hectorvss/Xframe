"""
OpenAI Images API (gpt-image-2 / gpt-image-1.5 / gpt-image-1-mini).

Es el único adaptador de imagen que se puede probar con la clave que el usuario ya tiene.
Sin él, la clave de OpenAI solo abre Sora 2 (vídeo), y los "elements" —personajes,
localizaciones, objetos, que en Xframe son imágenes de referencia— no se pueden crear.
Sin elements no hay continuidad de personaje que probar, así que este fichero desbloquea
el flujo central del producto, no una casilla del catálogo.

--------------------------------------------------------------------------------------
LA DECISIÓN DIFÍCIL: una API SÍNCRONA dentro de un contrato submit → poll
--------------------------------------------------------------------------------------

`GenerationAdapter` asume el patrón de los ocho proveedores de vídeo: `submit()` encola y
devuelve un identificador, `poll()` consulta hasta un estado terminal. La Images API de
OpenAI no encola nada: `POST /v1/images/generations` **bloquea y devuelve la imagen en la
misma respuesta**. No hay id de trabajo, no hay endpoint de estado, no hay nada que
poletear.

Se resuelve así, y esta es la parte que hay que entender antes de tocar el fichero:

- `submit()` hace la llamada real y **guarda el resultado ya terminal** en `ref.raw`.
- `poll()` no toca la red: lee `ref.raw` y devuelve el `ProviderJobStatus` correspondiente,
  terminal desde el primer ciclo.

Por qué así y no de las otras dos formas posibles:

1. *Meter un caso especial en el worker* ("si el adaptador es síncrono, sáltate el
   polling") sería trasladar un detalle de un proveedor a la capa que existe justamente
   para no conocerlos. El worker es donde vive el dinero: cada rama nueva ahí es una
   forma nueva de cobrar mal.
2. *Que `poll()` repitiera la llamada* generaría —y facturaría— una imagen distinta en
   cada ciclo. La Images API cobra por generación, no por consulta: sería pagar N veces
   por un plano y quedarnos con la última.

El precio de la decisión, dicho explícitamente para que nadie lo descubra en producción:
el resultado vive en memoria entre `submit()` y el primer `poll()`. `JobWorker._store_ref`
solo persiste `provider`, `external_id` y `poll_url` —no `raw`—, así que si el proceso
muere en esa ventana la imagen se pierde y ya está pagada. La ventana es de un ciclo de
polling en el mismo `_process`, y el barrido de jobs huérfanos reembolsa al usuario, así
que el fallo es acotado y no silencioso. Cerrarlo del todo exige persistir `ref.raw`, que
es trabajo del worker y no de aquí.

--------------------------------------------------------------------------------------
LA OTRA RAREZA: la salida es base64, no una URL
--------------------------------------------------------------------------------------

Los modelos GPT Image **siempre** devuelven `b64_json` [V]. `response_format: "url"` solo
existe en dall-e-2 y dall-e-3, que no son modelos de este catálogo. Es decir: no hay
ninguna URL que `JobWorker._land_output` pueda descargar con su `httpx.get()`.

Se devuelve un `data:` URI en `output_urls` porque es la única representación que cabe en
`ProviderJobStatus` sin cambiar el contrato, y los bytes crudos quedan además en
`raw["images_b64"]` para quien pueda usarlos directamente. El `OutputDownloader` del
worker **sí** sabe decodificar un `data:` URI (`app/jobs/download.py`, rama `data:`), así
que el camino descarga→bucket cierra el círculo end-to-end sin tocar nada aquí.
"""

from __future__ import annotations

import base64
import io
from decimal import Decimal
from typing import Any

from app.config import get_settings
from app.providers._http import UPLOAD_TIMEOUT, HttpAdapter, _money, job_ref
from app.providers.base import (
    GenerationRequest,
    Modality,
    ModelSpec,
    ProviderJobRef,
    ProviderJobStatus,
)
from app.tools.errors import ProviderRejectedError

#: Tamaños estándar de los modelos GPT Image [V]. Los modelos aceptan además
#: `WIDTHxHEIGHT` arbitrario divisible por 16, pero el precio de un tamaño libre no está
#: publicado, así que se restringe al set tarifado: generar barato y facturar a ciegas es
#: peor que no ofrecer el tamaño.
_SIZE_BY_ASPECT: dict[str, str] = {
    "1:1": "1024x1024",
    "16:9": "1536x1024",
    "9:16": "1024x1536",
    "4:3": "1536x1024",
    "3:4": "1024x1536",
}
_ALLOWED_SIZES = frozenset(_SIZE_BY_ASPECT.values())
_DEFAULT_SIZE = "1024x1024"

#: `quality` para modelos GPT Image [V]: `auto`, `low`, `medium`, `high`. (`standard`/`hd`
#: son de dall-e-3 y aquí darían 400.)
_ALLOWED_QUALITY = ("low", "medium", "high")
_DEFAULT_QUALITY = "medium"

#: Precio por imagen 1024x1024 según calidad, en USD.
#: NO VERIFICADO contra OpenAI: la página oficial de precios ya no publica el coste por
#: imagen (solo $/1M tokens y remite a una calculadora). Estas cifras salen de fuentes
#: secundarias de julio de 2026 para gpt-image-2. Se usan como estimación previa; el
#: importe real lo mide OpenAI en tokens de salida.
_QUALITY_RATIO: dict[str, Decimal] = {
    # Proporciones respecto a `medium`, NO dólares. El precio absoluto sale de
    # `gen_models.cost_per_image` del modelo concreto, que es lo que distingue a
    # `gpt-image-1-mini` de `gpt-image-2`. Los ratios se derivan de la tarifa publicada
    # del buque insignia (0.006 / 0.053 / 0.211 por imagen en low / medium / high).
    "low": Decimal("0.113"),
    "medium": Decimal("1"),
    "high": Decimal("3.981"),
}

#: NO VERIFICADO: los tamaños no cuadrados consumen ~1.5x los tokens de salida del
#: cuadrado. Se aplica al alza; equivocarse por arriba se ve en el precio antes de lanzar,
#: equivocarse por abajo se paga en margen y no da ningún error.
_SIZE_MULTIPLIER: dict[str, Decimal] = {
    "1024x1024": Decimal("1.0"),
    "1536x1024": Decimal("1.5"),
    "1024x1536": Decimal("1.5"),
}

#: NO VERIFICADO: la doc de edits documenta `image[]` como lista sin declarar un máximo
#: legible. Se topa en 8 por prudencia —cada referencia se factura como tokens de imagen
#: de entrada— y porque más de ocho referencias no mejora la continuidad, la diluye.
_MAX_REFERENCES = 8

#: Códigos y textos con los que OpenAI rechaza por moderación. Llegan como 400, que
#: `classify_http_error` ya clasifica como ajustable; esto solo mejora el mensaje que ve
#: el LLM para que reescriba el prompt en vez de reintentar el mismo.
_MODERATION_MARKERS = ("moderation_blocked", "content_policy", "safety_violation")


class OpenAIImageAdapter(HttpAdapter):
    """
    Adaptador de imagen de OpenAI.

    `provider_id` es `openai_image` y **no** `openai` a propósito. El registry indexa las
    fábricas por `provider_id` (`_FACTORIES[cls.provider_id] = cls`), así que reutilizar
    `openai` —el de `SoraAdapter`— no sería compartir credenciales: sería que la última
    clase registrada machacara a la otra y que todos los jobs de vídeo acabaran en el
    adaptador de imagen, o al revés. La clave de API sí se comparte, que es lo que el
    usuario espera.
    """

    provider_id = "openai_image"
    supported_modalities: tuple[Modality, ...] = ("image",)
    base_url = "https://api.openai.com"

    #: `poll()` no hace red (ver docstring del módulo), así que este valor no protege
    #: ningún rate limit: solo cumple el mínimo que exige el contrato. El worker toma
    #: `max(esto, job_poll_interval_s)` y duerme ese tiempo antes del primer poll, de modo
    #: que una imagen ya generada tarda un ciclo extra en aterrizar. Es el coste de no
    #: meter un caso especial en el worker.
    min_poll_interval_s = 1.0

    #: Vacío a propósito: este adaptador **nunca** entrega una URL. La API de imágenes
    #: responde en `b64_json` y aquí se devuelve un `data:` URI, que el worker decodifica
    #: sin tocar la red. No hay ningún host que abrir.
    output_domains: tuple[str, ...] = ()

    def auth_headers(self) -> dict[str, str]:
        key = self._require(get_settings().openai_api_key, "OPENAI_API_KEY")
        return {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}

    # -- submit --------------------------------------------------------------- #

    async def submit(self, req: GenerationRequest) -> ProviderJobRef:
        """
        Genera (o edita) la imagen **ya**, y empaqueta el resultado terminal en `ref.raw`.

        Dos caminos según haya referencias visuales o no:

        - Sin referencias → `POST /v1/images/generations`, cuerpo JSON.
        - Con referencias → `POST /v1/images/edits`, `multipart/form-data`. Es el camino
          que da continuidad de personaje: se le pasan las imágenes del element y el
          modelo mantiene la identidad en vez de inventar una cara nueva. Sin este camino
          el adaptador serviría para hacer bonitos, no para hacer una película.
        """
        references = self._ref_urls(req)[:_MAX_REFERENCES]
        if references:
            response = await self._submit_edit(req, references)
        else:
            response = await self.request(
                "POST",
                "/v1/images/generations",
                json=self._common_fields(req),
                timeout=UPLOAD_TIMEOUT,
            )

        body = response.json()
        images = [item.get("b64_json") for item in (body.get("data") or [])]
        images = [b for b in images if b]
        if not images:
            # 200 sin imagen: no es un estado que la API documente, pero devolver un ref
            # "vivo" haría que el worker poleteara para siempre algo que no existe.
            raise ProviderRejectedError(
                self.provider_id,
                f"la respuesta no trae ninguna imagen en data[].b64_json: {str(body)[:300]}",
            )

        mime = f"image/{body.get('output_format') or self._output_format(req)}"
        raw: dict[str, Any] = {
            "state": "succeeded",
            "images_b64": images,
            "mime_type": mime,
            "size": body.get("size"),
            "quality": body.get("quality"),
            "usage": body.get("usage"),
            # Aquí NO se publica `cost_usd`, y es deliberado. `_final_credits` lo usaría
            # para cobrar el importe medido en vez de la reserva, pero el precio depende
            # del modelo (`gen_models.cost_per_image`) y `submit` solo recibe la petición,
            # no el `ModelSpec`. Calcularlo sin esa referencia daba la misma cifra para
            # `gpt-image-1-mini` y para `gpt-image-2`, que cuestan más del triple uno que
            # otro. Sin este campo, el cierre cobra la reserva —que sí se calculó con el
            # spec— y eso es correcto; con un `cost_usd` mal calculado, no lo sería.
            # Para cobrar lo medido de verdad hay que derivarlo de `usage` en tokens con
            # la tarifa del modelo, y eso necesita el spec en esta capa.
        }

        # No hay id de trabajo porque no hay trabajo: se sintetiza uno estable a partir de
        # `created`, que es lo único que la respuesta ofrece como identificador. Solo se
        # usa para trazas y para que `_store_ref` tenga algo que escribir.
        external_id = f"img-{body.get('created') or 'sync'}"
        return job_ref(self.provider_id, external_id, poll_url=None, raw=raw)

    async def _submit_edit(
        self, req: GenerationRequest, references: list[str]
    ) -> Any:
        """
        Camino de edición/variación con imagen de referencia (continuidad de personaje).

        Las referencias se **descargan y se suben como ficheros**: el endpoint de edits es
        `multipart/form-data` y no acepta URLs [V]. Se usa `fetch_image_inline()` porque ya
        resuelve lo delicado —descargar sin mandarle a un bucket ajeno la cabecera
        `Authorization` de OpenAI, y distinguir una URL firmada caducada de un fallo de
        red— y se deshace el base64 porque aquí hacen falta los bytes.
        """
        files: list[tuple[str, tuple[str, bytes, str]]] = []
        source_bytes: bytes | None = None
        for index, url in enumerate(references):
            mime, encoded = await self.fetch_image_inline(url)
            decoded = base64.b64decode(encoded)
            if index == 0:
                source_bytes = decoded
            extension = mime.split("/")[-1] or "png"
            files.append(
                # `image[]` y no `image`: con varias referencias el nombre en singular
                # solo transporta la primera, y las demás se pierden sin ningún error.
                ("image[]", (f"reference_{index}.{extension}", decoded, mime))
            )

        geometries = req.extra.get("mask_geometry")
        if source_bytes and isinstance(geometries, list) and geometries:
            from PIL import Image, ImageDraw

            with Image.open(io.BytesIO(source_bytes)) as source_image:
                width, height = source_image.size
            # Opaque pixels are preserved; transparent pixels are regenerated.
            mask = Image.new("RGBA", (width, height), (255, 255, 255, 255))
            draw = ImageDraw.Draw(mask)
            for geometry in geometries:
                if not isinstance(geometry, dict):
                    continue
                if geometry.get("type") == "rect":
                    x = max(0.0, min(1.0, float(geometry.get("x", 0))))
                    y = max(0.0, min(1.0, float(geometry.get("y", 0))))
                    w = max(0.0, min(1.0 - x, float(geometry.get("width", 0))))
                    h = max(0.0, min(1.0 - y, float(geometry.get("height", 0))))
                    draw.rectangle(
                        (int(x * width), int(y * height), int((x + w) * width), int((y + h) * height)),
                        fill=(0, 0, 0, 0),
                    )
                elif geometry.get("type") == "drawing":
                    points = [
                        (int(float(point["x"]) * width), int(float(point["y"]) * height))
                        for point in geometry.get("points", [])
                        if isinstance(point, dict) and "x" in point and "y" in point
                    ]
                    if len(points) > 1:
                        draw.line(points, fill=(0, 0, 0, 0), width=max(8, int(width * 0.02)))
            buffer = io.BytesIO()
            mask.save(buffer, format="PNG")
            files.append(("mask", ("mask.png", buffer.getvalue(), "image/png")))

        # En multipart todo valor es texto. Los booleanos y enteros del JSON se
        # convierten aquí; mandarlos como tal produce un 400 poco descriptivo.
        data = {k: str(v) for k, v in self._common_fields(req).items()}

        return await self.request(
            "POST",
            "/v1/images/edits",
            data=data,
            files=files,
            timeout=UPLOAD_TIMEOUT,
        )

    def _common_fields(self, req: GenerationRequest) -> dict[str, Any]:
        """
        Campos que comparten `generations` y `edits`.

        Deliberadamente **no** se manda:

        - `response_format`: solo existe en dall-e-* [V]. En un modelo GPT Image es un
          parámetro desconocido, y OpenAI rechaza lo que no conoce en vez de ignorarlo
          (misma lección que dejó `seed` en el adaptador de Sora).
        - `seed`: la Images API no lo expone [V]. La reproducibilidad se consigue con
          referencias, no con semilla.
        - `negative_prompt`: no existe. La negación va dentro del prompt o no va.
        """
        fields: dict[str, Any] = {
            "model": req.model_id,
            "prompt": self._styled_prompt(req),
            "size": self._size_for(req),
            "quality": self._quality_for(req),
            "n": 1,
            "output_format": self._output_format(req),
            # `moderation: "low"` es filtrado menos restrictivo, no ausente. Se deja en el
            # `auto` por defecto salvo petición explícita: un storyboard rechazado a mitad
            # obliga a regenerar la serie, pero relajar la moderación por defecto es una
            # decisión de producto que no toca a un adaptador.
        }
        if req.negative_prompt:
            # Sin campo propio, la única forma honesta de no perder la instrucción.
            fields["prompt"] = f"{fields['prompt']}. Evita: {req.negative_prompt}"

        background = req.extra.get("background")
        if background in ("transparent", "opaque", "auto"):
            # `transparent` exige png o webp [V]; se fuerza para que no salga un 400.
            fields["background"] = background
            if background == "transparent" and fields["output_format"] == "jpeg":
                fields["output_format"] = "png"

        moderation = req.extra.get("moderation")
        if moderation in ("low", "auto"):
            fields["moderation"] = moderation

        return fields

    def _size_for(self, req: GenerationRequest) -> str:
        if req.resolution and req.resolution in _ALLOWED_SIZES:
            return req.resolution
        return _SIZE_BY_ASPECT.get(req.aspect or "1:1", _DEFAULT_SIZE)

    @staticmethod
    def _quality_for(req: GenerationRequest) -> str:
        quality = str(req.extra.get("quality", "")).lower()
        return quality if quality in _ALLOWED_QUALITY else _DEFAULT_QUALITY

    @staticmethod
    def _output_format(req: GenerationRequest) -> str:
        fmt = str(req.extra.get("output_format", "")).lower()
        # png por defecto: es sin pérdidas, y estas imágenes son referencias que después
        # se vuelven a meter en otro modelo. Un jpeg reencodeado varias veces degrada
        # justo la cara que intentamos mantener igual.
        return fmt if fmt in ("png", "jpeg", "webp") else "png"

    # -- poll ----------------------------------------------------------------- #

    async def poll(self, ref: ProviderJobRef) -> ProviderJobStatus:
        """
        Devuelve el resultado que `submit()` ya obtuvo. **No hace ninguna llamada.**

        Tampoco pasa por `throttled_poll_gate()`: ese gate existe para no superar el rate
        limit del proveedor, y aquí no hay petición que limitar. Esperar por él solo
        añadiría latencia a un resultado que está en memoria.
        """
        raw = ref.raw or {}
        images = raw.get("images_b64") or []
        if not images:
            # Solo se llega aquí si alguien reconstruyó el ref sin `raw` — típicamente
            # `JobWorker._load_ref`, que no persiste `raw` (ver docstring del módulo).
            return ProviderJobStatus(
                state="failed",
                error=(
                    "el resultado síncrono de la Images API no está en el ProviderJobRef. "
                    "La imagen se generó y se facturó, pero este proceso ya no la tiene; "
                    "hay que relanzar la generación."
                ),
                raw=raw,
            )

        mime = raw.get("mime_type") or "image/png"
        return ProviderJobStatus(
            state="succeeded",
            progress=1.0,
            output_urls=[f"data:{mime};base64,{b64}" for b64 in images],
            raw=raw,
        )

    async def cancel(self, ref: ProviderJobRef) -> None:
        """
        No-op, y no por pereza: cuando existe un `ref` la imagen **ya está generada y
        facturada**. No hay trabajo en vuelo que cancelar, y llamar a cualquier endpoint
        aquí sería inventarse una API que no existe.
        """
        return None

    # -- coste ---------------------------------------------------------------- #

    def estimate_cost(self, req: GenerationRequest, spec: ModelSpec) -> Decimal:
        """
        Precio por imagen según calidad y tamaño, no una tarifa plana.

        OpenAI no cobra por imagen: mide tokens de imagen de salida, y el número de tokens
        depende del par (calidad, tamaño). Un precio plano se equivocaría por un factor de
        35 entre `low` y `high`, que es la diferencia entre cobrar de más hasta espantar al
        usuario y generar por debajo de coste.

        `spec.cost_per_image` de la semilla se usa como suelo: si un día la tabla local se
        queda vieja y baja de la tarifa sembrada, se cobra la sembrada.
        """
        return self._price_for(req, spec)

    def _price_for(self, req: GenerationRequest, spec: ModelSpec) -> Decimal:
        # El ancla es el precio del MODELO, no una tarifa global. La tabla de calidad son
        # ahora proporciones respecto a `medium`, no dólares: sus valores absolutos
        # estaban calibrados sobre el buque insignia, así que `gpt-image-1-mini` —que
        # cuesta un tercio— se cobraba exactamente igual que `gpt-image-2`. Se detectó
        # ejecutando una generación de verdad: catálogo 0.015, cobrado 0.0795.
        anchor = Decimal(getattr(spec, "cost_per_image", None) or spec.cost_per_second)
        ratio = _QUALITY_RATIO.get(self._quality_for(req), Decimal("1"))
        base = anchor * ratio
        multiplier = _SIZE_MULTIPLIER.get(self._size_for(req), Decimal("1.5"))
        references = len(self._ref_urls(req)[:_MAX_REFERENCES])
        cost = base * multiplier
        if references:
            # NO VERIFICADO: se estima ~$0.01 por referencia de entrada (tokens de imagen
            # de entrada a $8-10/1M). Ignorarlas subestimaría el coste justo en el caso
            # normal de este producto, donde casi toda generación lleva elements.
            cost += Decimal("0.01") * references
        return _money(cost)

    def normalize_error(self, exc: Exception) -> Exception:
        """
        Igual que la base, salvo que un rechazo por moderación se reetiqueta con una
        instrucción accionable: el LLM tiene que reescribir el prompt, no reintentarlo.
        """
        normalized = super().normalize_error(exc)
        text = str(normalized).lower()
        if any(marker in text for marker in _MODERATION_MARKERS):
            return ProviderRejectedError(
                self.provider_id,
                f"{normalized} — la moderación de OpenAI bloqueó esta petición. "
                f"Reescribe el prompt evitando el elemento señalado; reintentarlo igual "
                f"da el mismo rechazo y se cuenta contra la cuota.",
            )
        return normalized
