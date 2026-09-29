"""Buscador de vuelos baratos con alertas por mail.

Busca pasajes de ida y de vuelta por separado (solo ida) en Google Flights via
SerpApi, guarda el precio mas barato de cada tramo en un archivo de estado y
combina idas y vueltas de la misma ciudad que cumplan la estadia. Envia un mail
cuando alguna combinacion cuesta el umbral o menos por persona.

Pensado para el plan gratis de SerpApi (250 busquedas por mes): cada dia
actualiza los tramos mas viejos (primero los nunca vistos), de modo que en
pocos dias se recorren todos y despues se van refrescando.

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
    # nombre -> codigos de aeropuerto (separados por coma) de cada ciudad
    "origenes": {"Buenos Aires": "EZE,AEP", "Santiago": "SCL"},
    "destino": "MIA,FLL",  # Miami y Fort Lauderdale (a 40 min de Miami)
    "primera_salida": "2027-02-05",
    "ultimo_regreso": "2027-02-28",
    "estadia_min": 10,
    "estadia_max": 13,
    # 6 busquedas por dia = ~180 por mes (queda margen para pruebas a mano).
    "busquedas_por_dia": 6,
    # Precios mas viejos que esto no se usan para combinar (una vuelta completa
    # de todos los tramos tarda ~10 dias).
    "max_edad_dias": 12,
    # Las aerolineas cobran tarifa de adulto desde los 12 anios:
    # 2 adultos + adolescente de 14 = 3 adultos, nena de 6 = 1 menor.
    "adultos": 3,
    "menores": 1,
    "precio_max_por_persona": 600,
    "moneda": "USD",
}


def pasajeros(cfg):
    return cfg["adultos"] + cfg["menores"]


def todos_los_tramos(cfg):
    """Tramos (ciudad, "ida"/"vuelta", fecha) en un orden que arma combinaciones
    enseguida: ida del dia k seguida de la vuelta del dia k + estadia minima."""
    primera = date.fromisoformat(cfg["primera_salida"])
    ultimo = date.fromisoformat(cfg["ultimo_regreso"])
    dias = (ultimo - primera).days - cfg["estadia_min"] + 1
    tramos = []
    for k in range(dias):
        for ciudad in cfg["origenes"]:
            ida = primera + timedelta(days=k)
            tramos.append((ciudad, "ida", ida))
            tramos.append((ciudad, "vuelta", ida + timedelta(days=cfg["estadia_min"])))
    return tramos


def clave(ciudad, sentido, fecha):
    return f"{ciudad}|{sentido}|{fecha.isoformat()}"


def tramos_de_hoy(cfg, estado, todas=False):
    """Los tramos con el precio mas viejo (primero los nunca buscados)."""
    tramos = todos_los_tramos(cfg)
    if todas:
        return tramos
    orden = sorted(range(len(tramos)), key=lambda i: (
        estado.get(clave(*tramos[i]), {}).get("visto", ""), i))
    return [tramos[i] for i in orden[:cfg["busquedas_por_dia"]]]


def buscar_tramo(ciudad, sentido, fecha, cfg, api_key):
    origen, destino = cfg["origenes"][ciudad], cfg["destino"]
    if sentido == "vuelta":
        origen, destino = destino, origen
    params = {
        "engine": "google_flights",
        "departure_id": origen,
        "arrival_id": destino,
        "outbound_date": fecha.isoformat(),
        "type": "2",  # solo ida
        "adults": cfg["adultos"],
        "children": cfg["menores"],
        "currency": cfg["moneda"],
        "hl": "es",
        "api_key": api_key,
    }
    url = "https://serpapi.com/search.json?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=90) as resp:
        data = json.load(resp)
    if "error" in data:
        # sin vuelos ese dia no es una falla de la busqueda
        if "hasn't returned any results" in data["error"]:
            return None
        raise RuntimeError(data["error"])
    vuelos = [v for v in data.get("best_flights", []) + data.get("other_flights", [])
              if "price" in v]
    if not vuelos:
        return None
    v = min(vuelos, key=lambda v: v["price"])
    tramos = v["flights"]
    return {
        "total": v["price"],
        "aerolineas": ", ".join(sorted({t["airline"] for t in tramos})),
        "ruta": " > ".join([tramos[0]["departure_airport"]["id"]]
                           + [t["arrival_airport"]["id"] for t in tramos]),
        "sale": tramos[0]["departure_airport"]["time"],
        "llega": tramos[-1]["arrival_airport"]["time"],
        "duracion_h": round(v["total_duration"] / 60, 1),
        "link": data.get("search_metadata", {}).get("google_flights_url", ""),
    }


def demo_tramo(ciudad, sentido, fecha, cfg, api_key=None):
    base = 1700 if sentido == "ida" else 1250
    total = base + (fecha.day % 4) * 150 + (200 if ciudad == "Santiago" else 0)
    return {
        "total": total,
        "aerolineas": "Aerolinea Demo",
        "ruta": (f"{cfg['origenes'][ciudad][:3]} > PUJ > MIA" if sentido == "ida"
                 else f"MIA > PUJ > {cfg['origenes'][ciudad][:3]}"),
        "sale": f"{fecha.isoformat()} 04:45",
        "llega": f"{fecha.isoformat()} 15:08",
        "duracion_h": 12.4,
        "link": "https://www.google.com/travel/flights",
    }


def cargar_estado(ruta):
    try:
        with open(ruta) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def guardar_estado(ruta, estado):
    with open(ruta, "w") as f:
        json.dump(estado, f, indent=1, ensure_ascii=False, sort_keys=True)


def combinaciones(cfg, estado, hoy):
    """Combina idas y vueltas de la misma ciudad con precios recientes."""
    limite = (hoy - timedelta(days=cfg["max_edad_dias"])).isoformat()
    actuales = {clave(*t) for t in todos_los_tramos(cfg)}
    vigentes = {k: v for k, v in estado.items()
                if k in actuales and v.get("visto", "") >= limite and v.get("vuelo")}
    combos = []
    for k_ida, ida in vigentes.items():
        ciudad, sentido, f_ida = k_ida.split("|")
        if sentido != "ida":
            continue
        for dias in range(cfg["estadia_min"], cfg["estadia_max"] + 1):
            f_vuelta = date.fromisoformat(f_ida) + timedelta(days=dias)
            if f_vuelta > date.fromisoformat(cfg["ultimo_regreso"]):
                break
            vuelta = vigentes.get(clave(ciudad, "vuelta", f_vuelta))
            if not vuelta:
                continue
            total = ida["vuelo"]["total"] + vuelta["vuelo"]["total"]
            combos.append({
                "ciudad": ciudad,
                "dias": dias,
                "ida": dict(ida["vuelo"], fecha=f_ida, visto=ida["visto"]),
                "vuelta": dict(vuelta["vuelo"], fecha=f_vuelta.isoformat(),
                               visto=vuelta["visto"]),
                "total": total,
                "por_persona": round(total / pasajeros(cfg)),
            })
    combos.sort(key=lambda c: c["total"])
    return combos


def texto_combo(c, cfg, hoy):
    m = cfg["moneda"]
    lineas = [f"{c['ciudad']} - Miami, {c['ida']['fecha']} al {c['vuelta']['fecha']} "
              f"({c['dias']} dias): {m} {c['por_persona']} por persona "
              f"({m} {c['total']} en total)"]
    for nombre in ("ida", "vuelta"):
        t = c[nombre]
        edad = (hoy - date.fromisoformat(t["visto"])).days
        visto = "hoy" if edad == 0 else f"hace {edad} dia(s)"
        lineas.append(
            f"   {nombre.capitalize()}: {t['aerolineas']} | {t['ruta']} | "
            f"sale {t['sale']} llega {t['llega']} | {t['duracion_h']} h | "
            f"{m} {round(t['total'] / pasajeros(cfg))} p.p. (precio visto {visto})")
        lineas.append(f"   {t['link']}")
    return "\n".join(lineas)


def enviar_mail(combos, cfg, hoy, prueba=False):
    m = cfg["moneda"]
    if prueba:
        intro = ("MAIL DE PRUEBA: el buscador funciona y las alertas te van a llegar aca.\n"
                 f"Estas son las mejores combinaciones de hoy, esten o no bajo el tope "
                 f"de {m} {cfg['precio_max_por_persona']:g} por persona:")
    else:
        intro = (f"Encontre {len(combos)} combinacion(es) de ida y vuelta a Miami a "
                 f"{m} {cfg['precio_max_por_persona']:g} o menos por persona "
                 f"({pasajeros(cfg)} pasajeros):")
    cuerpo = [intro, ""]
    for c in combos[:10]:
        cuerpo += [texto_combo(c, cfg, hoy), ""]
    cuerpo.append("La ida y la vuelta son pasajes separados: compra los dos, y "
                  "revisa el precio final con equipaje antes de pagar (las low cost "
                  "cobran la valija aparte). Los precios cambian rapido.")

    mejor = combos[0]
    msg = EmailMessage()
    msg["Subject"] = ("[Prueba] " if prueba else "") + (
        f"Alerta vuelos {mejor['ciudad']}-Miami: {m} {mejor['por_persona']} por persona")
    msg["From"] = os.environ["SMTP_USER"]
    msg["To"] = os.environ["ALERT_TO"]
    msg.set_content("\n".join(cuerpo))

    host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    port = int(os.environ.get("SMTP_PORT", "465"))
    with smtplib.SMTP_SSL(host, port) as smtp:
        smtp.login(os.environ["SMTP_USER"], os.environ["SMTP_PASSWORD"])
        smtp.send_message(msg)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--demo", action="store_true",
                        help="usa precios de ejemplo en vez de SerpApi")
    parser.add_argument("--estado", default="precios.json",
                        help="archivo donde se guardan los precios de cada tramo")
    parser.add_argument("--umbral", type=float,
                        help="precio maximo por persona (pisa la config)")
    parser.add_argument("--todas", action="store_true",
                        help="busca todos los tramos hoy (gasta muchas busquedas: "
                             "usar solo de vez en cuando)")
    parser.add_argument("--mail-prueba", action="store_true",
                        help="envia un mail con las mejores combinaciones aunque "
                             "ninguna este bajo el umbral")
    parser.add_argument("--no-mail", action="store_true",
                        help="solo muestra resultados, no envia mail")
    args = parser.parse_args()

    cfg = dict(CONFIG)
    if args.umbral is not None:
        cfg["precio_max_por_persona"] = args.umbral
    api_key = os.environ.get("SERPAPI_KEY")
    if not args.demo and not api_key:
        sys.exit("Falta SERPAPI_KEY (o usa --demo)")

    hoy = date.today()
    estado = cargar_estado(args.estado)
    buscar = demo_tramo if args.demo else buscar_tramo
    tramos = tramos_de_hoy(cfg, estado, args.todas)
    print(f"Busquedas de hoy ({len(tramos)}): "
          + ", ".join(f"{c} {s} {f:%d/%m}" for c, s, f in tramos))

    ok = 0
    for ciudad, sentido, fecha in tramos:
        try:
            vuelo = buscar(ciudad, sentido, fecha, cfg, api_key)
        except Exception as e:  # una busqueda que falla no corta las demas
            print(f"{ciudad} {sentido} {fecha}: error {e}", file=sys.stderr)
            continue
        ok += 1
        estado[clave(ciudad, sentido, fecha)] = {"visto": hoy.isoformat(), "vuelo": vuelo}
        if vuelo:
            print(f"  {ciudad} {sentido} {fecha:%d/%m}: {cfg['moneda']} "
                  f"{round(vuelo['total'] / pasajeros(cfg))} p.p. "
                  f"{vuelo['aerolineas']} ({vuelo['ruta']})")
        else:
            print(f"  {ciudad} {sentido} {fecha:%d/%m}: sin vuelos")
    guardar_estado(args.estado, estado)
    if tramos and not ok:
        sys.exit("Fallaron todas las busquedas: revisa SERPAPI_KEY y los errores de arriba.")

    actuales = [clave(*t) for t in todos_los_tramos(cfg)]
    print(f"Tramos buscados alguna vez: {sum(k in estado for k in actuales)} "
          f"de {len(actuales)}.")
    combos = combinaciones(cfg, estado, hoy)
    print(f"{len(combos)} combinaciones ida + vuelta. Las 5 mas baratas:")
    for c in combos[:5]:
        print(texto_combo(c, cfg, hoy))
    for ciudad in cfg["origenes"]:
        mejor = next((c for c in combos if c["ciudad"] == ciudad), None)
        print(f"Mas barato desde {ciudad}: " + (
            f"{cfg['moneda']} {mejor['por_persona']} p.p. "
            f"({mejor['ida']['fecha']} al {mejor['vuelta']['fecha']})"
            if mejor else "todavia sin combinaciones"))

    if args.mail_prueba:
        if not combos:
            sys.exit("Todavia no hay combinaciones para el mail de prueba.")
        enviar_mail(combos, cfg, hoy, prueba=True)
        print(f"Mail de prueba enviado a {os.environ['ALERT_TO']}.")
        return

    # Solo se avisa por combinaciones con algun tramo actualizado hoy, para no
    # repetir todos los dias la misma oferta con precios viejos.
    ofertas = [c for c in combos
               if c["por_persona"] <= cfg["precio_max_por_persona"]
               and hoy.isoformat() in (c["ida"]["visto"], c["vuelta"]["visto"])]
    if not ofertas:
        print(f"Ninguna combinacion nueva a {cfg['precio_max_por_persona']:g} "
              "o menos por persona.")
        return
    print(f"{len(ofertas)} combinacion(es) bajo el umbral.")
    if args.no_mail:
        return
    enviar_mail(ofertas, cfg, hoy)
    print(f"Mail enviado a {os.environ['ALERT_TO']}.")


if __name__ == "__main__":
    main()
