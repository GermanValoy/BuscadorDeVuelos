"""Buscador de vuelos baratos con alertas por mail.

Busca vuelos ida y vuelta en Google Flights (via SerpApi) para varias fechas
de salida y envia un mail cuando el precio por persona es menor o igual al
umbral configurado.

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
    "origen": "EZE",
    "destino": "MIA",
    "primera_salida": "2027-02-05",
    "dias_flexibles": 7,  # prueba salidas del 5 al 11 de febrero
    "estadia_dias": 14,
    # Las aerolineas cobran tarifa de adulto desde los 12 anios:
    # 2 adultos + adolescente de 14 = 3 adultos, nena de 6 = 1 menor.
    "adultos": 3,
    "menores": 1,
    "precio_max_por_persona": 500,
    "moneda": "USD",
}


def buscar(salida, regreso, cfg, api_key):
    params = {
        "engine": "google_flights",
        "departure_id": cfg["origen"],
        "arrival_id": cfg["destino"],
        "outbound_date": salida.isoformat(),
        "return_date": regreso.isoformat(),
        "type": "1",
        "adults": cfg["adultos"],
        "children": cfg["menores"],
        "currency": cfg["moneda"],
        "hl": "es",
        "api_key": api_key,
    }
    url = "https://serpapi.com/search.json?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=60) as resp:
        data = json.load(resp)
    if "error" in data:
        raise RuntimeError(data["error"])

    link = data.get("search_metadata", {}).get("google_flights_url", "")
    resultados = []
    for vuelo in data.get("best_flights", []) + data.get("other_flights", []):
        if "price" not in vuelo:
            continue
        tramos = vuelo["flights"]
        resultados.append({
            "salida": salida.isoformat(),
            "regreso": regreso.isoformat(),
            "total": vuelo["price"],
            "aerolineas": ", ".join(sorted({t["airline"] for t in tramos})),
            "escalas": len(tramos) - 1,
            "duracion_h": round(vuelo["total_duration"] / 60, 1),
            "link": link,
        })
    return resultados


def demo_resultados(salida, regreso, cfg):
    total = 1800 + (salida.day % 3) * 400
    return [{
        "salida": salida.isoformat(),
        "regreso": regreso.isoformat(),
        "total": total,
        "aerolineas": "Aerolinea Demo",
        "escalas": 1,
        "duracion_h": 13.5,
        "link": "https://www.google.com/travel/flights",
    }]


def enviar_mail(ofertas, cfg):
    pasajeros = cfg["adultos"] + cfg["menores"]
    lineas = [
        f"Encontre {len(ofertas)} vuelo(s) {cfg['origen']}-{cfg['destino']} "
        f"a {cfg['moneda']} {cfg['precio_max_por_persona']} o menos por persona "
        f"(ida y vuelta, {pasajeros} pasajeros):",
        "",
    ]
    for o in ofertas:
        lineas += [
            f"* {o['salida']} -> {o['regreso']} | {o['aerolineas']} | "
            f"{o['escalas']} escala(s) | {o['duracion_h']} h",
            f"  Total {cfg['moneda']} {o['total']} "
            f"({cfg['moneda']} {o['por_persona']} por persona)",
            f"  {o['link']}",
            "",
        ]
    lineas.append("Los precios cambian rapido: confirma antes de comprar.")

    msg = EmailMessage()
    mejor = ofertas[0]
    msg["Subject"] = (
        f"Alerta vuelos {cfg['origen']}-{cfg['destino']}: "
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
    parser.add_argument("--no-mail", action="store_true",
                        help="solo muestra resultados, no envia mail")
    args = parser.parse_args()

    cfg = dict(CONFIG)
    if args.umbral is not None:
        cfg["precio_max_por_persona"] = args.umbral
    api_key = os.environ.get("SERPAPI_KEY")
    if not args.demo and not api_key:
        sys.exit("Falta SERPAPI_KEY (o usa --demo)")

    pasajeros = cfg["adultos"] + cfg["menores"]
    primera = date.fromisoformat(cfg["primera_salida"])
    todos = []
    for i in range(cfg["dias_flexibles"]):
        salida = primera + timedelta(days=i)
        regreso = salida + timedelta(days=cfg["estadia_dias"])
        try:
            if args.demo:
                vuelos = demo_resultados(salida, regreso, cfg)
            else:
                vuelos = buscar(salida, regreso, cfg, api_key)
        except Exception as e:  # una fecha que falla no corta la busqueda
            print(f"{salida}: error {e}", file=sys.stderr)
            continue
        for v in vuelos:
            v["por_persona"] = round(v["total"] / pasajeros)
        todos += vuelos

    todos.sort(key=lambda v: v["total"])
    print(f"{len(todos)} vuelos encontrados. Los 10 mas baratos:")
    for v in todos[:10]:
        print(f"  {v['salida']} -> {v['regreso']}  {cfg['moneda']} {v['total']} "
              f"total / {v['por_persona']} p.p.  {v['aerolineas']} "
              f"({v['escalas']} esc., {v['duracion_h']} h)")

    ofertas = [v for v in todos
               if v["por_persona"] <= cfg["precio_max_por_persona"]]
    if not ofertas:
        print(f"Ninguno a {cfg['precio_max_por_persona']} o menos por persona.")
        return
    print(f"{len(ofertas)} oferta(s) bajo el umbral.")
    if args.no_mail:
        return
    enviar_mail(ofertas, cfg)
    print(f"Mail enviado a {os.environ['ALERT_TO']}.")


if __name__ == "__main__":
    main()
