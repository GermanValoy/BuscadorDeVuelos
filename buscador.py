"""Buscador de vuelos baratos con alertas por mail.

Pensado para el plan gratis de SerpApi (250 busquedas por mes). Cada dia hace:

1. Radar (1 busqueda por ciudad y mes): Google Travel Explore devuelve el ida y
   vuelta mas barato de todo el mes, sin fijar fechas. Alterna dia por medio
   entre viajes de ~1 semana y de ~2 semanas.
2. Tramos (rotativos): pasajes solo ida de Google Flights para una fecha fija.
   El precio mas barato de cada tramo se guarda en un archivo de estado y se
   combinan idas y vueltas de la misma ciudad que cumplan la estadia.

Envia un mail con todas las combinaciones bajo el umbral cuando aparece una
nueva o una ya avisada baja de precio.

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
    # nombre -> codigos de aeropuerto (separados por coma) de cada ciudad;
    # el radar usa solo el primero.
    "origenes": {"Buenos Aires": "EZE,AEP", "Santiago": "SCL"},
    "destino": "MIA,FLL",  # Miami y Fort Lauderdale (a 40 min de Miami)
    "primera_salida": "2027-02-01",
    "ultimo_regreso": "2027-03-31",
    "estadia_min": 7,
    "estadia_max": 21,
    # 4 radares (2 ciudades x 2 meses) + 4 tramos = 8 busquedas por dia,
    # ~240 por mes: no dispares corridas a mano.
    "tramos_por_dia": 4,
    "usar_radar": True,
    # Con 208 tramos y 4 por dia, cada uno se actualiza cada ~52 dias.
    "max_edad_dias": 60,
    # Las aerolineas cobran tarifa de adulto desde los 12 anios:
    # 2 adultos + adolescente de 14 = 3 adultos, nena de 6 = 1 menor.
    "adultos": 3,
    "menores": 1,
    "precio_max_por_persona": 600,
    "moneda": "USD",
}

AVISADOS = "_avisados"  # clave del estado con las combinaciones ya avisadas


def pasajeros(cfg):
    return cfg["adultos"] + cfg["menores"]


def meses(cfg):
    primera = date.fromisoformat(cfg["primera_salida"])
    ultimo = date.fromisoformat(cfg["ultimo_regreso"])
    return list(range(primera.month, ultimo.month + 1))


def todos_los_tramos(cfg):
    """Tramos (ciudad, "ida"/"vuelta", fecha).

    Cada ida del dia d va junto a la vuelta del dia d + estadia minima (asi
    forman una combinacion enseguida) y los dias se recorren salteados, para
    cubrir febrero y marzo parejo desde el principio.
    """
    primera = date.fromisoformat(cfg["primera_salida"])
    ultimo = date.fromisoformat(cfg["ultimo_regreso"])
    dias = (ultimo - primera).days - cfg["estadia_min"] + 1
    paso = next(p for p in range(dias // 2 + 1, dias) if _mcd(p, dias) == 1)
    tramos = []
    for i in range(dias):
        ida = primera + timedelta(days=i * paso % dias)
        for ciudad in cfg["origenes"]:
            tramos.append((ciudad, "ida", ida))
            tramos.append((ciudad, "vuelta", ida + timedelta(days=cfg["estadia_min"])))
    return tramos


def _mcd(a, b):
    while b:
        a, b = b, a % b
    return a


def clave(ciudad, sentido, fecha):
    return f"{ciudad}|{sentido}|{fecha.isoformat()}"


def tramos_de_hoy(cfg, estado, todas=False):
    """Los tramos con el precio mas viejo (primero los nunca buscados)."""
    tramos = todos_los_tramos(cfg)
    if todas:
        return tramos
    orden = sorted(range(len(tramos)), key=lambda i: (
        estado.get(clave(*tramos[i]), {}).get("visto", ""), i))
    return [tramos[i] for i in orden[:cfg["tramos_por_dia"]]]


def serpapi(params, cfg, api_key):
    params = dict(params, adults=cfg["adultos"], children=cfg["menores"],
                  currency=cfg["moneda"], hl="es", api_key=api_key)
    url = "https://serpapi.com/search.json?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=90) as resp:
        data = json.load(resp)
    if "error" in data and "hasn't returned any results" not in data["error"]:
        raise RuntimeError(data["error"])
    return data


def buscar_tramo(ciudad, sentido, fecha, cfg, api_key):
    origen, destino = cfg["origenes"][ciudad], cfg["destino"]
    if sentido == "vuelta":
        origen, destino = destino, origen
    data = serpapi({
        "engine": "google_flights",
        "departure_id": origen,
        "arrival_id": destino,
        "outbound_date": fecha.isoformat(),
        "type": "2",  # solo ida
    }, cfg, api_key)
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


def buscar_radar(ciudad, mes, duracion, cfg, api_key):
    """Ida y vuelta mas barato del mes (Google Travel Explore)."""
    data = serpapi({
        "engine": "google_travel_explore",
        "departure_id": cfg["origenes"][ciudad].split(",")[0],
        "arrival_id": cfg["destino"].split(",")[0],
        "month": mes,
        "travel_duration": duracion,  # 2: ~1 semana, 3: ~2 semanas
    }, cfg, api_key)
    vuelos = [v for v in data.get("flights", []) if "price" in v]
    if "start_date" not in data or not vuelos:
        return None
    v = min(vuelos, key=lambda v: v["price"])
    return combo_radar(ciudad, data["start_date"], data["end_date"], {
        "total": v["price"],
        "aerolineas": v.get("airline", "?"),
        "escalas": v.get("number_of_stops", "?"),
        "duracion_h": round(v.get("duration", 0) / 60, 1),
        "link": data.get("google_flights_link", ""),
    }, cfg)


def combo_radar(ciudad, salida, regreso, vuelo, cfg):
    return {
        "ciudad": ciudad,
        "fuente": "radar",
        "salida": salida,
        "regreso": regreso,
        "dias": (date.fromisoformat(regreso) - date.fromisoformat(salida)).days,
        "vuelo": vuelo,
        "total": vuelo["total"],
        "por_persona": round(vuelo["total"] / pasajeros(cfg)),
    }


def demo_tramo(ciudad, sentido, fecha, cfg, api_key=None):
    base = 1500 if sentido == "ida" else 1050
    total = base + (fecha.day % 4) * 150 + (200 if ciudad == "Santiago" else 0)
    codigo = cfg["origenes"][ciudad][:3]
    return {
        "total": total,
        "aerolineas": "Aerolinea Demo",
        "ruta": f"{codigo} > PUJ > MIA" if sentido == "ida" else f"MIA > PUJ > {codigo}",
        "sale": f"{fecha.isoformat()} 04:45",
        "llega": f"{fecha.isoformat()} 15:08",
        "duracion_h": 12.4,
        "link": "https://www.google.com/travel/flights",
    }


def demo_radar(ciudad, mes, duracion, cfg, api_key=None):
    salida = date(2027, mes, 20)
    dias = 9 if duracion == 2 else 15
    return combo_radar(ciudad, salida.isoformat(),
                       (salida + timedelta(days=dias)).isoformat(), {
                           "total": 1880 if ciudad == "Santiago" else 2300,
                           "aerolineas": "Aerolinea Demo",
                           "escalas": 1,
                           "duracion_h": 12.1,
                           "link": "https://www.google.com/travel/flights",
                       }, cfg)


def cargar_estado(ruta):
    try:
        with open(ruta) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def guardar_estado(ruta, estado):
    with open(ruta, "w") as f:
        json.dump(estado, f, indent=1, ensure_ascii=False, sort_keys=True)


def fechas_validas(salida, regreso, cfg):
    salida, regreso = date.fromisoformat(salida), date.fromisoformat(regreso)
    return (salida >= date.fromisoformat(cfg["primera_salida"])
            and regreso <= date.fromisoformat(cfg["ultimo_regreso"])
            and cfg["estadia_min"] <= (regreso - salida).days <= cfg["estadia_max"])


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
            f_vuelta = (date.fromisoformat(f_ida) + timedelta(days=dias)).isoformat()
            vuelta = vigentes.get(f"{ciudad}|vuelta|{f_vuelta}")
            if not vuelta or not fechas_validas(f_ida, f_vuelta, cfg):
                continue
            total = ida["vuelo"]["total"] + vuelta["vuelo"]["total"]
            combos.append({
                "ciudad": ciudad,
                "fuente": "tramos",
                "salida": f_ida,
                "regreso": f_vuelta,
                "dias": dias,
                "ida": dict(ida["vuelo"], visto=ida["visto"]),
                "vuelta": dict(vuelta["vuelo"], visto=vuelta["visto"]),
                "total": total,
                "por_persona": round(total / pasajeros(cfg)),
            })
    return combos


def id_combo(c):
    return f"{c['ciudad']}|{c['salida']}|{c['regreso']}|{c['fuente']}"


def visto(fecha_iso, hoy):
    edad = (hoy - date.fromisoformat(fecha_iso)).days
    return "hoy" if edad == 0 else f"hace {edad} dia(s)"


def texto_combo(c, cfg, hoy):
    m = cfg["moneda"]
    lineas = [f"{c['ciudad']} - Miami | {c['salida']} al {c['regreso']} | "
              f"{c['dias']} dias | {m} {c['por_persona']} por persona "
              f"({m} {c['total']} en total)"]
    if c["fuente"] == "radar":
        v = c["vuelo"]
        lineas.append(f"   Ida y vuelta: {v['aerolineas']} | {v['escalas']} escala(s) | "
                      f"{v['duracion_h']} h por tramo | precio visto hoy (radar)")
        lineas.append(f"   {v['link']}")
        return "\n".join(lineas)
    for nombre in ("ida", "vuelta"):
        t = c[nombre]
        lineas.append(
            f"   {nombre.capitalize()}: {t['aerolineas']} | {t['ruta']} | "
            f"sale {t['sale']} llega {t['llega']} | {t['duracion_h']} h | "
            f"{m} {round(t['total'] / pasajeros(cfg))} p.p. "
            f"(precio visto {visto(t['visto'], hoy)})")
        lineas.append(f"   {t['link']}")
    return "\n".join(lineas)


def enviar_mail(combos, nuevas, cfg, hoy, prueba=False):
    m = cfg["moneda"]
    tope = f"{m} {cfg['precio_max_por_persona']:g}"
    if prueba:
        intro = ("MAIL DE PRUEBA: el buscador funciona y las alertas te van a llegar aca.\n"
                 f"Estas son las mejores combinaciones de hoy, esten o no bajo {tope} "
                 "por persona:")
    else:
        intro = (f"Hay {len(combos)} combinacion(es) de ida y vuelta a Miami a {tope} o "
                 f"menos por persona ({pasajeros(cfg)} pasajeros), {len(nuevas)} "
                 "nueva(s) o mas barata(s) desde el ultimo aviso (marcadas con NUEVA):")
    cuerpo = [intro, ""]
    for c in combos:
        marca = "NUEVA " if id_combo(c) in nuevas else ""
        cuerpo += [marca + texto_combo(c, cfg, hoy), ""]
    cuerpo.append("Las combinaciones de 'tramos' son dos pasajes separados (ida y vuelta): "
                  "hay que comprar los dos. Revisa el precio final con equipaje antes de "
                  "pagar (las low cost cobran la valija aparte) y confirma los precios "
                  "vistos hace varios dias: cambian rapido.")

    mejor = combos[0]
    msg = EmailMessage()
    msg["Subject"] = ("[Prueba] " if prueba else "") + (
        f"Vuelos a Miami: {len(combos)} combinacion(es) desde {m} "
        f"{mejor['por_persona']} por persona")
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
                        help="busca todos los tramos hoy (gasta muchisimas "
                             "busquedas: usar solo con un plan pago)")
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
    avisados = estado.pop(AVISADOS, {})
    radar, tramo = (demo_radar, demo_tramo) if args.demo else (buscar_radar, buscar_tramo)
    duracion = 2 if hoy.toordinal() % 2 else 3  # alterna ~1 y ~2 semanas

    tareas = []
    if cfg["usar_radar"]:
        tareas += [(f"radar {c} mes {m}", radar, (c, m, duracion))
                   for c in cfg["origenes"] for m in meses(cfg)]
    tareas += [(f"{c} {s} {f:%d/%m}", tramo, (c, s, f))
               for c, s, f in tramos_de_hoy(cfg, estado, args.todas)]
    print(f"Busquedas de hoy ({len(tareas)}): " + ", ".join(t[0] for t in tareas))

    ok = 0
    radares = []
    for nombre, funcion, datos in tareas:
        try:
            resultado = funcion(*datos, cfg, api_key)
        except Exception as e:  # una busqueda que falla no corta las demas
            print(f"{nombre}: error {e}", file=sys.stderr)
            continue
        ok += 1
        if funcion is radar:
            if not resultado:
                print(f"  {nombre}: sin resultados")
            elif not fechas_validas(resultado["salida"], resultado["regreso"], cfg):
                print(f"  {nombre}: descartado (fuera de fechas) {resultado['salida']} "
                      f"al {resultado['regreso']}, {cfg['moneda']} "
                      f"{resultado['por_persona']} p.p.")
            else:
                print(f"  {nombre}: {resultado['salida']} al {resultado['regreso']} "
                      f"({resultado['dias']} dias), {cfg['moneda']} "
                      f"{resultado['por_persona']} p.p.")
                radares.append(resultado)
            continue
        estado[clave(*datos)] = {"visto": hoy.isoformat(), "vuelo": resultado}
        print(f"  {nombre}: " + (f"{cfg['moneda']} {round(resultado['total'] / pasajeros(cfg))} "
                                 f"p.p. {resultado['aerolineas']} ({resultado['ruta']})"
                                 if resultado else "sin vuelos"))
    if tareas and not ok:
        guardar_estado(args.estado, dict(estado, **{AVISADOS: avisados}))
        sys.exit("Fallaron todas las busquedas: revisa SERPAPI_KEY y los errores de arriba.")

    actuales = [clave(*t) for t in todos_los_tramos(cfg)]
    print(f"Tramos buscados alguna vez: {sum(k in estado for k in actuales)} "
          f"de {len(actuales)}.")
    combos = sorted(combinaciones(cfg, estado, hoy) + radares, key=lambda c: c["total"])
    print(f"{len(combos)} combinaciones. Las 5 mas baratas:")
    for c in combos[:5]:
        print(texto_combo(c, cfg, hoy))
    for ciudad in cfg["origenes"]:
        mejor = next((c for c in combos if c["ciudad"] == ciudad), None)
        print(f"Mas barato desde {ciudad}: " + (
            f"{cfg['moneda']} {mejor['por_persona']} p.p. ({mejor['salida']} al "
            f"{mejor['regreso']}, {mejor['dias']} dias)" if mejor
            else "todavia sin combinaciones"))

    if args.mail_prueba:
        guardar_estado(args.estado, dict(estado, **{AVISADOS: avisados}))
        if not combos:
            sys.exit("Todavia no hay combinaciones para el mail de prueba.")
        enviar_mail(combos[:10], set(), cfg, hoy, prueba=True)
        print(f"Mail de prueba enviado a {os.environ['ALERT_TO']}.")
        return

    ofertas = [c for c in combos if c["por_persona"] <= cfg["precio_max_por_persona"]]
    # Nueva: nunca avisada, o mas barata que cuando se aviso.
    nuevas = {id_combo(c) for c in ofertas
              if c["por_persona"] < avisados.get(id_combo(c), float("inf"))}
    print(f"{len(ofertas)} combinacion(es) a {cfg['precio_max_por_persona']:g} o menos "
          f"por persona, {len(nuevas)} nueva(s) o mas barata(s).")
    if nuevas and not args.no_mail:
        enviar_mail(ofertas, nuevas, cfg, hoy)
        print(f"Mail enviado a {os.environ['ALERT_TO']}.")
        avisados.update({id_combo(c): c["por_persona"] for c in ofertas})
    guardar_estado(args.estado, dict(estado, **{AVISADOS: avisados}))


if __name__ == "__main__":
    main()
