# BuscadorDeVuelos
Buscador de vuelos baratos con alertas por mail.

Busca ida y vuelta a Miami (MIA) desde Buenos Aires (EZE) y desde Santiago de
Chile (SCL), salidas del 5 al 11 de
febrero de 2027, 14 días de estadía, 3 adultos (el adolescente de 14 paga
tarifa de adulto) + 1 menor. Si encuentra vuelos a USD 600 o menos por persona,
envía un mail. Los parámetros se cambian en `CONFIG` dentro de `buscador.py`.

## Qué hay que conectar
1. **SerpApi** (datos de Google Flights): crear cuenta en https://serpapi.com y copiar la API key.
   Plan gratis: 250 búsquedas/mes. Cada corrida usa 14 (7 fechas × 2 orígenes).
2. **Gmail**: activar verificación en 2 pasos y crear una *contraseña de aplicación*
   en https://myaccount.google.com/apppasswords.
3. **Secrets del repo** (Settings → Secrets and variables → Actions):
   `SERPAPI_KEY`, `SMTP_USER`, `SMTP_PASSWORD`, `ALERT_TO`.

## Probar
```bash
python buscador.py --demo --no-mail        # sin credenciales, precios de ejemplo
python buscador.py --no-mail               # búsqueda real (requiere SERPAPI_KEY)
python buscador.py --demo                  # prueba el envío del mail
```
En GitHub: Actions → "Alerta de vuelos baratos" → *Run workflow*.
Después corre solo día por medio (≈ 210 búsquedas/mes, entra en el plan gratis).
Con un plan pago se puede pasar el cron a todos los días (`17 11 * * *`).
