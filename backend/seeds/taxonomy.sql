-- Xframe · semilla de taxonomía
--
-- GENERADO. No editar a mano: se regenera con
--   python -m app.providers.seed --emit-sql > backend/seeds/taxonomy.sql
-- La fuente de verdad es backend/app/providers/seed.py.
--
-- credits_per_unit = ceil(coste_usd * 40 * 1.0)
-- Cada modelo lleva la confianza de su precio según el informe 06:
--   [V] verificado · [S] secundario · [I] inferido.
-- Los [S] y [I] son deuda: un precio bajo equivocado se paga en margen y no
-- produce ningún error visible.

begin;

-- ------------------------------------------------------------------
-- gen_models
-- ------------------------------------------------------------------

-- Google Veo 3.1 · $0.40/segundo · [V] verificado en fuente primaria
insert into public.gen_models (
  id, family, provider, modality, label, description_llm,
  min_duration_s, max_duration_s, resolutions, aspects,
  supports_i2v, supports_last_frame, supports_char_ref, supports_audio,
  cost_per_second, cost_per_image, credits_per_unit,
  min_plan, status, sunset_at, sort
) values (
  'veo-3.1-generate-preview', 'Google Veo', 'google', 'video',
  'Google Veo 3.1',
  'Elige este cuando el plano tenga que quedar bien a la primera y el presupuesto lo permita: es el más fiable en fisica, manos y texto legible, y el unico que genera dialogo y ambiente sincronizados sin pasar por una capa de audio aparte. Es de los caros, asi que reservalo para los planos que el espectador va a mirar de verdad, no para pruebas de encuadre.',
  4, 8,
  array['720p', '1080p', '4K']::text[], array['16:9', '9:16']::text[],
  true, true, true, true,
  0.40, null, 16,
  'pro', 'active', null, 10
)
on conflict (id) do update set
  family = excluded.family, provider = excluded.provider,
  modality = excluded.modality, label = excluded.label,
  description_llm = excluded.description_llm,
  min_duration_s = excluded.min_duration_s, max_duration_s = excluded.max_duration_s,
  resolutions = excluded.resolutions, aspects = excluded.aspects,
  supports_i2v = excluded.supports_i2v,
  supports_last_frame = excluded.supports_last_frame,
  supports_char_ref = excluded.supports_char_ref,
  supports_audio = excluded.supports_audio,
  cost_per_second = excluded.cost_per_second,
  cost_per_image = excluded.cost_per_image,
  credits_per_unit = excluded.credits_per_unit,
  min_plan = excluded.min_plan, status = excluded.status,
  sunset_at = excluded.sunset_at, sort = excluded.sort,
  updated_at = now();

-- Google Veo 3.1 Lite · $0.05/segundo · [V] verificado en fuente primaria
insert into public.gen_models (
  id, family, provider, modality, label, description_llm,
  min_duration_s, max_duration_s, resolutions, aspects,
  supports_i2v, supports_last_frame, supports_char_ref, supports_audio,
  cost_per_second, cost_per_image, credits_per_unit,
  min_plan, status, sunset_at, sort
) values (
  'veo-3.1-lite-generate-preview', 'Google Veo', 'google', 'video',
  'Google Veo 3.1 Lite',
  'El caballo de batalla: ocho veces mas barato que Veo 3.1 y con el mismo criterio de composicion, a cambio de menos detalle fino y menos aguante en movimiento rapido. Usalo para iterar encuadre y ritmo, y sube a Veo 3.1 solo el plano que ya sabes que se queda.',
  4, 8,
  array['720p', '1080p']::text[], array['16:9', '9:16']::text[],
  true, true, true, true,
  0.05, null, 2,
  'free', 'active', null, 11
)
on conflict (id) do update set
  family = excluded.family, provider = excluded.provider,
  modality = excluded.modality, label = excluded.label,
  description_llm = excluded.description_llm,
  min_duration_s = excluded.min_duration_s, max_duration_s = excluded.max_duration_s,
  resolutions = excluded.resolutions, aspects = excluded.aspects,
  supports_i2v = excluded.supports_i2v,
  supports_last_frame = excluded.supports_last_frame,
  supports_char_ref = excluded.supports_char_ref,
  supports_audio = excluded.supports_audio,
  cost_per_second = excluded.cost_per_second,
  cost_per_image = excluded.cost_per_image,
  credits_per_unit = excluded.credits_per_unit,
  min_plan = excluded.min_plan, status = excluded.status,
  sunset_at = excluded.sunset_at, sort = excluded.sort,
  updated_at = now();

-- Google Veo 3.1 Fast · $0.10/segundo · [V] verificado en fuente primaria
insert into public.gen_models (
  id, family, provider, modality, label, description_llm,
  min_duration_s, max_duration_s, resolutions, aspects,
  supports_i2v, supports_last_frame, supports_char_ref, supports_audio,
  cost_per_second, cost_per_image, credits_per_unit,
  min_plan, status, sunset_at, sort
) values (
  'veo-3.1-fast-generate-preview', 'Google Veo', 'google', 'video',
  'Google Veo 3.1 Fast',
  'Generacion mas rapida de la familia, pensada para tanteo. Si el usuario esta explorando ideas y va a descartar la mayoria, esto le da respuesta en el menor tiempo posible. No lo uses para el corte final.',
  4, 8,
  array['720p', '1080p', '4K']::text[], array['16:9', '9:16']::text[],
  true, true, true, true,
  0.10, null, 4,
  'free', 'active', null, 12
)
on conflict (id) do update set
  family = excluded.family, provider = excluded.provider,
  modality = excluded.modality, label = excluded.label,
  description_llm = excluded.description_llm,
  min_duration_s = excluded.min_duration_s, max_duration_s = excluded.max_duration_s,
  resolutions = excluded.resolutions, aspects = excluded.aspects,
  supports_i2v = excluded.supports_i2v,
  supports_last_frame = excluded.supports_last_frame,
  supports_char_ref = excluded.supports_char_ref,
  supports_audio = excluded.supports_audio,
  cost_per_second = excluded.cost_per_second,
  cost_per_image = excluded.cost_per_image,
  credits_per_unit = excluded.credits_per_unit,
  min_plan = excluded.min_plan, status = excluded.status,
  sunset_at = excluded.sunset_at, sort = excluded.sort,
  updated_at = now();

-- Gemini Omni Flash · $0.10/segundo · [V] verificado en fuente primaria
insert into public.gen_models (
  id, family, provider, modality, label, description_llm,
  min_duration_s, max_duration_s, resolutions, aspects,
  supports_i2v, supports_last_frame, supports_char_ref, supports_audio,
  cost_per_second, cost_per_image, credits_per_unit,
  min_plan, status, sunset_at, sort
) values (
  'gemini-omni-flash', 'Gemini', 'google', 'video',
  'Gemini Omni Flash',
  'El mejor del catalogo manteniendo la misma cara entre planos distintos: Google lo posiciona explicitamente por encima de Veo 3.1 en consistencia de personaje y en refinamiento iterativo. Es la eleccion por defecto cuando la secuencia sigue a un personaje a lo largo de varios planos y la continuidad importa mas que el acabado de cada uno.',
  4, 10,
  array['720p']::text[], array['16:9', '9:16', '1:1']::text[],
  true, false, true, true,
  0.10, null, 4,
  'free', 'active', null, 13
)
on conflict (id) do update set
  family = excluded.family, provider = excluded.provider,
  modality = excluded.modality, label = excluded.label,
  description_llm = excluded.description_llm,
  min_duration_s = excluded.min_duration_s, max_duration_s = excluded.max_duration_s,
  resolutions = excluded.resolutions, aspects = excluded.aspects,
  supports_i2v = excluded.supports_i2v,
  supports_last_frame = excluded.supports_last_frame,
  supports_char_ref = excluded.supports_char_ref,
  supports_audio = excluded.supports_audio,
  cost_per_second = excluded.cost_per_second,
  cost_per_image = excluded.cost_per_image,
  credits_per_unit = excluded.credits_per_unit,
  min_plan = excluded.min_plan, status = excluded.status,
  sunset_at = excluded.sunset_at, sort = excluded.sort,
  updated_at = now();

-- OpenAI Sora 2 · $0.10/segundo · [V] verificado en fuente primaria
insert into public.gen_models (
  id, family, provider, modality, label, description_llm,
  min_duration_s, max_duration_s, resolutions, aspects,
  supports_i2v, supports_last_frame, supports_char_ref, supports_audio,
  cost_per_second, cost_per_image, credits_per_unit,
  min_plan, status, sunset_at, sort
) values (
  'sora-2', 'OpenAI Sora', 'openai', 'video',
  'OpenAI Sora 2',
  'Fuerte en escenas con varios personajes actuando a la vez y con dialogo que suena natural. AVISO: OpenAI apaga toda la Videos API el 24 de septiembre de 2026. No lo propongas para un proyecto que el usuario vaya a seguir editando despues de esa fecha; si ya hay planos hechos con el, avisale de que no podra regenerarlos.',
  4, 12,
  array['720p']::text[], array['16:9', '9:16']::text[],
  true, false, true, true,
  0.10, null, 4,
  'free', 'deprecated', '2026-09-24'::timestamptz, 20
)
on conflict (id) do update set
  family = excluded.family, provider = excluded.provider,
  modality = excluded.modality, label = excluded.label,
  description_llm = excluded.description_llm,
  min_duration_s = excluded.min_duration_s, max_duration_s = excluded.max_duration_s,
  resolutions = excluded.resolutions, aspects = excluded.aspects,
  supports_i2v = excluded.supports_i2v,
  supports_last_frame = excluded.supports_last_frame,
  supports_char_ref = excluded.supports_char_ref,
  supports_audio = excluded.supports_audio,
  cost_per_second = excluded.cost_per_second,
  cost_per_image = excluded.cost_per_image,
  credits_per_unit = excluded.credits_per_unit,
  min_plan = excluded.min_plan, status = excluded.status,
  sunset_at = excluded.sunset_at, sort = excluded.sort,
  updated_at = now();

-- OpenAI Sora 2 Pro · $0.30/segundo · [V] verificado en fuente primaria
insert into public.gen_models (
  id, family, provider, modality, label, description_llm,
  min_duration_s, max_duration_s, resolutions, aspects,
  supports_i2v, supports_last_frame, supports_char_ref, supports_audio,
  cost_per_second, cost_per_image, credits_per_unit,
  min_plan, status, sunset_at, sort
) values (
  'sora-2-pro', 'OpenAI Sora', 'openai', 'video',
  'OpenAI Sora 2 Pro',
  'Version de mas resolucion de Sora 2, con el mismo rango de duracion (hasta 12 segundos por plano). Comparte la fecha de apagado del 24 de septiembre de 2026, asi que vale para entregar ya, no para construir encima.',
  4, 12,
  array['720p', '1024p', '1080p']::text[], array['16:9', '9:16']::text[],
  true, false, true, true,
  0.30, null, 12,
  'pro', 'deprecated', '2026-09-24'::timestamptz, 21
)
on conflict (id) do update set
  family = excluded.family, provider = excluded.provider,
  modality = excluded.modality, label = excluded.label,
  description_llm = excluded.description_llm,
  min_duration_s = excluded.min_duration_s, max_duration_s = excluded.max_duration_s,
  resolutions = excluded.resolutions, aspects = excluded.aspects,
  supports_i2v = excluded.supports_i2v,
  supports_last_frame = excluded.supports_last_frame,
  supports_char_ref = excluded.supports_char_ref,
  supports_audio = excluded.supports_audio,
  cost_per_second = excluded.cost_per_second,
  cost_per_image = excluded.cost_per_image,
  credits_per_unit = excluded.credits_per_unit,
  min_plan = excluded.min_plan, status = excluded.status,
  sunset_at = excluded.sunset_at, sort = excluded.sort,
  updated_at = now();

-- OpenAI GPT Image 2 · $0.053/imagen · [S] fuente secundaria, re-verificar
-- NOTA: Precio de calidad media a 1024x1024 segun fuentes secundarias (jul 2026): low $0.006 / medium $0.053 / high $0.211. OpenAI factura por tokens de imagen de salida, no por imagen; ver _PRICE_BY_QUALITY en openai_image.py.
insert into public.gen_models (
  id, family, provider, modality, label, description_llm,
  min_duration_s, max_duration_s, resolutions, aspects,
  supports_i2v, supports_last_frame, supports_char_ref, supports_audio,
  cost_per_second, cost_per_image, credits_per_unit,
  min_plan, status, sunset_at, sort
) values (
  'gpt-image-2', 'OpenAI GPT Image', 'openai_image', 'image',
  'OpenAI GPT Image 2',
  'Empieza por aqui para CREAR un element: la cara de un personaje, una localizacion o un objeto que despues va a repetirse en toda la pieza. Tambien es el que hay que usar para generar el fotograma de referencia que luego se anima con un modelo de video. Entiende instrucciones largas y literales mejor que ningun otro del catalogo, asi que es el indicado cuando el usuario describe con precision lo que quiere ver. Si le pasas elements existentes, los toma como referencia y conserva la identidad en vez de inventar una cara nueva, que es lo que da continuidad entre vinetas.',
  null, null,
  array['1024x1024', '1536x1024', '1024x1536']::text[], array['1:1', '16:9', '9:16']::text[],
  false, false, true, false,
  0.053, 0.053, 3,
  'free', 'active', null, 1
)
on conflict (id) do update set
  family = excluded.family, provider = excluded.provider,
  modality = excluded.modality, label = excluded.label,
  description_llm = excluded.description_llm,
  min_duration_s = excluded.min_duration_s, max_duration_s = excluded.max_duration_s,
  resolutions = excluded.resolutions, aspects = excluded.aspects,
  supports_i2v = excluded.supports_i2v,
  supports_last_frame = excluded.supports_last_frame,
  supports_char_ref = excluded.supports_char_ref,
  supports_audio = excluded.supports_audio,
  cost_per_second = excluded.cost_per_second,
  cost_per_image = excluded.cost_per_image,
  credits_per_unit = excluded.credits_per_unit,
  min_plan = excluded.min_plan, status = excluded.status,
  sunset_at = excluded.sunset_at, sort = excluded.sort,
  updated_at = now();

-- OpenAI GPT Image 1.5 · $0.042/imagen · [I] INFERIDO, no verificado
-- NOTA: Precio INFERIDO por analogia con gpt-image-2; no hay tarifa por imagen publicada.
insert into public.gen_models (
  id, family, provider, modality, label, description_llm,
  min_duration_s, max_duration_s, resolutions, aspects,
  supports_i2v, supports_last_frame, supports_char_ref, supports_audio,
  cost_per_second, cost_per_image, credits_per_unit,
  min_plan, status, sunset_at, sort
) values (
  'gpt-image-1.5', 'OpenAI GPT Image', 'openai_image', 'image',
  'OpenAI GPT Image 1.5',
  'Generacion anterior a GPT Image 2, algo mas barata y con el mismo criterio de composicion. Sirve como plan B si GPT Image 2 esta saturado, y como escalon intermedio cuando el usuario quiere iterar varias veces sobre la misma idea antes de fijar el element definitivo. Para el element que se queda, sube a GPT Image 2.',
  null, null,
  array['1024x1024', '1536x1024', '1024x1536']::text[], array['1:1', '16:9', '9:16']::text[],
  false, false, true, false,
  0.042, 0.042, 2,
  'free', 'active', null, 2
)
on conflict (id) do update set
  family = excluded.family, provider = excluded.provider,
  modality = excluded.modality, label = excluded.label,
  description_llm = excluded.description_llm,
  min_duration_s = excluded.min_duration_s, max_duration_s = excluded.max_duration_s,
  resolutions = excluded.resolutions, aspects = excluded.aspects,
  supports_i2v = excluded.supports_i2v,
  supports_last_frame = excluded.supports_last_frame,
  supports_char_ref = excluded.supports_char_ref,
  supports_audio = excluded.supports_audio,
  cost_per_second = excluded.cost_per_second,
  cost_per_image = excluded.cost_per_image,
  credits_per_unit = excluded.credits_per_unit,
  min_plan = excluded.min_plan, status = excluded.status,
  sunset_at = excluded.sunset_at, sort = excluded.sort,
  updated_at = now();

-- OpenAI GPT Image 1 Mini · $0.015/imagen · [I] INFERIDO, no verificado
-- NOTA: Precio INFERIDO. Oficial: $2.50/1M tokens de entrada, frente a $8.00 de los grandes.
insert into public.gen_models (
  id, family, provider, modality, label, description_llm,
  min_duration_s, max_duration_s, resolutions, aspects,
  supports_i2v, supports_last_frame, supports_char_ref, supports_audio,
  cost_per_second, cost_per_image, credits_per_unit,
  min_plan, status, sunset_at, sort
) values (
  'gpt-image-1-mini', 'OpenAI GPT Image', 'openai_image', 'image',
  'OpenAI GPT Image 1 Mini',
  'El escalon barato de la familia. Es una herramienta de tanteo: sirve para comprobar si una descripcion de personaje o de localizacion produce algo parecido a lo que el usuario tiene en la cabeza, antes de gastar en el modelo bueno. No lo uses para el element definitivo, porque la cara que salga de aqui es la que habra que mantener en todos los planos siguientes.',
  null, null,
  array['1024x1024', '1536x1024', '1024x1536']::text[], array['1:1', '16:9', '9:16']::text[],
  false, false, true, false,
  0.015, 0.015, 1,
  'free', 'active', null, 3
)
on conflict (id) do update set
  family = excluded.family, provider = excluded.provider,
  modality = excluded.modality, label = excluded.label,
  description_llm = excluded.description_llm,
  min_duration_s = excluded.min_duration_s, max_duration_s = excluded.max_duration_s,
  resolutions = excluded.resolutions, aspects = excluded.aspects,
  supports_i2v = excluded.supports_i2v,
  supports_last_frame = excluded.supports_last_frame,
  supports_char_ref = excluded.supports_char_ref,
  supports_audio = excluded.supports_audio,
  cost_per_second = excluded.cost_per_second,
  cost_per_image = excluded.cost_per_image,
  credits_per_unit = excluded.credits_per_unit,
  min_plan = excluded.min_plan, status = excluded.status,
  sunset_at = excluded.sunset_at, sort = excluded.sort,
  updated_at = now();

-- OpenAI GPT Image 1 · $0.042/imagen · [S] fuente secundaria, re-verificar
-- NOTA: Marcado deprecated en la doc oficial de OpenAI; fecha de apagado 2026-10-23.
insert into public.gen_models (
  id, family, provider, modality, label, description_llm,
  min_duration_s, max_duration_s, resolutions, aspects,
  supports_i2v, supports_last_frame, supports_char_ref, supports_audio,
  cost_per_second, cost_per_image, credits_per_unit,
  min_plan, status, sunset_at, sort
) values (
  'gpt-image-1', 'OpenAI GPT Image', 'openai_image', 'image',
  'OpenAI GPT Image 1',
  'RETIRADO POR EL PROVEEDOR el 23 de octubre de 2026. No lo propongas. Si el usuario lo pide por nombre, explicale que OpenAI lo apaga y ofrecele gpt-image-2, que cubre el mismo caso de uso y ademas conserva mejor la identidad de las referencias que se le pasan.',
  null, null,
  array['1024x1024', '1536x1024', '1024x1536']::text[], array['1:1', '16:9', '9:16']::text[],
  false, false, true, false,
  0.042, 0.042, 2,
  'free', 'deprecated', '2026-10-23'::timestamptz, 4
)
on conflict (id) do update set
  family = excluded.family, provider = excluded.provider,
  modality = excluded.modality, label = excluded.label,
  description_llm = excluded.description_llm,
  min_duration_s = excluded.min_duration_s, max_duration_s = excluded.max_duration_s,
  resolutions = excluded.resolutions, aspects = excluded.aspects,
  supports_i2v = excluded.supports_i2v,
  supports_last_frame = excluded.supports_last_frame,
  supports_char_ref = excluded.supports_char_ref,
  supports_audio = excluded.supports_audio,
  cost_per_second = excluded.cost_per_second,
  cost_per_image = excluded.cost_per_image,
  credits_per_unit = excluded.credits_per_unit,
  min_plan = excluded.min_plan, status = excluded.status,
  sunset_at = excluded.sunset_at, sort = excluded.sort,
  updated_at = now();

-- Kling 3.0 · $0.075/segundo · [S] fuente secundaria, re-verificar
insert into public.gen_models (
  id, family, provider, modality, label, description_llm,
  min_duration_s, max_duration_s, resolutions, aspects,
  supports_i2v, supports_last_frame, supports_char_ref, supports_audio,
  cost_per_second, cost_per_image, credits_per_unit,
  min_plan, status, sunset_at, sort
) values (
  'kling-3.0', 'Kling', 'kling', 'video',
  'Kling 3.0',
  'El mejor para continuidad dura: acepta frame inicial y final a la vez y varias imagenes de referencia con correferencia de personajes, de modo que puedes encadenar planos que empalman de verdad en vez de parecerse. Tambien es el que mas aguanta sin cortar, hasta 15 segundos. Si el trabajo es una secuencia y no un plano suelto, empieza por aqui.',
  3, 15,
  array['720p', '1080p', '4K']::text[], array['16:9', '9:16', '1:1']::text[],
  true, true, true, true,
  0.075, null, 3,
  'free', 'active', null, 30
)
on conflict (id) do update set
  family = excluded.family, provider = excluded.provider,
  modality = excluded.modality, label = excluded.label,
  description_llm = excluded.description_llm,
  min_duration_s = excluded.min_duration_s, max_duration_s = excluded.max_duration_s,
  resolutions = excluded.resolutions, aspects = excluded.aspects,
  supports_i2v = excluded.supports_i2v,
  supports_last_frame = excluded.supports_last_frame,
  supports_char_ref = excluded.supports_char_ref,
  supports_audio = excluded.supports_audio,
  cost_per_second = excluded.cost_per_second,
  cost_per_image = excluded.cost_per_image,
  credits_per_unit = excluded.credits_per_unit,
  min_plan = excluded.min_plan, status = excluded.status,
  sunset_at = excluded.sunset_at, sort = excluded.sort,
  updated_at = now();

-- Kling 3.0 Turbo · $0.07/segundo · [S] fuente secundaria, re-verificar
insert into public.gen_models (
  id, family, provider, modality, label, description_llm,
  min_duration_s, max_duration_s, resolutions, aspects,
  supports_i2v, supports_last_frame, supports_char_ref, supports_audio,
  cost_per_second, cost_per_image, credits_per_unit,
  min_plan, status, sunset_at, sort
) values (
  'kling-3.0-turbo', 'Kling', 'kling', 'video',
  'Kling 3.0 Turbo',
  'Kling 3.0 con la cola priorizada: misma gramatica de continuidad, respuesta notablemente antes y algo menos de detalle. Es el que hay que usar mientras el usuario esta afinando el prompt de una secuencia, porque el ciclo de iteracion es lo que decide si acaba el trabajo.',
  3, 15,
  array['720p', '1080p']::text[], array['16:9', '9:16', '1:1']::text[],
  true, true, true, false,
  0.07, null, 3,
  'free', 'active', null, 31
)
on conflict (id) do update set
  family = excluded.family, provider = excluded.provider,
  modality = excluded.modality, label = excluded.label,
  description_llm = excluded.description_llm,
  min_duration_s = excluded.min_duration_s, max_duration_s = excluded.max_duration_s,
  resolutions = excluded.resolutions, aspects = excluded.aspects,
  supports_i2v = excluded.supports_i2v,
  supports_last_frame = excluded.supports_last_frame,
  supports_char_ref = excluded.supports_char_ref,
  supports_audio = excluded.supports_audio,
  cost_per_second = excluded.cost_per_second,
  cost_per_image = excluded.cost_per_image,
  credits_per_unit = excluded.credits_per_unit,
  min_plan = excluded.min_plan, status = excluded.status,
  sunset_at = excluded.sunset_at, sort = excluded.sort,
  updated_at = now();

-- Kling 3.0 Motion Control · $0.09/segundo · [I] INFERIDO, no verificado
-- NOTA: Precio inferido: no hay tarifa publicada para la variante motion-control.
insert into public.gen_models (
  id, family, provider, modality, label, description_llm,
  min_duration_s, max_duration_s, resolutions, aspects,
  supports_i2v, supports_last_frame, supports_char_ref, supports_audio,
  cost_per_second, cost_per_image, credits_per_unit,
  min_plan, status, sunset_at, sort
) values (
  'kling-3.0-motion-control', 'Kling', 'kling', 'video',
  'Kling 3.0 Motion Control',
  'Unica variante de Kling que acepta el movimiento de camara como parametro y no como descripcion en el prompt, y la unica que llega a 30 segundos. Elige esta cuando el usuario pida un movimiento concreto y reproducible (un travelling que tiene que ser igual en tres planos), no cuando solo quiera que la camara se mueva un poco.',
  3, 30,
  array['720p', '1080p']::text[], array['16:9', '9:16', '1:1']::text[],
  true, true, true, false,
  0.09, null, 4,
  'free', 'active', null, 32
)
on conflict (id) do update set
  family = excluded.family, provider = excluded.provider,
  modality = excluded.modality, label = excluded.label,
  description_llm = excluded.description_llm,
  min_duration_s = excluded.min_duration_s, max_duration_s = excluded.max_duration_s,
  resolutions = excluded.resolutions, aspects = excluded.aspects,
  supports_i2v = excluded.supports_i2v,
  supports_last_frame = excluded.supports_last_frame,
  supports_char_ref = excluded.supports_char_ref,
  supports_audio = excluded.supports_audio,
  cost_per_second = excluded.cost_per_second,
  cost_per_image = excluded.cost_per_image,
  credits_per_unit = excluded.credits_per_unit,
  min_plan = excluded.min_plan, status = excluded.status,
  sunset_at = excluded.sunset_at, sort = excluded.sort,
  updated_at = now();

-- Kling 2.5 Turbo · $0.07/segundo · [S] fuente secundaria, re-verificar
insert into public.gen_models (
  id, family, provider, modality, label, description_llm,
  min_duration_s, max_duration_s, resolutions, aspects,
  supports_i2v, supports_last_frame, supports_char_ref, supports_audio,
  cost_per_second, cost_per_image, credits_per_unit,
  min_plan, status, sunset_at, sort
) values (
  'kling-2.5-turbo', 'Kling', 'kling', 'video',
  'Kling 2.5 Turbo',
  'Generacion anterior, mas barata y todavia solida en movimiento humano. Sirve como plan B cuando 3.0 esta saturado o cuando el plano no necesita continuidad con ningun otro.',
  5, 10,
  array['720p', '1080p']::text[], array['16:9', '9:16', '1:1']::text[],
  true, true, false, false,
  0.07, null, 3,
  'free', 'active', null, 33
)
on conflict (id) do update set
  family = excluded.family, provider = excluded.provider,
  modality = excluded.modality, label = excluded.label,
  description_llm = excluded.description_llm,
  min_duration_s = excluded.min_duration_s, max_duration_s = excluded.max_duration_s,
  resolutions = excluded.resolutions, aspects = excluded.aspects,
  supports_i2v = excluded.supports_i2v,
  supports_last_frame = excluded.supports_last_frame,
  supports_char_ref = excluded.supports_char_ref,
  supports_audio = excluded.supports_audio,
  cost_per_second = excluded.cost_per_second,
  cost_per_image = excluded.cost_per_image,
  credits_per_unit = excluded.credits_per_unit,
  min_plan = excluded.min_plan, status = excluded.status,
  sunset_at = excluded.sunset_at, sort = excluded.sort,
  updated_at = now();

-- Kling 2.1 Master · $0.14/segundo · [I] INFERIDO, no verificado
-- NOTA: Precio inferido a partir del multiplicador pro sobre Kling 2.5.
insert into public.gen_models (
  id, family, provider, modality, label, description_llm,
  min_duration_s, max_duration_s, resolutions, aspects,
  supports_i2v, supports_last_frame, supports_char_ref, supports_audio,
  cost_per_second, cost_per_image, credits_per_unit,
  min_plan, status, sunset_at, sort
) values (
  'kling-2.1-master', 'Kling', 'kling', 'video',
  'Kling 2.1 Master',
  'Version de maxima calidad de la generacion 2.x, con acabado mas cinematico y mas coste. Tiene sentido si al usuario le gusto el resultado de 2.5 Turbo y quiere el mismo plano rematado, no como punto de partida.',
  5, 10,
  array['720p', '1080p']::text[], array['16:9', '9:16', '1:1']::text[],
  true, false, false, false,
  0.14, null, 6,
  'pro', 'active', null, 34
)
on conflict (id) do update set
  family = excluded.family, provider = excluded.provider,
  modality = excluded.modality, label = excluded.label,
  description_llm = excluded.description_llm,
  min_duration_s = excluded.min_duration_s, max_duration_s = excluded.max_duration_s,
  resolutions = excluded.resolutions, aspects = excluded.aspects,
  supports_i2v = excluded.supports_i2v,
  supports_last_frame = excluded.supports_last_frame,
  supports_char_ref = excluded.supports_char_ref,
  supports_audio = excluded.supports_audio,
  cost_per_second = excluded.cost_per_second,
  cost_per_image = excluded.cost_per_image,
  credits_per_unit = excluded.credits_per_unit,
  min_plan = excluded.min_plan, status = excluded.status,
  sunset_at = excluded.sunset_at, sort = excluded.sort,
  updated_at = now();

-- Minimax Hailuo 2.3 · $0.0934/segundo · [S] fuente secundaria, re-verificar
-- TARIFA PLANA POR CLIP: $0.56/clip. El coste por segundo de arriba está derivado dividiendo entre la duración mínima facturable (6 s) para no vender por debajo de coste en el clip corto. Ver resolve_cost_per_second() en seed.py.
-- NOTA: MiniMax factura POR CLIP ($0.19-0.56 segun resolucion), no por segundo. Se toma el extremo alto porque es el que aplica a 1080p, que es lo que se pide. El cost_per_second declarado (0.056 = 0.56/10s) era el bug: a 6s cobraba 0.96x del coste, es decir por debajo de coste.
insert into public.gen_models (
  id, family, provider, modality, label, description_llm,
  min_duration_s, max_duration_s, resolutions, aspects,
  supports_i2v, supports_last_frame, supports_char_ref, supports_audio,
  cost_per_second, cost_per_image, credits_per_unit,
  min_plan, status, sunset_at, sort
) values (
  'hailuo-2.3', 'Minimax Hailuo', 'minimax', 'video',
  'Minimax Hailuo 2.3',
  'El que mejor mueve: accion fisica, impactos, tela y pelo con inercia creible. Es la eleccion cuando el plano es dinamico y algo tiene que pasar. A cambio solo admite un personaje de referencia, asi que no lo uses en escenas donde dos caras conocidas comparten cuadro.',
  6, 10,
  array['720p', '1080p']::text[], array['16:9', '9:16', '1:1']::text[],
  true, false, true, false,
  0.0934, null, 4,
  'pro', 'active', null, 40
)
on conflict (id) do update set
  family = excluded.family, provider = excluded.provider,
  modality = excluded.modality, label = excluded.label,
  description_llm = excluded.description_llm,
  min_duration_s = excluded.min_duration_s, max_duration_s = excluded.max_duration_s,
  resolutions = excluded.resolutions, aspects = excluded.aspects,
  supports_i2v = excluded.supports_i2v,
  supports_last_frame = excluded.supports_last_frame,
  supports_char_ref = excluded.supports_char_ref,
  supports_audio = excluded.supports_audio,
  cost_per_second = excluded.cost_per_second,
  cost_per_image = excluded.cost_per_image,
  credits_per_unit = excluded.credits_per_unit,
  min_plan = excluded.min_plan, status = excluded.status,
  sunset_at = excluded.sunset_at, sort = excluded.sort,
  updated_at = now();

-- Minimax Hailuo 2.3 Fast · $0.0317/segundo · [S] fuente secundaria, re-verificar
-- TARIFA PLANA POR CLIP: $0.19/clip. El coste por segundo de arriba está derivado dividiendo entre la duración mínima facturable (6 s) para no vender por debajo de coste en el clip corto. Ver resolve_cost_per_second() en seed.py.
-- NOTA: MiniMax factura POR CLIP ($0.19), no por segundo. El cost_per_second declarado salia de dividir entre 10s y dejaba el clip de 6s bajo coste.
insert into public.gen_models (
  id, family, provider, modality, label, description_llm,
  min_duration_s, max_duration_s, resolutions, aspects,
  supports_i2v, supports_last_frame, supports_char_ref, supports_audio,
  cost_per_second, cost_per_image, credits_per_unit,
  min_plan, status, sunset_at, sort
) values (
  'hailuo-2.3-fast', 'Minimax Hailuo', 'minimax', 'video',
  'Minimax Hailuo 2.3 Fast',
  'La opcion mas rapida y barata del catalogo que todavia mueve bien. Usalo para probar si un plano concreto funciona antes de gastar en un modelo caro: encuadre, accion y ritmo se juzgan igual de bien aqui. No admite personaje de referencia, asi que en cuanto el plano tenga que respetar una cara ya definida hay que subir a 2.3 o a otro modelo. Se factura por clip completo, de modo que pedir menos duracion no lo abarata: si vas a generar, pide la duracion que necesita el plano.',
  6, 10,
  array['720p', '1080p']::text[], array['16:9', '9:16', '1:1']::text[],
  true, false, false, false,
  0.0317, null, 2,
  'free', 'active', null, 41
)
on conflict (id) do update set
  family = excluded.family, provider = excluded.provider,
  modality = excluded.modality, label = excluded.label,
  description_llm = excluded.description_llm,
  min_duration_s = excluded.min_duration_s, max_duration_s = excluded.max_duration_s,
  resolutions = excluded.resolutions, aspects = excluded.aspects,
  supports_i2v = excluded.supports_i2v,
  supports_last_frame = excluded.supports_last_frame,
  supports_char_ref = excluded.supports_char_ref,
  supports_audio = excluded.supports_audio,
  cost_per_second = excluded.cost_per_second,
  cost_per_image = excluded.cost_per_image,
  credits_per_unit = excluded.credits_per_unit,
  min_plan = excluded.min_plan, status = excluded.status,
  sunset_at = excluded.sunset_at, sort = excluded.sort,
  updated_at = now();

-- Minimax Hailuo 02 · $0.0750/segundo · [I] INFERIDO, no verificado
-- TARIFA PLANA POR CLIP: $0.45/clip. El coste por segundo de arriba está derivado dividiendo entre la duración mínima facturable (6 s) para no vender por debajo de coste en el clip corto. Ver resolve_cost_per_second() en seed.py.
-- NOTA: MiniMax factura por clip. Tarifa inferida; re-verificar antes de volumen.
insert into public.gen_models (
  id, family, provider, modality, label, description_llm,
  min_duration_s, max_duration_s, resolutions, aspects,
  supports_i2v, supports_last_frame, supports_char_ref, supports_audio,
  cost_per_second, cost_per_image, credits_per_unit,
  min_plan, status, sunset_at, sort
) values (
  'hailuo-02', 'Minimax Hailuo', 'minimax', 'video',
  'Minimax Hailuo 02',
  'Generacion anterior, todavia buena en fisica y algo mas predecible que 2.3 cuando el prompt es largo y detallado. Usalo si 2.3 esta reinterpretando demasiado lo que se le pide.',
  6, 10,
  array['720p', '1080p']::text[], array['16:9', '9:16', '1:1']::text[],
  true, false, false, false,
  0.0750, null, 3,
  'pro', 'active', null, 42
)
on conflict (id) do update set
  family = excluded.family, provider = excluded.provider,
  modality = excluded.modality, label = excluded.label,
  description_llm = excluded.description_llm,
  min_duration_s = excluded.min_duration_s, max_duration_s = excluded.max_duration_s,
  resolutions = excluded.resolutions, aspects = excluded.aspects,
  supports_i2v = excluded.supports_i2v,
  supports_last_frame = excluded.supports_last_frame,
  supports_char_ref = excluded.supports_char_ref,
  supports_audio = excluded.supports_audio,
  cost_per_second = excluded.cost_per_second,
  cost_per_image = excluded.cost_per_image,
  credits_per_unit = excluded.credits_per_unit,
  min_plan = excluded.min_plan, status = excluded.status,
  sunset_at = excluded.sunset_at, sort = excluded.sort,
  updated_at = now();

-- Minimax Hailuo 02 Fast · $0.0250/segundo · [I] INFERIDO, no verificado
-- TARIFA PLANA POR CLIP: $0.15/clip. El coste por segundo de arriba está derivado dividiendo entre la duración mínima facturable (6 s) para no vender por debajo de coste en el clip corto. Ver resolve_cost_per_second() en seed.py.
-- NOTA: MiniMax factura por clip. Tarifa inferida; re-verificar antes de volumen.
insert into public.gen_models (
  id, family, provider, modality, label, description_llm,
  min_duration_s, max_duration_s, resolutions, aspects,
  supports_i2v, supports_last_frame, supports_char_ref, supports_audio,
  cost_per_second, cost_per_image, credits_per_unit,
  min_plan, status, sunset_at, sort
) values (
  'hailuo-02-fast', 'Minimax Hailuo', 'minimax', 'video',
  'Minimax Hailuo 02 Fast',
  'El de menor resolucion de todo el catalogo. Es un modelo de descarte: sirve para comprobar si una idea de plano tiene sentido antes de gastar nada serio en ella. Nunca lo propongas como entrega, ni siquiera para una previsualizacion que el usuario vaya a ensenar a alguien.',
  6, 10,
  array['512p']::text[], array['16:9', '9:16', '1:1']::text[],
  true, false, false, false,
  0.0250, null, 1,
  'free', 'active', null, 43
)
on conflict (id) do update set
  family = excluded.family, provider = excluded.provider,
  modality = excluded.modality, label = excluded.label,
  description_llm = excluded.description_llm,
  min_duration_s = excluded.min_duration_s, max_duration_s = excluded.max_duration_s,
  resolutions = excluded.resolutions, aspects = excluded.aspects,
  supports_i2v = excluded.supports_i2v,
  supports_last_frame = excluded.supports_last_frame,
  supports_char_ref = excluded.supports_char_ref,
  supports_audio = excluded.supports_audio,
  cost_per_second = excluded.cost_per_second,
  cost_per_image = excluded.cost_per_image,
  credits_per_unit = excluded.credits_per_unit,
  min_plan = excluded.min_plan, status = excluded.status,
  sunset_at = excluded.sunset_at, sort = excluded.sort,
  updated_at = now();

-- Seedance 2.0 · $0.36/segundo · [S] fuente secundaria, re-verificar
-- NOTA: DESACTIVADO: el esquema de peticion no se ha podido verificar contra la doc oficial de BytePlus (docs.byteplus.com sirve el contenido por JS). Es el modelo mas caro del catalogo, asi que una llamada sin verificar se factura igual aunque no haga lo que se pidio. El adaptador falla con un error claro; ver app/providers/seedance.py para reactivarlo.
insert into public.gen_models (
  id, family, provider, modality, label, description_llm,
  min_duration_s, max_duration_s, resolutions, aspects,
  supports_i2v, supports_last_frame, supports_char_ref, supports_audio,
  cost_per_second, cost_per_image, credits_per_unit,
  min_plan, status, sunset_at, sort
) values (
  'seedance-2.0', 'Seedance', 'bytedance', 'video',
  'Seedance 2.0',
  'El acabado mas cinematografico del catalogo y, con diferencia, el mas caro: puede costar veinte veces mas por segundo que Hailuo Fast. Justificalo solo en el plano principal de una pieza, y avisa del coste antes de lanzarlo. Nunca lo uses para explorar.',
  4, 15,
  array['720p', '1080p', '4K']::text[], array['16:9', '9:16', '1:1']::text[],
  true, true, true, false,
  0.36, null, 15,
  'business', 'deprecated', null, 50
)
on conflict (id) do update set
  family = excluded.family, provider = excluded.provider,
  modality = excluded.modality, label = excluded.label,
  description_llm = excluded.description_llm,
  min_duration_s = excluded.min_duration_s, max_duration_s = excluded.max_duration_s,
  resolutions = excluded.resolutions, aspects = excluded.aspects,
  supports_i2v = excluded.supports_i2v,
  supports_last_frame = excluded.supports_last_frame,
  supports_char_ref = excluded.supports_char_ref,
  supports_audio = excluded.supports_audio,
  cost_per_second = excluded.cost_per_second,
  cost_per_image = excluded.cost_per_image,
  credits_per_unit = excluded.credits_per_unit,
  min_plan = excluded.min_plan, status = excluded.status,
  sunset_at = excluded.sunset_at, sort = excluded.sort,
  updated_at = now();

-- Seedance 2.0 Fast · $0.12/segundo · [I] INFERIDO, no verificado
-- NOTA: DESACTIVADO: el esquema de peticion no se ha podido verificar contra la doc oficial de BytePlus (docs.byteplus.com sirve el contenido por JS). Es el modelo mas caro del catalogo, asi que una llamada sin verificar se factura igual aunque no haga lo que se pidio. El adaptador falla con un error claro; ver app/providers/seedance.py para reactivarlo.
insert into public.gen_models (
  id, family, provider, modality, label, description_llm,
  min_duration_s, max_duration_s, resolutions, aspects,
  supports_i2v, supports_last_frame, supports_char_ref, supports_audio,
  cost_per_second, cost_per_image, credits_per_unit,
  min_plan, status, sunset_at, sort
) values (
  'seedance-2.0-fast', 'Seedance', 'bytedance', 'video',
  'Seedance 2.0 Fast',
  'Conserva el criterio fotografico de Seedance 2.0 a un coste que ya permite iterar. Si el usuario quiere ese look concreto, empieza aqui y sube al modelo grande solo para el render final.',
  4, 15,
  array['720p']::text[], array['16:9', '9:16', '1:1']::text[],
  true, false, true, false,
  0.12, null, 5,
  'pro', 'deprecated', null, 51
)
on conflict (id) do update set
  family = excluded.family, provider = excluded.provider,
  modality = excluded.modality, label = excluded.label,
  description_llm = excluded.description_llm,
  min_duration_s = excluded.min_duration_s, max_duration_s = excluded.max_duration_s,
  resolutions = excluded.resolutions, aspects = excluded.aspects,
  supports_i2v = excluded.supports_i2v,
  supports_last_frame = excluded.supports_last_frame,
  supports_char_ref = excluded.supports_char_ref,
  supports_audio = excluded.supports_audio,
  cost_per_second = excluded.cost_per_second,
  cost_per_image = excluded.cost_per_image,
  credits_per_unit = excluded.credits_per_unit,
  min_plan = excluded.min_plan, status = excluded.status,
  sunset_at = excluded.sunset_at, sort = excluded.sort,
  updated_at = now();

-- Seedance 2.0 Mini · $0.06/segundo · [I] INFERIDO, no verificado
-- NOTA: DESACTIVADO: el esquema de peticion no se ha podido verificar contra la doc oficial de BytePlus (docs.byteplus.com sirve el contenido por JS). Es el modelo mas caro del catalogo, asi que una llamada sin verificar se factura igual aunque no haga lo que se pidio. El adaptador falla con un error claro; ver app/providers/seedance.py para reactivarlo.
insert into public.gen_models (
  id, family, provider, modality, label, description_llm,
  min_duration_s, max_duration_s, resolutions, aspects,
  supports_i2v, supports_last_frame, supports_char_ref, supports_audio,
  cost_per_second, cost_per_image, credits_per_unit,
  min_plan, status, sunset_at, sort
) values (
  'seedance-2.0-mini', 'Seedance', 'bytedance', 'video',
  'Seedance 2.0 Mini',
  'El escalon barato de Seedance. Pierde detalle en fondos y en iluminacion compleja, pero mantiene el encuadre y el ritmo, que es lo que necesitas para decidir si un plano entra en el montaje.',
  4, 15,
  array['720p']::text[], array['16:9', '9:16', '1:1']::text[],
  true, false, false, false,
  0.06, null, 3,
  'free', 'deprecated', null, 52
)
on conflict (id) do update set
  family = excluded.family, provider = excluded.provider,
  modality = excluded.modality, label = excluded.label,
  description_llm = excluded.description_llm,
  min_duration_s = excluded.min_duration_s, max_duration_s = excluded.max_duration_s,
  resolutions = excluded.resolutions, aspects = excluded.aspects,
  supports_i2v = excluded.supports_i2v,
  supports_last_frame = excluded.supports_last_frame,
  supports_char_ref = excluded.supports_char_ref,
  supports_audio = excluded.supports_audio,
  cost_per_second = excluded.cost_per_second,
  cost_per_image = excluded.cost_per_image,
  credits_per_unit = excluded.credits_per_unit,
  min_plan = excluded.min_plan, status = excluded.status,
  sunset_at = excluded.sunset_at, sort = excluded.sort,
  updated_at = now();

-- Seedance 1.0 Pro · $0.10/segundo · [I] INFERIDO, no verificado
-- NOTA: DESACTIVADO: el esquema de peticion no se ha podido verificar contra la doc oficial de BytePlus (docs.byteplus.com sirve el contenido por JS). Es el modelo mas caro del catalogo, asi que una llamada sin verificar se factura igual aunque no haga lo que se pidio. El adaptador falla con un error claro; ver app/providers/seedance.py para reactivarlo.
insert into public.gen_models (
  id, family, provider, modality, label, description_llm,
  min_duration_s, max_duration_s, resolutions, aspects,
  supports_i2v, supports_last_frame, supports_char_ref, supports_audio,
  cost_per_second, cost_per_image, credits_per_unit,
  min_plan, status, sunset_at, sort
) values (
  'seedance-1.0-pro', 'Seedance', 'bytedance', 'video',
  'Seedance 1.0 Pro',
  'Generacion anterior, mas conservadora y con menos tendencia a inventarse movimiento que no estaba en el prompt. Util cuando Seedance 2.0 esta sobreactuando el plano.',
  5, 10,
  array['720p', '1080p']::text[], array['16:9', '9:16', '1:1']::text[],
  true, false, false, false,
  0.10, null, 4,
  'free', 'deprecated', null, 53
)
on conflict (id) do update set
  family = excluded.family, provider = excluded.provider,
  modality = excluded.modality, label = excluded.label,
  description_llm = excluded.description_llm,
  min_duration_s = excluded.min_duration_s, max_duration_s = excluded.max_duration_s,
  resolutions = excluded.resolutions, aspects = excluded.aspects,
  supports_i2v = excluded.supports_i2v,
  supports_last_frame = excluded.supports_last_frame,
  supports_char_ref = excluded.supports_char_ref,
  supports_audio = excluded.supports_audio,
  cost_per_second = excluded.cost_per_second,
  cost_per_image = excluded.cost_per_image,
  credits_per_unit = excluded.credits_per_unit,
  min_plan = excluded.min_plan, status = excluded.status,
  sunset_at = excluded.sunset_at, sort = excluded.sort,
  updated_at = now();

-- Wan 2.7 · $0.10/segundo · [S] fuente secundaria, re-verificar
insert into public.gen_models (
  id, family, provider, modality, label, description_llm,
  min_duration_s, max_duration_s, resolutions, aspects,
  supports_i2v, supports_last_frame, supports_char_ref, supports_audio,
  cost_per_second, cost_per_image, credits_per_unit,
  min_plan, status, sunset_at, sort
) values (
  'wan-2.7', 'Wan', 'wan', 'video',
  'Wan 2.7',
  'Acepta prompts muy largos (miles de caracteres) y hasta nueve imagenes de entrada, asi que es el que mejor obedece una descripcion de plano minuciosa. Si el usuario ha escrito un parrafo entero describiendo lo que quiere, mandalo aqui en vez de resumirlo para otro modelo.',
  2, 15,
  array['720p', '1080p']::text[], array['16:9', '9:16', '1:1']::text[],
  true, true, true, false,
  0.10, null, 4,
  'free', 'active', null, 60
)
on conflict (id) do update set
  family = excluded.family, provider = excluded.provider,
  modality = excluded.modality, label = excluded.label,
  description_llm = excluded.description_llm,
  min_duration_s = excluded.min_duration_s, max_duration_s = excluded.max_duration_s,
  resolutions = excluded.resolutions, aspects = excluded.aspects,
  supports_i2v = excluded.supports_i2v,
  supports_last_frame = excluded.supports_last_frame,
  supports_char_ref = excluded.supports_char_ref,
  supports_audio = excluded.supports_audio,
  cost_per_second = excluded.cost_per_second,
  cost_per_image = excluded.cost_per_image,
  credits_per_unit = excluded.credits_per_unit,
  min_plan = excluded.min_plan, status = excluded.status,
  sunset_at = excluded.sunset_at, sort = excluded.sort,
  updated_at = now();

-- Wan 2.5 · $0.05/segundo · [S] fuente secundaria, re-verificar
insert into public.gen_models (
  id, family, provider, modality, label, description_llm,
  min_duration_s, max_duration_s, resolutions, aspects,
  supports_i2v, supports_last_frame, supports_char_ref, supports_audio,
  cost_per_second, cost_per_image, credits_per_unit,
  min_plan, status, sunset_at, sort
) values (
  'wan-2.5', 'Wan', 'wan', 'video',
  'Wan 2.5',
  'El mas barato del catalogo que genera audio nativo. Para un plano de ambiente o un recurso de relleno con sonido, es dificil de justificar gastar mas. La calidad de imagen es visiblemente inferior a Veo o Kling.',
  5, 10,
  array['480p', '720p', '1080p']::text[], array['16:9', '9:16', '1:1']::text[],
  true, true, false, true,
  0.05, null, 2,
  'free', 'active', null, 61
)
on conflict (id) do update set
  family = excluded.family, provider = excluded.provider,
  modality = excluded.modality, label = excluded.label,
  description_llm = excluded.description_llm,
  min_duration_s = excluded.min_duration_s, max_duration_s = excluded.max_duration_s,
  resolutions = excluded.resolutions, aspects = excluded.aspects,
  supports_i2v = excluded.supports_i2v,
  supports_last_frame = excluded.supports_last_frame,
  supports_char_ref = excluded.supports_char_ref,
  supports_audio = excluded.supports_audio,
  cost_per_second = excluded.cost_per_second,
  cost_per_image = excluded.cost_per_image,
  credits_per_unit = excluded.credits_per_unit,
  min_plan = excluded.min_plan, status = excluded.status,
  sunset_at = excluded.sunset_at, sort = excluded.sort,
  updated_at = now();

-- Wan 2.2 Plus · $0.10/segundo · [S] fuente secundaria, re-verificar
insert into public.gen_models (
  id, family, provider, modality, label, description_llm,
  min_duration_s, max_duration_s, resolutions, aspects,
  supports_i2v, supports_last_frame, supports_char_ref, supports_audio,
  cost_per_second, cost_per_image, credits_per_unit,
  min_plan, status, sunset_at, sort
) values (
  'wan-2.2-plus', 'Wan', 'wan', 'video',
  'Wan 2.2 Plus',
  'Clips cortos, rapidos y sin audio, con duracion fija. Es una herramienta de tanteo: sirve para comprobar si un encuadre funciona antes de gastar en un modelo serio, no para entregar nada al usuario final.',
  5, 5,
  array['720p']::text[], array['16:9', '9:16', '1:1']::text[],
  true, true, false, false,
  0.10, null, 4,
  'free', 'active', null, 62
)
on conflict (id) do update set
  family = excluded.family, provider = excluded.provider,
  modality = excluded.modality, label = excluded.label,
  description_llm = excluded.description_llm,
  min_duration_s = excluded.min_duration_s, max_duration_s = excluded.max_duration_s,
  resolutions = excluded.resolutions, aspects = excluded.aspects,
  supports_i2v = excluded.supports_i2v,
  supports_last_frame = excluded.supports_last_frame,
  supports_char_ref = excluded.supports_char_ref,
  supports_audio = excluded.supports_audio,
  cost_per_second = excluded.cost_per_second,
  cost_per_image = excluded.cost_per_image,
  credits_per_unit = excluded.credits_per_unit,
  min_plan = excluded.min_plan, status = excluded.status,
  sunset_at = excluded.sunset_at, sort = excluded.sort,
  updated_at = now();

-- Higgsfield DoP Turbo · $0.083/segundo · [S] fuente secundaria, re-verificar
-- NOTA: Precio de revendedor (Pixazo, $0.416 por clip de 5 s). No oficial.
insert into public.gen_models (
  id, family, provider, modality, label, description_llm,
  min_duration_s, max_duration_s, resolutions, aspects,
  supports_i2v, supports_last_frame, supports_char_ref, supports_audio,
  cost_per_second, cost_per_image, credits_per_unit,
  min_plan, status, sunset_at, sort
) values (
  'higgsfield-dop-turbo', 'Higgsfield', 'higgsfield', 'video',
  'Higgsfield DoP Turbo',
  'El unico modelo del catalogo entrenado sobre movimiento de camara, no sobre descripciones de movimiento. Si el usuario pide un movimiento con nombre propio (dolly zoom, orbita, grua), este lo ejecuta de verdad mientras que los demas lo aproximan. Necesita una imagen de partida: genera primero el fotograma con Soul o Flux y animalo aqui.',
  5, 5,
  array['720p', '1080p']::text[], array['16:9', '9:16', '1:1']::text[],
  true, true, true, false,
  0.083, null, 4,
  'free', 'active', null, 5
)
on conflict (id) do update set
  family = excluded.family, provider = excluded.provider,
  modality = excluded.modality, label = excluded.label,
  description_llm = excluded.description_llm,
  min_duration_s = excluded.min_duration_s, max_duration_s = excluded.max_duration_s,
  resolutions = excluded.resolutions, aspects = excluded.aspects,
  supports_i2v = excluded.supports_i2v,
  supports_last_frame = excluded.supports_last_frame,
  supports_char_ref = excluded.supports_char_ref,
  supports_audio = excluded.supports_audio,
  cost_per_second = excluded.cost_per_second,
  cost_per_image = excluded.cost_per_image,
  credits_per_unit = excluded.credits_per_unit,
  min_plan = excluded.min_plan, status = excluded.status,
  sunset_at = excluded.sunset_at, sort = excluded.sort,
  updated_at = now();

-- Higgsfield DoP Lite · $0.027/segundo · [S] fuente secundaria, re-verificar
-- NOTA: Precio de revendedor (Pixazo, $0.135 por clip de 5 s). No oficial.
insert into public.gen_models (
  id, family, provider, modality, label, description_llm,
  min_duration_s, max_duration_s, resolutions, aspects,
  supports_i2v, supports_last_frame, supports_char_ref, supports_audio,
  cost_per_second, cost_per_image, credits_per_unit,
  min_plan, status, sunset_at, sort
) values (
  'higgsfield-dop-lite', 'Higgsfield', 'higgsfield', 'video',
  'Higgsfield DoP Lite',
  'DoP a un tercio del coste. Ejecuta los mismos presets de camara con menos detalle de imagen, lo que lo hace ideal para probar que el movimiento elegido es el correcto antes de pagar el bueno.',
  5, 5,
  array['720p']::text[], array['16:9', '9:16', '1:1']::text[],
  true, true, false, false,
  0.027, null, 2,
  'free', 'active', null, 6
)
on conflict (id) do update set
  family = excluded.family, provider = excluded.provider,
  modality = excluded.modality, label = excluded.label,
  description_llm = excluded.description_llm,
  min_duration_s = excluded.min_duration_s, max_duration_s = excluded.max_duration_s,
  resolutions = excluded.resolutions, aspects = excluded.aspects,
  supports_i2v = excluded.supports_i2v,
  supports_last_frame = excluded.supports_last_frame,
  supports_char_ref = excluded.supports_char_ref,
  supports_audio = excluded.supports_audio,
  cost_per_second = excluded.cost_per_second,
  cost_per_image = excluded.cost_per_image,
  credits_per_unit = excluded.credits_per_unit,
  min_plan = excluded.min_plan, status = excluded.status,
  sunset_at = excluded.sunset_at, sort = excluded.sort,
  updated_at = now();

-- Higgsfield DoP Preview · $0.115/segundo · [S] fuente secundaria, re-verificar
-- NOTA: Precio de revendedor (Pixazo, $0.573 por clip de 5 s). No oficial.
insert into public.gen_models (
  id, family, provider, modality, label, description_llm,
  min_duration_s, max_duration_s, resolutions, aspects,
  supports_i2v, supports_last_frame, supports_char_ref, supports_audio,
  cost_per_second, cost_per_image, credits_per_unit,
  min_plan, status, sunset_at, sort
) values (
  'higgsfield-dop-preview', 'Higgsfield', 'higgsfield', 'video',
  'Higgsfield DoP Preview',
  'La variante de maxima fidelidad de DoP. Se justifica solo en el plano donde el movimiento de camara es el protagonista y va a verse grande.',
  5, 5,
  array['1080p']::text[], array['16:9', '9:16', '1:1']::text[],
  true, true, true, false,
  0.115, null, 5,
  'pro', 'active', null, 7
)
on conflict (id) do update set
  family = excluded.family, provider = excluded.provider,
  modality = excluded.modality, label = excluded.label,
  description_llm = excluded.description_llm,
  min_duration_s = excluded.min_duration_s, max_duration_s = excluded.max_duration_s,
  resolutions = excluded.resolutions, aspects = excluded.aspects,
  supports_i2v = excluded.supports_i2v,
  supports_last_frame = excluded.supports_last_frame,
  supports_char_ref = excluded.supports_char_ref,
  supports_audio = excluded.supports_audio,
  cost_per_second = excluded.cost_per_second,
  cost_per_image = excluded.cost_per_image,
  credits_per_unit = excluded.credits_per_unit,
  min_plan = excluded.min_plan, status = excluded.status,
  sunset_at = excluded.sunset_at, sort = excluded.sort,
  updated_at = now();

-- Higgsfield Soul · $0.17/imagen · [S] fuente secundaria, re-verificar
-- NOTA: Segmind cotiza $0.120-0.230/gen. Se toma el punto medio.
insert into public.gen_models (
  id, family, provider, modality, label, description_llm,
  min_duration_s, max_duration_s, resolutions, aspects,
  supports_i2v, supports_last_frame, supports_char_ref, supports_audio,
  cost_per_second, cost_per_image, credits_per_unit,
  min_plan, status, sunset_at, sort
) values (
  'higgsfield-soul', 'Higgsfield', 'higgsfield', 'image',
  'Higgsfield Soul',
  'Fotorrealismo con textura de piel creible, y la puerta de entrada a Soul ID: si el proyecto tiene un personaje entrenado, este es el unico modelo que reproduce su cara exacta en cualquier pose o luz. Para storyboards de personaje recurrente, empieza siempre aqui.',
  null, null,
  array['1536x1536', '1536x2048', '2048x1536']::text[], array['16:9', '9:16', '1:1']::text[],
  false, false, true, false,
  0.17, 0.17, 7,
  'free', 'active', null, 8
)
on conflict (id) do update set
  family = excluded.family, provider = excluded.provider,
  modality = excluded.modality, label = excluded.label,
  description_llm = excluded.description_llm,
  min_duration_s = excluded.min_duration_s, max_duration_s = excluded.max_duration_s,
  resolutions = excluded.resolutions, aspects = excluded.aspects,
  supports_i2v = excluded.supports_i2v,
  supports_last_frame = excluded.supports_last_frame,
  supports_char_ref = excluded.supports_char_ref,
  supports_audio = excluded.supports_audio,
  cost_per_second = excluded.cost_per_second,
  cost_per_image = excluded.cost_per_image,
  credits_per_unit = excluded.credits_per_unit,
  min_plan = excluded.min_plan, status = excluded.status,
  sunset_at = excluded.sunset_at, sort = excluded.sort,
  updated_at = now();

-- FLUX.2 [pro] · $0.03/imagen · [V] verificado en fuente primaria
-- NOTA: Tarifa por megapixel de salida; cost_per_second se siembra como $/MP.
insert into public.gen_models (
  id, family, provider, modality, label, description_llm,
  min_duration_s, max_duration_s, resolutions, aspects,
  supports_i2v, supports_last_frame, supports_char_ref, supports_audio,
  cost_per_second, cost_per_image, credits_per_unit,
  min_plan, status, sunset_at, sort
) values (
  'flux-2-pro', 'FLUX', 'bfl', 'image',
  'FLUX.2 [pro]',
  'Admite hasta ocho referencias en una sola llamada y sabe tomar el personaje de una imagen y la pose de otra. Es la forma barata de mantener el mismo personaje y la misma localizacion a lo largo de un storyboard sin entrenar nada. Es el modelo de imagen por defecto salvo que haga falta Soul ID.',
  null, null,
  array['720p', '1080p']::text[], array['16:9', '9:16', '1:1']::text[],
  false, false, true, false,
  0.03, 0.03, 2,
  'free', 'active', null, 70
)
on conflict (id) do update set
  family = excluded.family, provider = excluded.provider,
  modality = excluded.modality, label = excluded.label,
  description_llm = excluded.description_llm,
  min_duration_s = excluded.min_duration_s, max_duration_s = excluded.max_duration_s,
  resolutions = excluded.resolutions, aspects = excluded.aspects,
  supports_i2v = excluded.supports_i2v,
  supports_last_frame = excluded.supports_last_frame,
  supports_char_ref = excluded.supports_char_ref,
  supports_audio = excluded.supports_audio,
  cost_per_second = excluded.cost_per_second,
  cost_per_image = excluded.cost_per_image,
  credits_per_unit = excluded.credits_per_unit,
  min_plan = excluded.min_plan, status = excluded.status,
  sunset_at = excluded.sunset_at, sort = excluded.sort,
  updated_at = now();

-- FLUX.2 [max] · $0.07/imagen · [V] verificado en fuente primaria
-- NOTA: Primer megapixel $0.07, adicionales $0.03. Se siembra el primero.
insert into public.gen_models (
  id, family, provider, modality, label, description_llm,
  min_duration_s, max_duration_s, resolutions, aspects,
  supports_i2v, supports_last_frame, supports_char_ref, supports_audio,
  cost_per_second, cost_per_image, credits_per_unit,
  min_plan, status, sunset_at, sort
) values (
  'flux-2-max', 'FLUX', 'bfl', 'image',
  'FLUX.2 [max]',
  'FLUX.2 con mas presupuesto de calculo por imagen: mejor en texto dentro de la imagen y en detalle de material. Vale la pena en la portada o en el fotograma que se va a animar despues, no en las vinetas intermedias.',
  null, null,
  array['720p', '1080p']::text[], array['16:9', '9:16', '1:1']::text[],
  false, false, true, false,
  0.07, 0.07, 3,
  'pro', 'active', null, 71
)
on conflict (id) do update set
  family = excluded.family, provider = excluded.provider,
  modality = excluded.modality, label = excluded.label,
  description_llm = excluded.description_llm,
  min_duration_s = excluded.min_duration_s, max_duration_s = excluded.max_duration_s,
  resolutions = excluded.resolutions, aspects = excluded.aspects,
  supports_i2v = excluded.supports_i2v,
  supports_last_frame = excluded.supports_last_frame,
  supports_char_ref = excluded.supports_char_ref,
  supports_audio = excluded.supports_audio,
  cost_per_second = excluded.cost_per_second,
  cost_per_image = excluded.cost_per_image,
  credits_per_unit = excluded.credits_per_unit,
  min_plan = excluded.min_plan, status = excluded.status,
  sunset_at = excluded.sunset_at, sort = excluded.sort,
  updated_at = now();

-- FLUX Kontext [pro] · $0.04/imagen · [V] verificado en fuente primaria
insert into public.gen_models (
  id, family, provider, modality, label, description_llm,
  min_duration_s, max_duration_s, resolutions, aspects,
  supports_i2v, supports_last_frame, supports_char_ref, supports_audio,
  cost_per_second, cost_per_image, credits_per_unit,
  min_plan, status, sunset_at, sort
) values (
  'flux-kontext-pro', 'FLUX', 'bfl', 'image',
  'FLUX Kontext [pro]',
  'Especialista en editar una imagen que ya existe conservando todo lo demas: cambiar la ropa de un personaje, quitar un objeto, corregir la luz. Cuando el usuario diga ''igual pero con X'', esto es lo que hay que usar en lugar de regenerar desde cero y perder la continuidad.',
  null, null,
  array['720p', '1080p']::text[], array['16:9', '9:16', '1:1']::text[],
  false, false, true, false,
  0.04, 0.04, 2,
  'free', 'active', null, 72
)
on conflict (id) do update set
  family = excluded.family, provider = excluded.provider,
  modality = excluded.modality, label = excluded.label,
  description_llm = excluded.description_llm,
  min_duration_s = excluded.min_duration_s, max_duration_s = excluded.max_duration_s,
  resolutions = excluded.resolutions, aspects = excluded.aspects,
  supports_i2v = excluded.supports_i2v,
  supports_last_frame = excluded.supports_last_frame,
  supports_char_ref = excluded.supports_char_ref,
  supports_audio = excluded.supports_audio,
  cost_per_second = excluded.cost_per_second,
  cost_per_image = excluded.cost_per_image,
  credits_per_unit = excluded.credits_per_unit,
  min_plan = excluded.min_plan, status = excluded.status,
  sunset_at = excluded.sunset_at, sort = excluded.sort,
  updated_at = now();

-- Runway Gen-4 Turbo · $0.05/segundo · [V] verificado en fuente primaria
-- NOTA: Sin adaptador: no hay runway.py. Sembrado solo para poder informar del apagado.
insert into public.gen_models (
  id, family, provider, modality, label, description_llm,
  min_duration_s, max_duration_s, resolutions, aspects,
  supports_i2v, supports_last_frame, supports_char_ref, supports_audio,
  cost_per_second, cost_per_image, credits_per_unit,
  min_plan, status, sunset_at, sort
) values (
  'runway-gen-4-turbo', 'Runway', 'runway', 'video',
  'Runway Gen-4 Turbo',
  'RETIRADO POR EL PROVEEDOR el 30 de julio de 2026. No lo propongas. Si el usuario lo pide por nombre, explicale que Runway lo apago y ofrecele kling-3.0-turbo, que cubre el mismo caso de uso.',
  5, 10,
  array['720p', '1080p']::text[], array['16:9', '9:16', '1:1']::text[],
  true, false, true, false,
  0.05, null, 2,
  'free', 'deprecated', '2026-07-30'::timestamptz, 90
)
on conflict (id) do update set
  family = excluded.family, provider = excluded.provider,
  modality = excluded.modality, label = excluded.label,
  description_llm = excluded.description_llm,
  min_duration_s = excluded.min_duration_s, max_duration_s = excluded.max_duration_s,
  resolutions = excluded.resolutions, aspects = excluded.aspects,
  supports_i2v = excluded.supports_i2v,
  supports_last_frame = excluded.supports_last_frame,
  supports_char_ref = excluded.supports_char_ref,
  supports_audio = excluded.supports_audio,
  cost_per_second = excluded.cost_per_second,
  cost_per_image = excluded.cost_per_image,
  credits_per_unit = excluded.credits_per_unit,
  min_plan = excluded.min_plan, status = excluded.status,
  sunset_at = excluded.sunset_at, sort = excluded.sort,
  updated_at = now();

-- Runway Gen-4 · $0.12/segundo · [V] verificado en fuente primaria
-- NOTA: Sin adaptador: no hay runway.py. Sembrado solo para poder informar del apagado.
insert into public.gen_models (
  id, family, provider, modality, label, description_llm,
  min_duration_s, max_duration_s, resolutions, aspects,
  supports_i2v, supports_last_frame, supports_char_ref, supports_audio,
  cost_per_second, cost_per_image, credits_per_unit,
  min_plan, status, sunset_at, sort
) values (
  'runway-gen-4', 'Runway', 'runway', 'video',
  'Runway Gen-4',
  'RETIRADO POR EL PROVEEDOR el 30 de julio de 2026. No lo propongas. Alternativa equivalente en calidad: kling-3.0 o veo-3.1-generate-preview.',
  5, 10,
  array['720p', '1080p']::text[], array['16:9', '9:16', '1:1']::text[],
  true, false, true, false,
  0.12, null, 5,
  'pro', 'deprecated', '2026-07-30'::timestamptz, 91
)
on conflict (id) do update set
  family = excluded.family, provider = excluded.provider,
  modality = excluded.modality, label = excluded.label,
  description_llm = excluded.description_llm,
  min_duration_s = excluded.min_duration_s, max_duration_s = excluded.max_duration_s,
  resolutions = excluded.resolutions, aspects = excluded.aspects,
  supports_i2v = excluded.supports_i2v,
  supports_last_frame = excluded.supports_last_frame,
  supports_char_ref = excluded.supports_char_ref,
  supports_audio = excluded.supports_audio,
  cost_per_second = excluded.cost_per_second,
  cost_per_image = excluded.cost_per_image,
  credits_per_unit = excluded.credits_per_unit,
  min_plan = excluded.min_plan, status = excluded.status,
  sunset_at = excluded.sunset_at, sort = excluded.sort,
  updated_at = now();

-- ------------------------------------------------------------------
-- camera_motions
--
-- provider_ref queda vacío a propósito: Higgsfield identifica cada preset por
-- UUID y sirve el catálogo dinámicamente vía getMotions(). Inventar UUIDs aquí
-- sería sembrar datos falsos; el adaptador los resuelve por nombre en runtime.
-- ------------------------------------------------------------------

insert into public.camera_motions (id, label, description_llm, provider_ref, supports_strength, category, sort)
values ('dolly-zoom', 'Dolly Zoom',
  'El fondo se acerca mientras el sujeto se queda igual. Sirve para el momento exacto en que un personaje entiende algo que le cambia todo. Es un efecto que se nota: usado dos veces en la misma pieza, pierde su significado.',
  '{}'::jsonb, true, 'push', 10)
on conflict (id) do update set
  label = excluded.label, description_llm = excluded.description_llm,
  supports_strength = excluded.supports_strength,
  category = excluded.category, sort = excluded.sort;

insert into public.camera_motions (id, label, description_llm, provider_ref, supports_strength, category, sort)
values ('orbit-360', '360 Orbit',
  'La camara rodea al sujeto por completo. Presenta algo como si fuera un objeto de deseo: producto, vehiculo, personaje en su momento de poder. Necesita un sujeto claro y centrado, o se convierte en un mareo.',
  '{}'::jsonb, true, 'orbit', 11)
on conflict (id) do update set
  label = excluded.label, description_llm = excluded.description_llm,
  supports_strength = excluded.supports_strength,
  category = excluded.category, sort = excluded.sort;

insert into public.camera_motions (id, label, description_llm, provider_ref, supports_strength, category, sort)
values ('truck-left', 'Truck Left',
  'Desplazamiento lateral a la izquierda manteniendo el eje. Es el movimiento de acompanar a alguien que camina, o de revelar lo que habia fuera de cuadro sin cortar.',
  '{}'::jsonb, true, 'push', 12)
on conflict (id) do update set
  label = excluded.label, description_llm = excluded.description_llm,
  supports_strength = excluded.supports_strength,
  category = excluded.category, sort = excluded.sort;

insert into public.camera_motions (id, label, description_llm, provider_ref, supports_strength, category, sort)
values ('truck-right', 'Truck Right',
  'Igual que Truck Left en direccion contraria. Encadenar dos planos con trucks opuestos crea sensacion de desorden; hacerlo a proposito funciona, hacerlo por descuido se nota.',
  '{}'::jsonb, true, 'push', 13)
on conflict (id) do update set
  label = excluded.label, description_llm = excluded.description_llm,
  supports_strength = excluded.supports_strength,
  category = excluded.category, sort = excluded.sort;

insert into public.camera_motions (id, label, description_llm, provider_ref, supports_strength, category, sort)
values ('push-to-glass', 'Push to Glass',
  'Avance hacia una superficie transparente hasta atravesarla. Es la transicion de exterior a interior sin corte, y funciona muy bien para entrar en la intimidad de una escena desde fuera.',
  '{}'::jsonb, true, 'push', 14)
on conflict (id) do update set
  label = excluded.label, description_llm = excluded.description_llm,
  supports_strength = excluded.supports_strength,
  category = excluded.category, sort = excluded.sort;

insert into public.camera_motions (id, label, description_llm, provider_ref, supports_strength, category, sort)
values ('head-tracking', 'Head Tracking',
  'La camara sigue la cabeza del sujeto y la mantiene fija en cuadro pase lo que pase. Ata al espectador al personaje: usalo cuando lo que importa es lo que el siente, no donde esta.',
  '{}'::jsonb, true, 'handheld', 15)
on conflict (id) do update set
  label = excluded.label, description_llm = excluded.description_llm,
  supports_strength = excluded.supports_strength,
  category = excluded.category, sort = excluded.sort;

insert into public.camera_motions (id, label, description_llm, provider_ref, supports_strength, category, sort)
values ('crane-up', 'Crane Up',
  'Ascenso que abre el plano y deja al sujeto pequeno. Es el gesto de cierre por excelencia: separa al espectador de la escena. Reservalo para el final de una secuencia.',
  '{}'::jsonb, true, 'crane', 16)
on conflict (id) do update set
  label = excluded.label, description_llm = excluded.description_llm,
  supports_strength = excluded.supports_strength,
  category = excluded.category, sort = excluded.sort;

insert into public.camera_motions (id, label, description_llm, provider_ref, supports_strength, category, sort)
values ('crane-down', 'Crane Down',
  'Descenso desde una vista amplia hasta el sujeto. Es lo contrario de Crane Up y por tanto el gesto de apertura: situa un mundo y luego elige a quien vamos a seguir dentro de el.',
  '{}'::jsonb, true, 'crane', 17)
on conflict (id) do update set
  label = excluded.label, description_llm = excluded.description_llm,
  supports_strength = excluded.supports_strength,
  category = excluded.category, sort = excluded.sort;

insert into public.camera_motions (id, label, description_llm, provider_ref, supports_strength, category, sort)
values ('pan-left', 'Pan Left',
  'Giro sobre el eje hacia la izquierda, sin desplazar la camara. Recorre un espacio desde un punto fijo. Mas neutro y menos dramatico que un truck.',
  '{}'::jsonb, true, 'push', 18)
on conflict (id) do update set
  label = excluded.label, description_llm = excluded.description_llm,
  supports_strength = excluded.supports_strength,
  category = excluded.category, sort = excluded.sort;

insert into public.camera_motions (id, label, description_llm, provider_ref, supports_strength, category, sort)
values ('pan-right', 'Pan Right',
  'Giro sobre el eje hacia la derecha, sin desplazar la camara. Recorre un espacio desde un punto fijo, mas neutro que un truck. En occidental, acompanar el sentido de lectura hace que el movimiento pase desapercibido; ir contra el llama la atencion.',
  '{}'::jsonb, true, 'push', 19)
on conflict (id) do update set
  label = excluded.label, description_llm = excluded.description_llm,
  supports_strength = excluded.supports_strength,
  category = excluded.category, sort = excluded.sort;

insert into public.camera_motions (id, label, description_llm, provider_ref, supports_strength, category, sort)
values ('tilt-up', 'Tilt Up',
  'Inclinacion hacia arriba. Engrandece lo que revela: arquitectura, una figura de autoridad, una amenaza. El sujeto queda por encima del espectador.',
  '{}'::jsonb, true, 'crane', 20)
on conflict (id) do update set
  label = excluded.label, description_llm = excluded.description_llm,
  supports_strength = excluded.supports_strength,
  category = excluded.category, sort = excluded.sort;

insert into public.camera_motions (id, label, description_llm, provider_ref, supports_strength, category, sort)
values ('tilt-down', 'Tilt Down',
  'Inclinacion hacia abajo. Empequenece o expone lo que revela; es la mirada que juzga o que descubre algo caido.',
  '{}'::jsonb, true, 'crane', 21)
on conflict (id) do update set
  label = excluded.label, description_llm = excluded.description_llm,
  supports_strength = excluded.supports_strength,
  category = excluded.category, sort = excluded.sort;

insert into public.camera_motions (id, label, description_llm, provider_ref, supports_strength, category, sort)
values ('zoom-in', 'Zoom In',
  'Acercamiento optico sin mover la camara. Se lee como una intensificacion algo artificial, casi televisiva, distinta del avance fisico de un dolly. Elige entre uno y otro segun quieras naturalidad o enfasis declarado.',
  '{}'::jsonb, true, 'push', 22)
on conflict (id) do update set
  label = excluded.label, description_llm = excluded.description_llm,
  supports_strength = excluded.supports_strength,
  category = excluded.category, sort = excluded.sort;

insert into public.camera_motions (id, label, description_llm, provider_ref, supports_strength, category, sort)
values ('handheld-follow', 'Handheld Follow',
  'Seguimiento a mano, con temblor. Aporta urgencia y presencia documental. Es lo contrario de un plano compuesto: usalo cuando la escena deba parecer captada, no dirigida.',
  '{}'::jsonb, true, 'handheld', 23)
on conflict (id) do update set
  label = excluded.label, description_llm = excluded.description_llm,
  supports_strength = excluded.supports_strength,
  category = excluded.category, sort = excluded.sort;

insert into public.camera_motions (id, label, description_llm, provider_ref, supports_strength, category, sort)
values ('static-lockoff', 'Static Lock-off',
  'Camara completamente inmovil. No es la ausencia de decision, es una decision: obliga al espectador a mirar la composicion y deja que el movimiento lo ponga la accion. En una secuencia de planos moviles, un estatico es lo que da respiro.',
  '{}'::jsonb, false, 'handheld', 24)
on conflict (id) do update set
  label = excluded.label, description_llm = excluded.description_llm,
  supports_strength = excluded.supports_strength,
  category = excluded.category, sort = excluded.sort;

insert into public.camera_motions (id, label, description_llm, provider_ref, supports_strength, category, sort)
values ('anamorphic-flares', 'Anamorphic Flares',
  'Destellos horizontales azulados de optica anamorfica. No es un movimiento, es una firma de formato: dice ''esto es cine'' antes de que pase nada. Combina mal con un look documental.',
  '{}'::jsonb, true, 'fx', 30)
on conflict (id) do update set
  label = excluded.label, description_llm = excluded.description_llm,
  supports_strength = excluded.supports_strength,
  category = excluded.category, sort = excluded.sort;

insert into public.camera_motions (id, label, description_llm, provider_ref, supports_strength, category, sort)
values ('film-stock', 'Film Stock',
  'Grano, halacion y respuesta de color de pelicula fotoquimica. Ablanda el aspecto digital y unifica planos generados por modelos distintos, que es su uso mas util: tapa las costuras de una secuencia hecha a trozos.',
  '{}'::jsonb, true, 'fx', 31)
on conflict (id) do update set
  label = excluded.label, description_llm = excluded.description_llm,
  supports_strength = excluded.supports_strength,
  category = excluded.category, sort = excluded.sort;

insert into public.camera_motions (id, label, description_llm, provider_ref, supports_strength, category, sort)
values ('depth-of-field', 'Depth of Field Control',
  'Desenfoque selectivo del fondo. Dirige la mirada y separa al sujeto del entorno. En generativo tiene un beneficio adicional: esconde los fondos, que es donde los modelos cometen la mayoria de sus errores.',
  '{}'::jsonb, true, 'fx', 32)
on conflict (id) do update set
  label = excluded.label, description_llm = excluded.description_llm,
  supports_strength = excluded.supports_strength,
  category = excluded.category, sort = excluded.sort;

-- ------------------------------------------------------------------
-- visual_styles
-- ------------------------------------------------------------------

insert into public.visual_styles (id, dimension, label, description_llm, prompt_fragment, sort)
values ('teal-orange', 'palette', 'Teal & Orange',
  'Pieles calidas contra sombras frias. Es el color del cine comercial contemporaneo: legible, vendible y completamente reconocible. Si el usuario no pide nada concreto y la pieza es publicitaria, es la apuesta segura.',
  'teal and orange color grade, warm skin tones against cool shadows', 10)
on conflict (id) do update set
  dimension = excluded.dimension, label = excluded.label,
  description_llm = excluded.description_llm,
  prompt_fragment = excluded.prompt_fragment, sort = excluded.sort;

insert into public.visual_styles (id, dimension, label, description_llm, prompt_fragment, sort)
values ('desaturated-noir', 'palette', 'Desaturado Noir',
  'Color casi ausente, negros densos. Elimina la informacion cromatica para que el peso caiga en la forma y el contraste. Adecuado para drama y tension; mata cualquier plano que dependa de un producto de color.',
  'desaturated palette, deep crushed blacks, near-monochrome', 11)
on conflict (id) do update set
  dimension = excluded.dimension, label = excluded.label,
  description_llm = excluded.description_llm,
  prompt_fragment = excluded.prompt_fragment, sort = excluded.sort;

insert into public.visual_styles (id, dimension, label, description_llm, prompt_fragment, sort)
values ('pastel-soft', 'palette', 'Pastel Suave',
  'Tonos lavados y contraste bajo. Quita dramatismo y suma cercania. Funciona en comedia, en producto de estilo de vida y en recuerdo o ensonacion.',
  'soft pastel palette, low contrast, milky highlights', 12)
on conflict (id) do update set
  dimension = excluded.dimension, label = excluded.label,
  description_llm = excluded.description_llm,
  prompt_fragment = excluded.prompt_fragment, sort = excluded.sort;

insert into public.visual_styles (id, dimension, label, description_llm, prompt_fragment, sort)
values ('high-saturation-pop', 'palette', 'Pop Saturado',
  'Color al maximo. Retiene la atencion en scroll vertical, donde la pieza compite con el pulgar del espectador. Reservalo para vertical y formatos cortos; en pantalla grande cansa en segundos.',
  'hyper-saturated vivid colors, punchy contrast', 13)
on conflict (id) do update set
  dimension = excluded.dimension, label = excluded.label,
  description_llm = excluded.description_llm,
  prompt_fragment = excluded.prompt_fragment, sort = excluded.sort;

insert into public.visual_styles (id, dimension, label, description_llm, prompt_fragment, sort)
values ('golden-hour', 'lighting', 'Golden Hour',
  'Sol bajo, contraluz calido y sombras largas. Favorece cualquier rostro y cualquier paisaje, y por eso mismo es dificil de hacer mal. Su limite es narrativo: no puedes ambientar toda una pieza a la misma hora del dia.',
  'golden hour backlight, long shadows, warm rim light', 20)
on conflict (id) do update set
  dimension = excluded.dimension, label = excluded.label,
  description_llm = excluded.description_llm,
  prompt_fragment = excluded.prompt_fragment, sort = excluded.sort;

insert into public.visual_styles (id, dimension, label, description_llm, prompt_fragment, sort)
values ('hard-key-noir', 'lighting', 'Clave Dura',
  'Una fuente dura y sombras sin relleno. Esculpe y esconde a partes iguales. Es la luz del interrogatorio y del retrato dramatico; en producto crea reflejos dificiles de controlar.',
  'hard single key light, deep unfilled shadows, chiaroscuro', 21)
on conflict (id) do update set
  dimension = excluded.dimension, label = excluded.label,
  description_llm = excluded.description_llm,
  prompt_fragment = excluded.prompt_fragment, sort = excluded.sort;

insert into public.visual_styles (id, dimension, label, description_llm, prompt_fragment, sort)
values ('soft-overcast', 'lighting', 'Difusa de Nublado',
  'Luz envolvente y sin sombra marcada. Es la mas neutra y la que mejor empalma entre planos generados por separado, porque no impone direccion de luz que luego haya que respetar.',
  'soft diffused overcast light, no harsh shadows, even exposure', 22)
on conflict (id) do update set
  dimension = excluded.dimension, label = excluded.label,
  description_llm = excluded.description_llm,
  prompt_fragment = excluded.prompt_fragment, sort = excluded.sort;

insert into public.visual_styles (id, dimension, label, description_llm, prompt_fragment, sort)
values ('neon-practical', 'lighting', 'Neon Practico',
  'Fuentes de color dentro del propio plano: rotulos, pantallas, tubos. Da textura urbana y nocturna y justifica colores agresivos sin que parezcan postproduccion.',
  'neon practical lights in frame, colored spill, night interior', 23)
on conflict (id) do update set
  dimension = excluded.dimension, label = excluded.label,
  description_llm = excluded.description_llm,
  prompt_fragment = excluded.prompt_fragment, sort = excluded.sort;

insert into public.visual_styles (id, dimension, label, description_llm, prompt_fragment, sort)
values ('kodak-2383', 'film_stock', 'Kodak 2383',
  'Emulacion de copia de proyeccion: contraste alto y color de sala de cine. Es el acabado que hace que un plano parezca proyectado y no reproducido.',
  'Kodak 2383 print film emulation, cinematic contrast curve', 30)
on conflict (id) do update set
  dimension = excluded.dimension, label = excluded.label,
  description_llm = excluded.description_llm,
  prompt_fragment = excluded.prompt_fragment, sort = excluded.sort;

insert into public.visual_styles (id, dimension, label, description_llm, prompt_fragment, sort)
values ('16mm-grain', 'film_stock', '16mm Grano',
  'Grano visible y algo de inestabilidad. Lee como memoria, archivo o documental de epoca. Ademas disimula los artefactos tipicos del generativo, que es una ventaja practica ademas de estetica.',
  '16mm film grain, slight gate weave, halation', 31)
on conflict (id) do update set
  dimension = excluded.dimension, label = excluded.label,
  description_llm = excluded.description_llm,
  prompt_fragment = excluded.prompt_fragment, sort = excluded.sort;

insert into public.visual_styles (id, dimension, label, description_llm, prompt_fragment, sort)
values ('digital-clean', 'film_stock', 'Digital Limpio',
  'Sin grano ni textura anadida. Es lo que quieres cuando el sujeto es tecnologia, producto o interfaz, y cualquier suciedad se leeria como defecto de fabricacion.',
  'clean digital capture, no grain, high clarity', 32)
on conflict (id) do update set
  dimension = excluded.dimension, label = excluded.label,
  description_llm = excluded.description_llm,
  prompt_fragment = excluded.prompt_fragment, sort = excluded.sort;

insert into public.visual_styles (id, dimension, label, description_llm, prompt_fragment, sort)
values ('anamorphic-40mm', 'lens', 'Anamorfica 40mm',
  'Campo amplio con compresion horizontal y bokeh ovalado. Da escala sin tener que alejar la camara, asi que sirve para planos de conjunto que aun deben sentirse cercanos.',
  '40mm anamorphic lens, oval bokeh, horizontal flares', 40)
on conflict (id) do update set
  dimension = excluded.dimension, label = excluded.label,
  description_llm = excluded.description_llm,
  prompt_fragment = excluded.prompt_fragment, sort = excluded.sort;

insert into public.visual_styles (id, dimension, label, description_llm, prompt_fragment, sort)
values ('portrait-85mm', 'lens', 'Retrato 85mm',
  'Compresion de rasgos y fondo desenfocado. Es el plano de rostro por defecto: favorece la cara y aisla al personaje de un fondo que en generativo suele ser el punto debil.',
  '85mm portrait lens, shallow depth of field, compressed features', 41)
on conflict (id) do update set
  dimension = excluded.dimension, label = excluded.label,
  description_llm = excluded.description_llm,
  prompt_fragment = excluded.prompt_fragment, sort = excluded.sort;

insert into public.visual_styles (id, dimension, label, description_llm, prompt_fragment, sort)
values ('wide-24mm', 'lens', 'Gran Angular 24mm',
  'Perspectiva exagerada y mucho contexto. Mete al espectador dentro del espacio, pero deforma los rostros cercanos: no lo uses en un primer plano salvo que la distorsion sea el efecto buscado.',
  '24mm wide angle, exaggerated perspective, deep focus', 42)
on conflict (id) do update set
  dimension = excluded.dimension, label = excluded.label,
  description_llm = excluded.description_llm,
  prompt_fragment = excluded.prompt_fragment, sort = excluded.sort;

insert into public.visual_styles (id, dimension, label, description_llm, prompt_fragment, sort)
values ('macro-detail', 'lens', 'Macro',
  'Detalle extremo con profundidad de campo minima. Es el recurso de insercion que da textura a un montaje y descansa entre planos amplios. Muy barato de generar bien porque hay poco fondo que equivocar.',
  'extreme macro detail, razor-thin depth of field', 43)
on conflict (id) do update set
  dimension = excluded.dimension, label = excluded.label,
  description_llm = excluded.description_llm,
  prompt_fragment = excluded.prompt_fragment, sort = excluded.sort;

-- Los modelos que ya no estén en la semilla se retiran, no se borran:
-- generation_jobs.model_id los referencia y el historial debe seguir resolviendo.
update public.gen_models set status = 'retired', updated_at = now()
 where id <> all (array['veo-3.1-generate-preview', 'veo-3.1-lite-generate-preview', 'veo-3.1-fast-generate-preview', 'gemini-omni-flash', 'sora-2', 'sora-2-pro', 'gpt-image-2', 'gpt-image-1.5', 'gpt-image-1-mini', 'gpt-image-1', 'kling-3.0', 'kling-3.0-turbo', 'kling-3.0-motion-control', 'kling-2.5-turbo', 'kling-2.1-master', 'hailuo-2.3', 'hailuo-2.3-fast', 'hailuo-02', 'hailuo-02-fast', 'seedance-2.0', 'seedance-2.0-fast', 'seedance-2.0-mini', 'seedance-1.0-pro', 'wan-2.7', 'wan-2.5', 'wan-2.2-plus', 'higgsfield-dop-turbo', 'higgsfield-dop-lite', 'higgsfield-dop-preview', 'higgsfield-soul', 'flux-2-pro', 'flux-2-max', 'flux-kontext-pro', 'runway-gen-4-turbo', 'runway-gen-4']::text[]) and status <> 'retired';

commit;

