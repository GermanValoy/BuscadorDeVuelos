"""Buscador de vuelos baratos con alertas por mail.

Pensado para el plan gratis de SerpApi (250 busquedas por mes). Cada dia hace:

1. Radar (1 busqueda por origen): Google Travel Explore devuelve el viaje de
   ~2 semanas mas barato de todo el mes, sin fijar fechas.
2. Fechas exactas (rotativas): Google Flights con salida y regreso fijos. Cada
   dia prueba unas pocas combinaciones origen/fecha distintas, de modo que en
   pocos dias se recorren todas.

Envia un mail cuando algun vuelo cuesta el umbral o menos por persona.

Variables de entorno:
  SERPAPI_KEY      API key de https://serpapi.com (obligatoria salvo --demo)
  SMTP_USER        cuenta de Gmail que envia (ej. tucuenta@gmail.com)
  SMTP_PASSWORD    contrasena de aplicacion de Gmail (16 caracteres)
  ALERT_TO         mail que recibe las alertas
  SMTP_HOST/PORT   opcionales (por defecto smtp.gmail.com:465)
"""

import argparse
import json
import os
import smtplib
import sys
import urllib.parse
import urllib.request
from datetime import date, timedelta
from email.message import EmailMessage

CONFIG = {
    "origenes": ["EZE", "SCL"],  # Buenos Aires (Ezeiza) y Santiago de Chile
    "destino": "MIA",
    "primera_salida": "2027-02-05",
    "ultima_salida": "2027-02-15",
    "estadia_dias": 14,
    # El radar no deja fijar la estadia exacta: acepta viajes de 14 +/- 2 dias.
    "tolerancia_estadia": 2,
    # 2 radares + 5 fechas exactas = 7 busquedas por dia, ~210 por mes.
    "busquedas_exactas_por_dia": 5,
    # Las aerolineas cobran tarifa de adulto desde los 12 anios:
    # 2 adultos + adolescente de 14 = 3 adultos, nena de 6 = 1 menor.
    "adultos": 3,
    "menores": 1,
    "precio_max_por_persona": 600,
    "moneda": "USD",
}


def serpapi(params, cfg, api_key):
    params = dict(params, arrival_id=cfg["destino"], adults=cfg["adultos"],
                  children=cfg["menores"], currency=cfg["moneda"], hl="es",
                  api_key=api_key)
    url = "https://serpapi.com/search.json?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=90) as resp:
        data = json.load(resp)
    if "error" in data:
        raise RuntimeError(data["error"])
    return data


def buscar_fecha(origen, salida, regreso, cfg, api_key):
    data = serpapi({
        "engine": "google_flights",
        "departure_id": origen,
        "outbound_date": salida.isoformat(),
        "return_date": regreso.isoformat(),
        "type": "1",
    }, cfg, api_key)
    link = data.get("search_metadata", {}).get("google_flights_url", "")
    resultados = []
    for vuelo in data.get("best_flights", []) + data.get("other_flights", []):
        if "price" not in vuelo:
            continue
        tramos = vuelo["flights"]
        resultados.append({
            "fuente": "fecha exacta",
            "origen": origen,
            "salida": salida.isoformat(),
            "regreso": regreso.isoformat(),
            "total": vuelo["price"],
            "aerolineas": ", ".join(sorted({t["airline"] for t in tramos})),
            "escalas": len(tramos) - 1,
            "duracion_h": round(vuelo["total_duration"] / 60, 1),
            "link": link,
        })
    return resultados


def explorar_mes(origen, cfg, api_key):
    primera = date.fromisoformat(cfg["primera_salida"])
    data = serpapi({
        "engine": "google_travel_explore",
        "departure_id": origen,
        "month": primera.month,
        "travel_duration": 3,  # viajes de ~2 semanas
    }, cfg, api_key)
    if "start_date" not in data:
        return []
    return [{
        "fuente": "radar del mes",
        "origen": origen,
        "salida": data["start_date"],
        "regreso": data["end_date"],
        "total": vuelo["price"],
        "aerolineas": vuelo.get("airline", "?"),
        "escalas": vuelo.get("number_of_stops", "?"),
        "duracion_h": round(vuelo.get("duration", 0) / 60, 1),
        "link": data.get("google_flights_link", ""),
    } for vuelo in data.get("flights", []) if "price" in vuelo]


def fechas_de_hoy(cfg, hoy, todas=False):
    """Combinaciones (origen, salida) a buscar hoy, rotando dia a dia."""
    primera = date.fromisoformat(cfg["primera_salida"])
    ultima = date.fromisoformat(cfg["ultima_salida"])
    combos = [(origen, primera + timedelta(days=i))
              for i in range((ultima - primera).days + 1)
              for origen in cfg["origenes"]]
    if todas:
        return combos
    n = min(cfg["busquedas_exactas_por_dia"], len(combos))
    inicio = hoy.toordinal() * n % len(combos)
    return [combos[(inicio + k) % len(combos)] for k in range(n)]


def fecha_valida(v, cfg):
    salida = date.fromisoformat(v["salida"])
    regreso = date.fromisoformat(v["regreso"])
    estadia = (regreso - salida).days
    return (date.fromisoformat(cfg["primera_salida"]) <= salida
            <= date.fromisoformat(cfg["ultima_salida"])
            and abs(estadia - cfg["estadia_dias"]) <= cfg["tolerancia_estadia"])


def demo_fecha(origen, salida, regreso, cfg, api_key=None):
    total = 1800 + (salida.day % 3) * 400 + (300 if origen == "SCL" else 0)
    return [{
        "fuente": "fecha exacta",
        "origen": origen,
        "salida": salida.isoformat(),
        "regreso": regreso.isoformat(),
        "total": total,
        "aerolineas": "Aerolinea Demo",
        "escalas": 1,
        "duracion_h": 13.5,
        "link": "https://www.google.com/travel/flights",
    }]


def demo_mes(origen, cfg, api_key=None):
    salida = date(2027, 2, 13 if origen == "EZE" else 2)  # SCL: fuera de rango
    return [{
        "fuente": "radar del mes",
        "origen": origen,
        "salida": salida.isoformat(),
        "regreso": (salida + timedelta(days=16)).isoformat(),
        "total": 2300,
        "aerolineas": "Aerolinea Demo",
        "escalas": 1,
        "duracion_h": 13.3,
        "link": "https://www.google.com/travel/flights",
    }]


def texto_vuelo(v, cfg):
    estadia = (date.fromisoformat(v["regreso"]) - date.fromisoformat(v["salida"])).days
    return (f"{v['origen']}-{cfg['destino']} | {v['salida']} -> {v['regreso']} "
            f"({estadia} dias) | {v['aerolineas']} | {v['escalas']} escala(s) | "
            f"{v['duracion_h']} h | {v['fuente']}")


def enviar_mail(ofertas, cfg, prueba=False):
    pasajeros = cfg["adultos"] + cfg["menores"]
    if prueba:
        lineas = [
            "MAIL DE PRUEBA: el buscador funciona y las alertas te van a llegar aca.",
            f"Estos son los vuelos mas baratos de hoy (ida y vuelta, {pasajeros} "
            f"pasajeros), esten o no bajo el tope de {cfg['moneda']} "
            f"{cfg['precio_max_por_persona']:g} por persona:",
            "",
        ]
    else:
        lineas = [
            f"Encontre {len(ofertas)} vuelo(s) a {cfg['destino']} "
            f"a {cfg['moneda']} {cfg['precio_max_por_persona']:g} o menos por persona "
            f"(ida y vuelta, {pasajeros} pasajeros):",
            "",
        ]
    for o in ofertas:
        lineas += [
            "* " + texto_vuelo(o, cfg),
            f"  Total {cfg['moneda']} {o['total']} "
            f"({cfg['moneda']} {o['por_persona']} por persona)",
            f"  {o['link']}",
            "",
        ]
    lineas.append("Los precios cambian rapido: confirma antes de comprar.")

    msg = EmailMessage()
    mejor = min(ofertas, key=lambda v: v["total"])
    msg["Subject"] = ("[Prueba] " if prueba else "") + (
        f"Alerta vuelos {mejor['origen']}-{cfg['destino']}: "
        f"{cfg['moneda']} {mejor['por_persona']} por persona"
    )
    msg["From"] = os.environ["SMTP_USER"]
    msg["To"] = os.environ["ALERT_TO"]
    msg.set_content("\n".join(lineas))

    host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    port = int(os.environ.get("SMTP_PORT", "465"))
    with smtplib.SMTP_SSL(host, port) as smtp:
        smtp.login(os.environ["SMTP_USER"], os.environ["SMTP_PASSWORD"])
        smtp.send_message(msg)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--demo", action="store_true",
                        help="usa precios de ejemplo en vez de SerpApi")
    parser.add_argument("--umbral", type=float,
                        help="precio maximo por persona (pisa la config)")
    parser.add_argument("--todas", action="store_true",
                        help="busca todas las fechas exactas hoy (gasta muchas "
                             "busquedas: usar solo de vez en cuando)")
    parser.add_argument("--mail-prueba", action="store_true",
                        help="envia un mail con los vuelos mas baratos aunque "
                             "ninguno este bajo el umbral")
    parser.add_argument("--no-mail", action="store_true",
                        help="solo muestra resultados, no envia mail")
    args = parser.parse_args()

    cfg = dict(CONFIG)
    if args.umbral is not None:
        cfg["precio_max_por_persona"] = args.umbral
    api_key = os.environ.get("SERPAPI_KEY")
    if not args.demo and not api_key:
        sys.exit("Falta SERPAPI_KEY (o usa --demo)")

    radar, fecha = (demo_mes, demo_fecha) if args.demo else (explorar_mes, buscar_fecha)
    tareas = [(f"radar {o}", radar, (o,)) for o in cfg["origenes"]]
    for origen, salida in fechas_de_hoy(cfg, date.today(), args.todas):
        regreso = salida + timedelta(days=cfg["estadia_dias"])
        tareas.append((f"{origen} {salida}", fecha, (origen, salida, regreso)))
    print(f"Busquedas de hoy ({len(tareas)}): " + ", ".join(t[0] for t in tareas))

    pasajeros = cfg["adultos"] + cfg["menores"]
    todos = []
    ok = 0
    for nombre, funcion, datos in tareas:
        try:
            vuelos = funcion(*datos, cfg, api_key)
        except Exception as e:  # una busqueda que falla no corta las demas
            print(f"{nombre}: error {e}", file=sys.stderr)
            continue
        ok += 1
        for v in vuelos:
            v["por_persona"] = round(v["total"] / pasajeros)
            if not fecha_valida(v, cfg):
                print(f"  (descartado, fuera de fechas: {texto_vuelo(v, cfg)} "
                      f"{cfg['moneda']} {v['por_persona']} p.p.)")
                continue
            todos.append(v)

    if not ok:
        sys.exit("Fallaron todas las busquedas: revisa SERPAPI_KEY y los errores de arriba.")

    todos.sort(key=lambda v: v["total"])
    print(f"{len(todos)} vuelos en fechas validas. Los 10 mas baratos:")
    for v in todos[:10]:
        print(f"  {cfg['moneda']} {v['total']} total / {v['por_persona']} p.p.  "
              + texto_vuelo(v, cfg))

    if args.mail_prueba:
        # los 3 mas baratos de cada origen
        muestra = [v for o in cfg["origenes"]
                   for v in [x for x in todos if x["origen"] == o][:3]]
        if not muestra:
            sys.exit("No hay vuelos en fechas validas para el mail de prueba.")
        enviar_mail(muestra, cfg, prueba=True)
        print(f"Mail de prueba enviado a {os.environ['ALERT_TO']}.")
        return

    ofertas = [v for v in todos
               if v["por_persona"] <= cfg["precio_max_por_persona"]]
    if not ofertas:
        print(f"Ninguno a {cfg['precio_max_por_persona']:g} o menos por persona.")
        return
    print(f"{len(ofertas)} oferta(s) bajo el umbral.")
    if args.no_mail:
        return
    enviar_mail(ofertas, cfg)
    print(f"Mail enviado a {os.environ['ALERT_TO']}.")


if __name__ == "__main__":
    main()
