# BuscadorDeVuelos
Buscador de vuelos baratos con alertas por mail.

Busca ida y vuelta a Miami (MIA) desde Buenos Aires (EZE) y desde Santiago de
Chile (SCL), saliendo desde el 5 de febrero de 2027, con regreso a más tardar el
28 de febrero y una estadía de 10 a 13 días, para 3 adultos (el adolescente de
14 paga tarifa de adulto) + 1 menor. Si encuentra vuelos a USD 600 o menos por
persona, envía un mail. Los parámetros se cambian en `CONFIG` dentro de
`buscador.py`.

## Cómo aprovecha el plan gratis de SerpApi (250 búsquedas/mes)
Hay 100 combinaciones válidas de origen, salida y regreso. Cada día busca 7
(≈ 210 por mes, queda margen para pruebas a mano) en un orden mezclado, para que
cada día se prueben fechas y orígenes variados: una promo que baja muchas fechas
se detecta enseguida. Todas las combinaciones se revisan cada 15 días.

El "radar" de Google Travel Explore (1 búsqueda por origen para todo el mes)
está desactivado (`usar_radar`): no deja fijar el regreso máximo ni la estadía,
así que con estas fechas casi siempre elige viajes que vuelven en marzo.

## Qué hay que conectar
1. **SerpApi** (datos de Google Flights): crear cuenta en https://serpapi.com y copiar la API key.
2. **Gmail**: activar verificación en 2 pasos y crear una *contraseña de aplicación*
   en https://myaccount.google.com/apppasswords.
3. **Secrets del repo** (Settings → Secrets and variables → Actions):
   `SERPAPI_KEY`, `SMTP_USER`, `SMTP_PASSWORD`, `ALERT_TO`.

## Probar
```bash
python buscador.py --demo --no-mail        # sin credenciales, precios de ejemplo
python buscador.py --no-mail               # búsqueda real de hoy (7 búsquedas)
python buscador.py --todas --no-mail       # todas las fechas (100 búsquedas, usar muy poco)
python buscador.py --mail-prueba           # manda un mail aunque no haya ofertas
```
En GitHub: Actions → "Alerta de vuelos baratos" → *Run workflow* (se puede
tildar el mail de prueba). Cada corrida a mano gasta 7 búsquedas.
