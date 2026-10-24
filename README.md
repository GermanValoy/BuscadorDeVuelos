# BuscadorDeVuelos
Buscador de vuelos baratos con alertas por mail.

Busca pasajes a Miami (MIA o Fort Lauderdale, FLL) desde Buenos Aires (EZE o
AEP) y desde Santiago de Chile (SCL), saliendo desde el 1 de febrero de 2027 y
volviendo hasta el 31 de marzo (incluye salir en febrero y volver en marzo), con
una estadía de 7 a 21 días, para 3 adultos (el adolescente de 14 paga tarifa de
adulto) + 1 menor. Envía por mail todas las combinaciones de USD 600 o menos por
persona. Los parámetros se cambian en `CONFIG` dentro de `buscador.py`.

## Cómo busca (8 búsquedas por día, ≈ 240 por mes: no correrlo a mano)
- **Radar** (4 búsquedas): Google Travel Explore devuelve el ida y vuelta más
  barato de todo febrero y de todo marzo, desde cada ciudad. Alterna día por
  medio entre viajes de ~1 semana y de ~2 semanas. Detecta promos de todo el mes
  con muy pocas búsquedas.
- **Tramos** (4 búsquedas): pasajes solo ida para una fecha fija. Hay 208
  tramos (52 fechas de ida y 52 de vuelta por ciudad); se busca primero el de
  precio más viejo, así que cada uno se actualiza cada ~52 días. El precio más
  barato de cada tramo se guarda en `precios.json` (en GitHub, en la caché de
  Actions) y se combinan idas y vueltas de la misma ciudad que cumplen la
  estadía. Los precios de más de 60 días no se usan.
- **Mail**: lista todas las combinaciones de USD 600 o menos por persona, y
  solo se envía cuando aparece una nueva o una ya avisada baja de precio.

## Qué hay que conectar
1. **SerpApi** (datos de Google Flights): crear cuenta en https://serpapi.com y copiar la API key.
2. **Gmail**: activar verificación en 2 pasos y crear una *contraseña de aplicación*
   en https://myaccount.google.com/apppasswords.
3. **Secrets del repo** (Settings → Secrets and variables → Actions):
   `SERPAPI_KEY`, `SMTP_USER`, `SMTP_PASSWORD`, `ALERT_TO`.

## Probar
```bash
python buscador.py --demo --no-mail        # sin credenciales, precios de ejemplo
python buscador.py --no-mail               # búsqueda real de hoy (8 búsquedas)
python buscador.py --todas --no-mail       # todos los tramos (212 búsquedas, solo con plan pago)
python buscador.py --mail-prueba           # manda un mail aunque no haya ofertas
```
En GitHub: Actions → "Alerta de vuelos baratos" → *Run workflow* (se puede
tildar el mail de prueba). Cada corrida a mano gasta 8 búsquedas.
