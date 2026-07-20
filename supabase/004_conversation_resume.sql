-- Xframe · reanudación de conversaciones tras terminar los jobs
--
-- Contexto. La tool de generación encola y vuelve en segundos; el worker acaba
-- minutos después y publica `asset_ready` en el bus. Ese evento llega al frontend
-- por SSE pero no reentra en el grafo, así que "genera seis planos y móntalos"
-- eran dos mensajes del usuario: el agente nunca se enteraba de que los planos ya
-- estaban.
--
-- Estas tres columnas son las guardas de la reanudación automática. Sin ellas el
-- mecanismo es una bomba: cualquier generación suelta dispararía un turno de LLM, y
-- un turno que genera puede encadenar otro turno que genera.

alter table public.conversations
  add column if not exists awaiting_jobs   boolean     not null default false,
  add column if not exists auto_resumes    integer     not null default 0,
  add column if not exists last_resumed_at timestamptz;

comment on column public.conversations.awaiting_jobs is
  'La conversación encoló generaciones y espera a que aterricen. La ponen las tools '
  'de generación al encolar y se limpia al reanudar, dentro de la misma transacción '
  'que toma el cerrojo de la fila. Es la diferencia entre "el agente pidió esto y '
  'espera el resultado" y "alguien lanzó una generación por su cuenta": sin la marca, '
  'cualquier job que termine dispararía un turno que nadie ha pedido.';

comment on column public.conversations.auto_resumes is
  'Reanudaciones automáticas acumuladas. El tope vive en app/jobs/resume.py '
  '(MAX_AUTO_RESUMES). Se pone a cero cuando el usuario escribe de verdad, porque lo '
  'que hay que acotar es la cadena autónoma turno→genera→aterriza→turno, no el uso '
  'legítimo. Un bucle aquí gasta dinero en LLM y puede encadenar generaciones.';

comment on column public.conversations.last_resumed_at is
  'Marca de la última reanudación. Delimita qué jobs se le cuentan al agente en el '
  'evento sintético: los que terminaron después de este instante. Sin ella, cada '
  'reanudación le repetiría el historial entero de jobs de la conversación.';

-- Índice parcial: el worker pregunta "¿esta conversación espera algo?" una vez por
-- job terminado, y la inmensa mayoría de conversaciones no espera nada. El parcial
-- solo indexa las que sí, que son un puñado en cualquier instante.
create index if not exists conversations_awaiting_idx
  on public.conversations (id) where awaiting_jobs;

-- El worker busca los jobs no terminales de UNA conversación para decidir si queda
-- algo pendiente. `generation_jobs_pending_idx` es por (status, updated_at) y no
-- sirve para eso: obliga a recorrer todos los jobs vivos del sistema.
create index if not exists generation_jobs_conversation_idx
  on public.generation_jobs (conversation_id, status)
  where conversation_id is not null;
