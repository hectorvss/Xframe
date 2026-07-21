# Edge Functions de Xframe

- `resolve-asset`: entrega una URL firmada después de verificar que el usuario es propietario del proyecto.
- `extract-url`: importa una URL HTTP(S) como fuente de conocimiento, con límite de tamaño, timeout y sin seguir redirecciones.

Despliegue:

```sh
supabase functions deploy resolve-asset
supabase functions deploy extract-url
```

Ambas funciones requieren las variables estándar de Supabase (`SUPABASE_URL`,
`SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY`). El servidor MCP se despliega
en `backend/` y no almacena secretos de proveedor en Supabase Edge Functions.
