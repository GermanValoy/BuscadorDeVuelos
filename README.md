# BuscadorDeVuelos
Buscador de vuelos baratos con alertas por mail.

Busca pasajes a Miami (MIA o Fort Lauderdale, FLL) desde Buenos Aires (EZE o
AEP) y desde Santiago de Chile (SCL), saliendo desde el 5 de febrero de 2027,
con regreso a más tardar el 28 de febrero y una estadía de 10 a 13 días, para 3
adultos (el adolescente de 14 paga tarifa de adulto) + 1 menor. Los parámetros
se cambian en `CONFIG` dentro de `buscador.py`.

## Cómo busca
- Busca la **ida y la vuelta por separado** (pasajes solo ida). Así puede
  combinar la ida más barata con la vuelta más barata, aunque sean de
  aerolíneas distintas. En las pruebas, dos pasajes separados salieron más
  baratos que un ida y vuelta.
- Hay 56 tramos (14 fechas de ida y 14 de vuelta por ciudad). Guarda el precio
  más barato de cada uno en `precios.json` (en GitHub, en la caché de Actions)
  y arma todas las combinaciones de la misma ciudad que cumplen la estadía.
- Cada día busca los 6 tramos con el precio más viejo (≈ 180 búsquedas por mes,
  dentro del plan gratis de SerpApi de 250). Todos se recorren cada ~10 días, y
  los precios de más de 12 días no se usan.
- Envía un mail si alguna combinación con algún tramo actualizado ese día cuesta
  USD 600 o menos por persona.

## Qué hay que conectar
1. **SerpApi** (datos de Google Flights): crear cuenta en https://serpapi.com y copiar la API key.
2. **Gmail**: activar verificación en 2 pasos y crear una *contraseña de aplicación*
   en https://myaccount.google.com/apppasswords.
3. **Secrets del repo** (Settings → Secrets and variables → Actions):
   `SERPAPI_KEY`, `SMTP_USER`, `SMTP_PASSWORD`, `ALERT_TO`.

## Probar
```bash
python buscador.py --demo --no-mail        # sin credenciales, precios de ejemplo
python buscador.py --no-mail               # búsqueda real de hoy (6 búsquedas)
python buscador.py --todas --no-mail       # todos los tramos (56 búsquedas, usar muy poco)
python buscador.py --mail-prueba           # manda un mail aunque no haya ofertas
```
En GitHub: Actions → "Alerta de vuelos baratos" → *Run workflow* (se puede
tildar el mail de prueba). Cada corrida a mano gasta 6 búsquedas.
