# BuscadorDeVuelos
Buscador de vuelos baratos con alertas por mail.

Busca ida y vuelta a Miami (MIA) desde Buenos Aires (EZE) y desde Santiago de
Chile (SCL), con salida entre el 5 y el 15 de febrero de 2027 y unos 14 días de
estadía, para 3 adultos (el adolescente de 14 paga tarifa de adulto) + 1 menor.
Si encuentra vuelos a USD 600 o menos por persona, envía un mail. Los parámetros
se cambian en `CONFIG` dentro de `buscador.py`.

## Cómo aprovecha el plan gratis de SerpApi (250 búsquedas/mes)
Cada día hace 7 búsquedas (≈ 210 por mes, queda margen para pruebas a mano):

- **Radar del mes** (2 búsquedas, una por origen): Google Travel Explore devuelve
  el viaje de ~2 semanas más barato de todo febrero, sin fijar fechas. Se
  aceptan viajes que salgan entre el 5 y el 15 y duren 14 ± 2 días.
- **Fechas exactas** (5 búsquedas): Google Flights con salida y regreso fijos
  (14 días). Rota día a día entre las 22 combinaciones origen/fecha: todas se
  revisan cada 5 días.

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
python buscador.py --todas --no-mail       # todas las fechas (24 búsquedas, usar poco)
python buscador.py --mail-prueba           # manda un mail aunque no haya ofertas
```
En GitHub: Actions → "Alerta de vuelos baratos" → *Run workflow* (se puede
tildar el mail de prueba). Cada corrida a mano gasta 7 búsquedas.
