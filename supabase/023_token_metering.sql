-- 023 · Medición de tokens del agente en el libro de créditos.
--
-- El razonamiento del agente cuesta tokens, y los tokens cuestan dinero. Hasta ahora
-- ese coste no se cobraba: solo los jobs de generación movían el libro, así que la parte
-- más cara de un proyecto salía gratis y se comía el margen de la suscripción.
--
-- Se añade la kind 'tokens' al CHECK del libro. Es un cobro directo (amount negativo, sin
-- job_id): los tokens ya se gastaron cuando el modelo respondió, no hay reserva que
-- confirmar ni reembolsar. Ver app/jobs/credits.py::debit_tokens y app/agent/metering.py.

begin;

alter table public.credit_ledger drop constraint if exists credit_ledger_kind_check;
alter table public.credit_ledger add constraint credit_ledger_kind_check
  check (kind in ('grant','reserve','charge','refund','expire','tokens'));

commit;
