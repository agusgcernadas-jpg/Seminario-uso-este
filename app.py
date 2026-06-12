import streamlit as st
import streamlit.components.v1 as components
import plotly.graph_objects as go
import pandas as pd
import math
import io
import json
import requests
from google import genai
from google.genai import types
from datetime import datetime
from streamlit_local_storage import LocalStorage

LS_KEY = "planificador_finanzas_config"

DEFAULT_AHORRO_RATIO = 0.3
RATIO_AHORRO_BAJO = 0.1
RATIO_AHORRO_OBJETIVO = 0.2
OBJ_POR_FILA = 3

CATEGORIAS = ["Fondo de Emergencia", "Educación", "Vivienda", "Vehículo",
              "Viaje/Ocio", "Tecnología", "Salud", "Otro"]
PRIORIDADES = ["Baja", "Media", "Alta"]
PRIO_ORDER = {"Alta": 0, "Media": 1, "Baja": 2}
COLOR_PRIORIDAD = {"Alta": "#E74C3C", "Media": "#F1C40F", "Baja": "#3498DB"}
MONEDAS = ["ARS", "USD", "EUR"]

# Categorías para desglose de gastos. La tabla se renderiza dinámicamente de aquí
# y los indicadores 50/30/20 derivan los totales por tipo.
CATEGORIAS_GASTOS = [
    {"id": "vivienda",      "nombre": "Vivienda (alquiler, expensas, ABL)",                         "tipo": "Necesidad"},
    {"id": "servicios",     "nombre": "Servicios (luz, gas, agua, internet)",                       "tipo": "Necesidad"},
    {"id": "alimentacion",  "nombre": "Alimentación (supermercado)",                                "tipo": "Necesidad"},
    {"id": "transporte",    "nombre": "Transporte (combustible, abono SUBE, mantenimiento)",        "tipo": "Necesidad"},
    {"id": "salud",         "nombre": "Salud (obra social, medicamentos, seguros)",                 "tipo": "Necesidad"},
    {"id": "deudas",        "nombre": "Deudas (cuotas mínimas de créditos / tarjetas)",             "tipo": "Necesidad"},
    {"id": "suscripciones", "nombre": "Suscripciones (Canva, ChatGPT, iCloud, Netflix, Spotify)",   "tipo": "Deseo"},
    {"id": "salidas",       "nombre": "Salidas (restaurantes, bares, delivery)",                    "tipo": "Deseo"},
    {"id": "indumentaria",  "nombre": "Indumentaria (ropa urbana, deportiva)",                      "tipo": "Deseo"},
    {"id": "ocio",          "nombre": "Ocio (cine, hobbies, viajes cortos)",                        "tipo": "Deseo"},
    {"id": "otros",         "nombre": "Otros",                                                      "tipo": "Deseo"},
]

# Pesos del scoring (deben sumar 1.0)
PESO_TOLERANCIA    = 0.35
PESO_CAPACIDAD     = 0.25
PESO_HORIZONTE     = 0.20
PESO_CONOCIMIENTO  = 0.10
PESO_OBJETIVO      = 0.10

OBJETIVOS_FINANCIEROS = [
    "Preservar capital",
    "Generar ingresos pasivos",
    "Compra de vivienda",
    "Jubilación / retiro",
    "Crecimiento patrimonial",
    "Independencia financiera",
    "Viaje / consumo a corto plazo",
]

# Mapa objetivo → ajuste de score (puede restringir recomendaciones)
OBJETIVO_SCORE_AJUSTE = {
    "Preservar capital":          -15,
    "Generar ingresos pasivos":    -5,
    "Compra de vivienda":          -5,
    "Jubilación / retiro":         +5,
    "Crecimiento patrimonial":     +5,
    "Independencia financiera":    +5,
    "Viaje / consumo a corto plazo": -20,
}

# Mapa objetivo → fuerza el plazo máximo permitido para renta variable
OBJETIVO_HORIZONTE_MINIMO = {
    "Compra de vivienda":          None,   # depende del plazo declarado
    "Viaje / consumo a corto plazo": 6,    # máximo 6 meses tolerable
}

# Cada meta usa su propio objetivo en el motor de recomendación,
# en lugar del objetivo general del perfil.
CATEGORIA_A_OBJETIVO = {
    "Fondo de Emergencia":  "Preservar capital",
    "Educación":            "Crecimiento patrimonial",
    "Vivienda":             "Compra de vivienda",
    "Vehículo":             "Preservar capital",
    "Viaje/Ocio":           "Viaje / consumo a corto plazo",
    "Tecnología":           "Preservar capital",
    "Salud":                "Preservar capital",
    "Otro":                 "Crecimiento patrimonial",
}

TOOLTIPS_INSTRUMENTOS = {
    "FCI money market": (
        "Fondo Común de Inversión que invierte en activos de muy corto plazo "
        "(Letras, cauciones). Permite rescatar el dinero en 24-48hs. "
        "Es el equivalente a una caja de ahorro con rendimiento."
    ),
    "FCI renta fija": (
        "Fondo que invierte en bonos y títulos de deuda. "
        "Ofrece rendimiento predecible con baja volatilidad. "
        "Ideal para plazos de 6 a 24 meses."
    ),
    "Bono CER": (
        "Bono del Tesoro argentino ajustado por CER (índice que sigue la inflación). "
        "Protege el capital de la inflación. Similar a los bonos UVA pero emitidos por el Estado."
    ),
    "Plazo fijo UVA": (
        "Depósito a plazo cuyo capital se ajusta por UVA (Unidad de Valor Adquisitivo), "
        "que sigue la inflación. Garantiza rendimiento real positivo con plazo mínimo de 90 días."
    ),
    "CEDEAR": (
        "Certificado de Depósito Argentino que representa acciones extranjeras (Apple, Google, etc.) "
        "cotizando en pesos en la Bolsa argentina. Permite invertir en empresas globales "
        "con cobertura implícita al dólar."
    ),
    "ETF": (
        "Exchange Traded Fund: fondo que cotiza en bolsa y replica un índice (ej: S&P 500). "
        "Permite diversificación instantánea con bajos costos. "
        "Ideal para inversores con conocimiento moderado que no quieren seleccionar acciones individuales."
    ),
    "Cartera Mixta 60/40": (
        "Estrategia clásica: 60% renta fija (bonos, FCI) + 40% renta variable (acciones, ETFs). "
        "Busca equilibrio entre protección y crecimiento. "
        "El 60/40 es el portafolio de referencia de la industria desde hace décadas."
    ),
    "Renta Variable": (
        "Inversión en acciones o instrumentos cuyo rendimiento no está garantizado. "
        "Mayor potencial de ganancia a largo plazo, pero con volatilidad significativa en el corto plazo. "
        "Requiere horizonte de al menos 3-5 años para mitigar el riesgo."
    ),
    "Cuenta remunerada": (
        "Cuenta bancaria o fintech que paga intereses diarios sobre el saldo disponible. "
        "Sin plazo mínimo, liquidez inmediata. "
        "Ejemplos en Argentina: Mercado Pago, Ualá, Naranja X."
    ),
}

# Defaults editables por el usuario. Inflación y rendimiento son nominales anuales en %.
SUPUESTOS_DEFAULT = {
    "ARS": {"inflacion": 80.0, "rendimiento": 90.0},
    "USD": {"inflacion": 3.0, "rendimiento": 5.0},
    "EUR": {"inflacion": 2.5, "rendimiento": 4.0},
}
# ARS por 1 unidad de la moneda. ARS siempre 1.0 (pivote).
TIPOS_CAMBIO_DEFAULT = {"ARS": 1.0, "USD": 1200.0, "EUR": 1300.0}
CASAS_DOLAR = ["oficial", "blue", "bolsa", "contadoconliqui", "cripto", "tarjeta"]

# (umbral_inclusivo, label, emoji, color) — única fuente de verdad para clasificación por risk score.
PERFIL_LEVELS = [
    (20,  "Muy Conservador",  "🔵", "#2196F3"),
    (40,  "Conservador",      "🟢", "#4CAF50"),
    (60,  "Moderado",         "🟡", "#FFC107"),
    (80,  "Moderado Agresivo", "🟠", "#FF9800"),
    (100, "Agresivo",         "🔴", "#F44336"),
]


def clasificar_perfil(score: float) -> tuple[str, str]:
    for umbral, label, emoji, _ in PERFIL_LEVELS:
        if score <= umbral:
            return label, emoji
    return PERFIL_LEVELS[-1][1], PERFIL_LEVELS[-1][2]


def color_perfil(score: float) -> str:
    for umbral, _label, _emoji, color in PERFIL_LEVELS:
        if score <= umbral:
            return color
    return PERFIL_LEVELS[-1][3]


@st.cache_data
def recomendar_instrumento_avanzado(
    risk_score: float,
    plazo_meses: int,
    objetivo: str,
    conocimiento_score: float,
) -> dict:
    """
    Motor de recomendación basado en risk_score, plazo, objetivo y conocimiento.
    """
    # ── Regla 1: plazo urgente ──────────────────────────────────────────────
    if plazo_meses <= 6:
        return {
            "tipo": "Liquidez / Money Market",
            "alternativas": ["Cuenta remunerada", "FCI money market"],
            "descripcion": (
                "Con menos de 6 meses de plazo, la prioridad es la liquidez inmediata. "
                "FCI money market o cuenta remunerada: rescate en 24-48hs, sin riesgo de capital."
            ),
            "emoji": "🟢",
        }

    # ── Regla 2: objetivo de consumo a corto plazo ──────────────────────────
    if objetivo == "Viaje / consumo a corto plazo" and plazo_meses <= 12:
        return {
            "tipo": "Liquidez / Renta Fija Corta",
            "alternativas": ["FCI money market", "Plazo fijo UVA"],
            "descripcion": (
                "Objetivo de consumo próximo. Se prioriza capital garantizado. "
                "Plazo fijo UVA o FCI money market para preservar el valor real."
            ),
            "emoji": "🟢",
        }

    # ── Regla 3: compra de vivienda con horizonte ≤ 18 meses ───────────────
    if objetivo == "Compra de vivienda" and plazo_meses <= 18:
        return {
            "tipo": "Renta Fija / Instrumentos CER-UVA",
            "alternativas": ["Plazo fijo UVA", "Bono CER corto", "FCI renta fija"],
            "descripcion": (
                "Compra de vivienda próxima: no se puede asumir volatilidad. "
                "Instrumentos indexados a inflación (UVA/CER) protegen el poder adquisitivo "
                "sin exponer el capital a caídas de mercado."
            ),
            "emoji": "🟡",
        }

    # ── Clasificación por score + plazo ────────────────────────────────────
    usa_etf = conocimiento_score < 30  # baja literacy → ETFs/FCI sobre acciones

    if risk_score <= 20:
        return {
            "tipo": "Renta Fija / Bonos Cortos",
            "alternativas": ["FCI renta fija", "Plazo fijo UVA", "Letras del Tesoro"],
            "descripcion": (
                "Perfil muy conservador: capital preservado es la prioridad absoluta. "
                "Instrumentos de renta fija con baja duration y emisores de alta calidad."
            ),
            "emoji": "🔵",
        }

    if risk_score <= 40:
        if plazo_meses <= 24:
            return {
                "tipo": "Renta Fija con cobertura inflacionaria",
                "alternativas": ["Bono CER", "FCI renta fija", "Plazo fijo UVA"],
                "descripcion": (
                    "Perfil conservador con horizonte medio. "
                    "Instrumentos indexados a inflación para proteger el poder adquisitivo "
                    "sin asumir volatilidad de renta variable."
                ),
                "emoji": "🟢",
            }
        return {
            "tipo": "Cartera Conservadora 80/20",
            "alternativas": ["FCI renta fija (80%)", "FCI balanceado (20%)", "Bonos soberanos"],
            "descripcion": (
                "80% renta fija diversificada + 20% activos con leve exposición a renta variable. "
                "El horizonte permite absorber volatilidad menor."
            ),
            "emoji": "🟢",
        }

    if risk_score <= 60:
        if plazo_meses <= 12:
            return {
                "tipo": "Renta Fija Diversificada",
                "alternativas": ["FCI renta fija", "Bonos CER", "Letras ajustables"],
                "descripcion": (
                    "Perfil moderado pero horizonte corto: el tiempo no alcanza para "
                    "recuperar caídas de renta variable. Se recomienda renta fija diversificada."
                ),
                "emoji": "🟡",
            }
        instrumento = "ETFs diversificados globales" if usa_etf else "CEDEARs de índices"
        return {
            "tipo": "Cartera Mixta 60/40",
            "alternativas": ["FCI balanceado", instrumento, "Bonos soberanos en USD"],
            "descripcion": (
                "60% renta fija + 40% renta variable. Equilibrio clásico entre estabilidad "
                f"y crecimiento. {'Se priorizan ETFs de índices por bajo conocimiento declarado en acciones individuales.' if usa_etf else 'Con tu nivel de conocimiento podés incorporar CEDEARs selectivos.'}"
            ),
            "emoji": "🟡",
        }

    if risk_score <= 80:
        if plazo_meses < 24:
            return {
                "tipo": "Cartera Mixta 50/50 con sesgo dinámico",
                "alternativas": ["FCI balanceado", "ETFs globales", "Bonos USD"],
                "descripcion": (
                    "Perfil moderado-agresivo pero con horizonte limitado. "
                    "Se modera la exposición a renta variable para evitar cristalizar pérdidas "
                    "si el mercado cae cerca del momento de rescate."
                ),
                "emoji": "🟠",
            }
        instrumento = "ETFs de renta variable (S&P 500, MSCI)" if usa_etf else "Acciones / CEDEARs selectivos"
        return {
            "tipo": "Cartera de Crecimiento 30/70",
            "alternativas": [instrumento, "FCI renta variable", "Bonos HY en USD"],
            "descripcion": (
                "30% renta fija como colchón de liquidez + 70% renta variable. "
                f"{'ETFs diversificados reducen el riesgo idiosincrático sin requerir selección de empresas individuales.' if usa_etf else 'Tu nivel de conocimiento te permite construir una cartera de acciones/CEDEARs con criterio propio.'}"
            ),
            "emoji": "🟠",
        }

    # score > 80: Agresivo
    if plazo_meses < 36:
        instrumento = "ETFs temáticos / sectoriales" if usa_etf else "Acciones locales e internacionales"
        return {
            "tipo": "Renta Variable con diversificación táctica",
            "alternativas": [instrumento, "CEDEARs", "FCI renta variable"],
            "descripcion": (
                "Perfil agresivo con horizonte moderado. Alta exposición a renta variable "
                "con diversificación geográfica y sectorial para mitigar concentración."
            ),
            "emoji": "🔴",
        }
    instrumento_rv = "ETFs de mercados emergentes y desarrollados" if usa_etf else "Acciones + CEDEARs + ETFs globales"
    return {
        "tipo": "Renta Variable / Cartera de Alto Crecimiento",
        "alternativas": [instrumento_rv, "Criptomonedas (fracción)", "REITs / Real assets"],
        "descripcion": (
            "Horizonte largo + perfil agresivo: condiciones ideales para maximizar "
            "rendimiento real. La diversificación geográfica y por clase de activo "
            "es clave. El tiempo juega a favor: las caídas son oportunidades de compra."
        ),
        "emoji": "🔴",
    }


EXPORT_COLUMNS = ["Meta", "Categoría", "Prioridad", "Moneda",
                  "Costo Total", "Costo Futuro Estimado", "Ya Ahorrado",
                  "Plazo (Meses)", "Cuota Ideal", "Monto Asignado",
                  "Estado", "Instrumento Sugerido"]


def convertir(monto, de_moneda, a_moneda, tipos_cambio):
    if de_moneda == a_moneda or monto == 0:
        return monto
    tc_destino = tipos_cambio.get(a_moneda, 0)
    if tc_destino <= 0:
        return monto
    return monto * tipos_cambio[de_moneda] / tc_destino


def _tasa_mensual(tasa_anual_pct):
    return (1 + tasa_anual_pct / 100) ** (1 / 12) - 1


def calcular_cuota_meta(obj, supuestos):
    n = int(obj.get("Plazo (Meses)") or 0)
    moneda = obj.get("Moneda") or "ARS"
    sup = supuestos.get(moneda, SUPUESTOS_DEFAULT[moneda])
    pi_m = _tasa_mensual(sup["inflacion"])
    r_m = _tasa_mensual(sup["rendimiento"])

    costo_presente = float(obj.get("Costo Total") or 0)
    ahorrado_presente = float(obj.get("Ya Ahorrado") or 0)

    costo_futuro = costo_presente * (1 + pi_m) ** n
    ahorrado_futuro = ahorrado_presente * (1 + r_m) ** n
    faltante = max(0.0, costo_futuro - ahorrado_futuro)

    if n <= 0 or faltante == 0:
        cuota_ideal = 0.0
    elif r_m > 1e-9:
        cuota_ideal = faltante * r_m / ((1 + r_m) ** n - 1)
    else:
        cuota_ideal = faltante / n

    return {
        "moneda_meta": moneda,
        "costo_futuro": costo_futuro,
        "ahorrado_futuro": ahorrado_futuro,
        "faltante_futuro": faltante,
        "cuota_ideal": cuota_ideal,
        "r_mensual": r_m,
    }


def meses_para_acumular(faltante_futuro, cuota, r_mensual):
    if cuota <= 0:
        return None
    if r_mensual <= 1e-9:
        return math.ceil(faltante_futuro / cuota)
    base = 1 + faltante_futuro * r_mensual / cuota
    if base <= 0:
        return None
    return math.ceil(math.log(base) / math.log(1 + r_mensual))


def estado_meta(cuota_asignada, cuota_ideal):
    if cuota_asignada >= cuota_ideal and cuota_ideal > 0:
        return "En curso"
    if cuota_asignada > 0:
        return "Parcial"
    return "En espera"


def fmt(monto, codigo):
    # Formato argentino: ARS 1.234.567,89 (puntos para miles, coma para decimal)
    s = f"{monto:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{codigo} {s}"


def _ar_format_pesos(value: float) -> str:
    """1234567.89 → '1.234.567,00' (centavos fijos en 00; tipeás pesos enteros)."""
    pesos_int = int(value)
    return f"{pesos_int:,}".replace(",", ".") + ",00"


def _parse_money_text(text: str) -> float:
    """'1.234.567,00' → 1234567.0  ·  '$10000 ARS' → 10000.0  ·  '' → 0.0"""
    if not text:
        return 0.0
    comma_idx = text.find(",")
    pesos_part = text[:comma_idx] if comma_idx >= 0 else text
    digits = "".join(c for c in pesos_part if c.isdigit())
    return float(int(digits)) if digits else 0.0


def money_input(label: str, key_canonical: str, help: str = None, max_value: float = None) -> float:
    """
    Input de plata con formato AR en tiempo real (vía install_money_format_js).

    Mantiene dos keys en session_state:
    - key_canonical: float canónico (ej. sueldo_valor) — el que serializa a localStorage
    - "_<key_canonical>__text": string formateado del widget (ej. "1.000.000,00")
    - "_<key_canonical>__shadow": último canónico observado, para detectar updates externos
    """
    text_key = f"_{key_canonical}__text"
    shadow_key = f"_{key_canonical}__shadow"

    canonical = float(st.session_state.get(key_canonical, 0.0))
    shadow = float(st.session_state.get(shadow_key, 0.0))

    if text_key not in st.session_state:
        # Primera renderización: inicializamos texto desde el canónico
        st.session_state[text_key] = _ar_format_pesos(canonical) if canonical > 0 else ""
        st.session_state[shadow_key] = canonical
    elif canonical != shadow:
        # El canónico fue updateado externamente (localStorage load, upload de config) →
        # re-sincronizamos el texto desde el canónico
        st.session_state[text_key] = _ar_format_pesos(canonical) if canonical > 0 else ""
        st.session_state[shadow_key] = canonical

    raw = st.text_input(label, key=text_key, help=help, placeholder="0,00")

    new_value = _parse_money_text(raw)
    if max_value is not None and new_value > max_value:
        new_value = float(max_value)

    if st.session_state.get(key_canonical) != new_value:
        st.session_state[key_canonical] = new_value
    st.session_state[shadow_key] = new_value

    return new_value


def install_money_format_js():
    """
    Inyecta JS que escucha keystrokes en inputs con placeholder='0,00' y los
    formatea como pesos argentinos en tiempo real. Llamar una vez por script run.

    Hack: el iframe de components.v1.html con srcdoc es same-origin con el parent,
    así que `window.parent.document` está accesible y podemos modificar los inputs
    de Streamlit directamente. Usa el setter nativo de HTMLInputElement.prototype.value
    para que React/Streamlit registre el cambio.
    """
    from streamlit.components.v1 import html
    html(r"""
    <script>
    (function() {
      const parentWin = window.parent;
      const parentDoc = parentWin.document;

      // Desconectar observer previo (Streamlit re-rendera el iframe en cada run)
      if (parentWin.__moneyObserver) {
        try { parentWin.__moneyObserver.disconnect(); } catch(e) {}
      }

      const nativeSetter = Object.getOwnPropertyDescriptor(
        parentWin.HTMLInputElement.prototype, 'value'
      ).set;

      function setValue(input, value) {
        nativeSetter.call(input, value);
        input.dispatchEvent(new Event('input', { bubbles: true }));
      }

      function formatPesos(pesosInt) {
        return pesosInt.toLocaleString('es-AR') + ',00';
      }

      function attach(input) {
        if (input.dataset.moneyFormatted === '1') return;
        input.dataset.moneyFormatted = '1';

        function refresh(triggeredByUser) {
          const val = input.value;
          const commaIdx = val.indexOf(',');
          const pesosPart = commaIdx >= 0 ? val.substring(0, commaIdx) : val;
          const digits = pesosPart.replace(/\D/g, '');

          if (!digits) {
            if (val !== '' && triggeredByUser) {
              setValue(input, '');
            }
            return;
          }

          const pesos = parseInt(digits, 10);
          if (isNaN(pesos)) return;
          const formatted = formatPesos(pesos);
          if (val !== formatted) {
            setValue(input, formatted);
            // Cursor justo antes de la coma (los centavos quedan locked en ,00)
            const commaPos = formatted.indexOf(',');
            const pos = commaPos > 0 ? commaPos : formatted.length;
            input.setSelectionRange(pos, pos);
          }
        }

        input.addEventListener('input', () => refresh(true));
        input.addEventListener('focus', () => {
          // Si el input está vacío, no hacer nada. Si tiene valor, cursor antes de coma.
          if (input.value) {
            const commaPos = input.value.indexOf(',');
            if (commaPos > 0) {
              setTimeout(() => input.setSelectionRange(commaPos, commaPos), 0);
            }
          }
        });
        // Format inicial (cuando se monta el input con valor pre-existente)
        refresh(false);
      }

      function scan() {
        const inputs = parentDoc.querySelectorAll('input[placeholder="0,00"]');
        inputs.forEach(attach);
      }

      const observer = new MutationObserver(scan);
      observer.observe(parentDoc.body, { childList: true, subtree: true });
      parentWin.__moneyObserver = observer;

      scan();
    })();
    </script>
    """, height=0)


DTYPES_OBJETIVOS = {
    "Costo Total": "float64",
    "Ya Ahorrado": "float64",
    "Plazo (Meses)": "int64",
}

def _normalizar_df(df, moneda_fallback):
    df = df.copy()
    if "Moneda" not in df.columns:
        df["Moneda"] = moneda_fallback
    else:
        df["Moneda"] = df["Moneda"].fillna(moneda_fallback)
    df = df.dropna(subset=["Meta", "Costo Total", "Plazo (Meses)"])
    df = df[df["Meta"].astype(str).str.strip() != ""]
    for col, dt in DTYPES_OBJETIVOS.items():
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=list(DTYPES_OBJETIVOS))
    for col, dt in DTYPES_OBJETIVOS.items():
        if col in df.columns:
            df[col] = df[col].astype(dt)
    return df.reset_index(drop=True)

@st.cache_data
def proyectar_capital(
    ahorrado_presente: float,
    cuota_mensual: float,
    r_mensual: float,
    n_meses: int,
) -> list[float]:
    capital = [ahorrado_presente]
    for _ in range(n_meses):
        siguiente = capital[-1] * (1 + r_mensual) + cuota_mensual
        capital.append(siguiente)
    return capital


def grafico_proyeccion(obj_enriquecido: dict, supuestos: dict) -> go.Figure:
    n = int(obj_enriquecido.get("Plazo (Meses)", 12))
    moneda = obj_enriquecido["moneda_meta"]
    sup = supuestos.get(moneda, SUPUESTOS_DEFAULT[moneda])
    r_m = _tasa_mensual(sup["rendimiento"])
    pi_m = _tasa_mensual(sup["inflacion"])

    capital_ideal = proyectar_capital(
        float(obj_enriquecido.get("Ya Ahorrado", 0)),
        obj_enriquecido["cuota_ideal_meta"],
        r_m, n,
    )
    capital_real = proyectar_capital(
        float(obj_enriquecido.get("Ya Ahorrado", 0)),
        obj_enriquecido["cuota_asignada_meta"],
        r_m, n,
    )
    costo_futuro_mes = [
        float(obj_enriquecido.get("Costo Total", 0)) * (1 + pi_m) ** t
        for t in range(n + 1)
    ]
    meses = list(range(n + 1))

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=meses, y=costo_futuro_mes, name="Costo objetivo (ajustado por inflación)",
        line=dict(color="#E74C3C", dash="dash", width=1.5),
        hovertemplate=f"{moneda} %{{y:,.0f}}<extra>Objetivo</extra>",
    ))
    fig.add_trace(go.Scatter(
        x=meses, y=capital_ideal, name="Capital con cuota ideal",
        line=dict(color="#2ECC71", width=2),
        hovertemplate=f"{moneda} %{{y:,.0f}}<extra>Cuota ideal</extra>",
        fill="tozeroy", fillcolor="rgba(46,204,113,0.08)",
    ))
    if obj_enriquecido["cuota_asignada_meta"] < obj_enriquecido["cuota_ideal_meta"]:
        fig.add_trace(go.Scatter(
            x=meses, y=capital_real, name="Capital con cuota asignada",
            line=dict(color="#F39C12", width=2, dash="dot"),
            hovertemplate=f"{moneda} %{{y:,.0f}}<extra>Cuota asignada</extra>",
        ))
    fig.update_layout(
        height=220,
        margin=dict(t=8, b=8, l=8, r=8),
        legend=dict(orientation="h", y=-0.25, font=dict(size=11, color="#848D97")),
        xaxis_title="Meses",
        yaxis_title=moneda,
        hovermode="x unified",
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#E6EDF3"),
        xaxis=dict(gridcolor="rgba(230,237,243,0.08)", color="#848D97"),
        yaxis=dict(gridcolor="rgba(230,237,243,0.08)", color="#848D97"),
    )
    return fig


@st.cache_data
def calcular_indicadores_salud(
    sueldo: float,
    total_gastos: float,
    ahorro_dispuesto: float,
    fondo_emergencia_meses: float,
    deuda_mensual: float = 0.0,
) -> list[dict]:
    indicadores = []

    ratio_ahorro = ahorro_dispuesto / sueldo if sueldo > 0 else 0
    if ratio_ahorro >= 0.20:
        estado_aho, icono_aho = "ok", "✅"
    elif ratio_ahorro >= 0.10:
        estado_aho, icono_aho = "warning", "⚠️"
    else:
        estado_aho, icono_aho = "error", "🚨"
    indicadores.append({
        "nombre": "Tasa de ahorro",
        "valor": f"{ratio_ahorro:.1%}",
        "estado": estado_aho,
        "icono": icono_aho,
        "descripcion": "Porcentaje del ingreso neto destinado al ahorro/inversión.",
        "benchmark": "≥ 20%",
    })

    if fondo_emergencia_meses >= 6:
        estado_fe, icono_fe = "ok", "✅"
    elif fondo_emergencia_meses >= 3:
        estado_fe, icono_fe = "warning", "⚠️"
    else:
        estado_fe, icono_fe = "error", "🚨"
    indicadores.append({
        "nombre": "Fondo de emergencia",
        "valor": f"{fondo_emergencia_meses:.1f} meses",
        "estado": estado_fe,
        "icono": icono_fe,
        "descripcion": "Meses de gastos cubiertos por el fondo de liquidez disponible.",
        "benchmark": "≥ 6 meses",
    })

    ratio_gastos = total_gastos / sueldo if sueldo > 0 else 0
    if ratio_gastos <= 0.50:
        estado_gf, icono_gf = "ok", "✅"
    elif ratio_gastos <= 0.70:
        estado_gf, icono_gf = "warning", "⚠️"
    else:
        estado_gf, icono_gf = "error", "🚨"
    indicadores.append({
        "nombre": "Gastos fijos / ingresos",
        "valor": f"{ratio_gastos:.1%}",
        "estado": estado_gf,
        "icono": icono_gf,
        "descripcion": "Regla 50/30/20: máximo 50% en necesidades fijas.",
        "benchmark": "≤ 50%",
    })

    ratio_deuda = deuda_mensual / sueldo if sueldo > 0 else 0
    if ratio_deuda <= 0.15:
        estado_deu, icono_deu = "ok", "✅"
    elif ratio_deuda <= 0.30:
        estado_deu, icono_deu = "warning", "⚠️"
    else:
        estado_deu, icono_deu = "error", "🚨"
    indicadores.append({
        "nombre": "Cuotas de deuda / ingresos",
        "valor": f"{ratio_deuda:.1%}",
        "estado": estado_deu,
        "icono": icono_deu,
        "descripcion": "Porcentaje del ingreso comprometido en deudas.",
        "benchmark": "≤ 15%",
    })

    libre = sueldo - total_gastos - deuda_mensual
    ratio_libre = libre / sueldo if sueldo > 0 else 0
    if ratio_libre >= 0.30:
        estado_lib, icono_lib = "ok", "✅"
    elif ratio_libre >= 0.15:
        estado_lib, icono_lib = "warning", "⚠️"
    else:
        estado_lib, icono_lib = "error", "🚨"
    indicadores.append({
        "nombre": "Margen financiero libre",
        "valor": f"{ratio_libre:.1%}",
        "estado": estado_lib,
        "icono": icono_lib,
        "descripcion": "Porcentaje del ingreso libre tras cubrir gastos fijos y deudas.",
        "benchmark": "≥ 30%",
    })

    return indicadores


@st.cache_data(ttl=600, show_spinner=False)
def _generar_reporte_ia(contexto: str, system_prompt: str, model: str = "gemini-2.5-flash") -> str:
    api_key = st.secrets.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("missing_api_key")
    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model=model,
        contents=contexto,
        config=types.GenerateContentConfig(
            system_instruction=system_prompt,
            temperature=0.6,
            max_output_tokens=3000,
            thinking_config=types.ThinkingConfig(thinking_budget=0),
        ),
    )
    return response.text


@st.cache_data(ttl=3600)
def fetch_cotizaciones():
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        r1 = requests.get("https://dolarapi.com/v1/dolares", headers=headers, timeout=5)
        r2 = requests.get("https://dolarapi.com/v1/cotizaciones/eur", headers=headers, timeout=5)
        dolares = r1.json()
        eur = r2.json()
        usd_por_casa = {d.get("casa"): float(d["venta"]) for d in dolares if d.get("venta")}
        return {
            "USD": usd_por_casa,
            "EUR": float(eur.get("venta", 0)) or None,
            "actualizado": dolares[0].get("fechaActualizacion") if dolares else None,
        }
    except requests.exceptions.SSLError:
        return "error_ssl"
    except (requests.RequestException, ValueError, KeyError):
        return None


@st.cache_data
def build_excel(rows, perfil_data: tuple = ()):
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine='xlsxwriter') as writer:
        wb = writer.book

        df_reporte = pd.DataFrame(list(rows), columns=EXPORT_COLUMNS)
        df_reporte.to_excel(writer, index=False, sheet_name="Ruta Crítica")
        ws1 = writer.sheets["Ruta Crítica"]
        hdr_fmt = wb.add_format({'bold': True, 'bg_color': '#1a1a2e', 'font_color': '#FFFFFF', 'border': 1})
        for col_num, col_name in enumerate(EXPORT_COLUMNS):
            ws1.write(0, col_num, col_name, hdr_fmt)
        ws1.set_column(0, len(EXPORT_COLUMNS) - 1, 20)

        if perfil_data:
            (rs, label, objetivo, horizonte, conocimiento,
             s_tolerancia, s_capacidad, s_horizonte, s_conocimiento, s_objetivo) = perfil_data

            titulo_fmt  = wb.add_format({'bold': True, 'font_size': 14, 'bg_color': '#1a1a2e',
                                          'font_color': '#FFFFFF', 'border': 1, 'align': 'center'})
            seccion_fmt = wb.add_format({'bold': True, 'bg_color': '#16213e', 'font_color': '#FFFFFF', 'border': 1})
            label_fmt   = wb.add_format({'bold': True, 'bg_color': '#F5F5F5', 'border': 1})
            valor_fmt   = wb.add_format({'border': 1, 'align': 'right'})
            pct_fmt     = wb.add_format({'border': 1, 'align': 'right', 'num_format': '0.0"%"'})

            ws2 = wb.add_worksheet("Perfil del Inversor")
            ws2.set_column(0, 0, 38)
            ws2.set_column(1, 1, 22)

            ws2.merge_range('A1:B1', '💰 Perfil del Inversor — Ruta Crítica Financiera', titulo_fmt)
            filas_perfil = [
                ("RESULTADO GLOBAL", None),
                ("Risk Score (0–100)", rs),
                ("Clasificación", label),
                ("Objetivo financiero", objetivo),
                ("Horizonte temporal", horizonte),
                ("Conocimiento financiero (score)", conocimiento),
                ("", None),
                ("SCORING POR DIMENSIÓN", None),
                (f"Tolerancia psicológica  (peso {int(PESO_TOLERANCIA*100)}%)", round(s_tolerancia, 1)),
                (f"Capacidad financiera    (peso {int(PESO_CAPACIDAD*100)}%)", round(s_capacidad, 1)),
                (f"Horizonte temporal      (peso {int(PESO_HORIZONTE*100)}%)", round(s_horizonte, 1)),
                (f"Conocimiento financiero (peso {int(PESO_CONOCIMIENTO*100)}%)", round(s_conocimiento, 1)),
                (f"Objetivo financiero     (peso {int(PESO_OBJETIVO*100)}%)", round(s_objetivo, 1)),
            ]
            for i, (k, v) in enumerate(filas_perfil, start=1):
                if v is None:
                    ws2.write(i, 0, k, seccion_fmt)
                    ws2.write(i, 1, "", seccion_fmt)
                else:
                    ws2.write(i, 0, k, label_fmt)
                    fmt = pct_fmt if isinstance(v, float) and k != "Risk Score (0–100)" and "clasificación" not in k.lower() and "objetivo" not in k.lower() and "horizonte" not in k.lower() else valor_fmt
                    ws2.write(i, 1, v, fmt)

    return buf.getvalue()


st.set_page_config(layout="wide", page_title="Cuaderno de Finanzas", page_icon="◐", initial_sidebar_state="collapsed")

install_money_format_js()

components.html("""
<script>
(function() {
  function attach(el) {
    if (el._zeroCleared) return;
    el._zeroCleared = true;
    el.addEventListener('focus', function() {
      if (parseFloat(this.value) === 0) {
        var self = this;
        setTimeout(function() { self.select(); }, 0);
      }
    });
  }
  function scan() {
    try {
      window.parent.document.querySelectorAll('input[type="number"]').forEach(attach);
    } catch(e) {}
  }
  scan();
  try {
    new MutationObserver(scan).observe(
      window.parent.document.body,
      { childList: true, subtree: true }
    );
  } catch(e) {}
})();
</script>
""", height=0)

st.html("""
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
<style>
:root {
  --ink: #E6EDF3;
  --paper: #0D1117;
  --paper-deep: #161B22;
  --accent: #00C896;
  --accent-deep: #00A87E;
  --success: #00C896;
  --warning: #D29922;
  --rule: rgba(230,237,243,0.12);
  --muted: rgba(230,237,243,0.45);
  --whisper: rgba(230,237,243,0.05);
}
.stApp {
  background: var(--paper);
  color: var(--ink);
}
html, body, .stApp, [data-testid="stMarkdownContainer"],
[data-testid="stMarkdownContainer"] p,
[data-testid="stMarkdownContainer"] li,
.stMetric label, label, button, input, select, textarea {
  font-family: 'Inter', system-ui, -apple-system, sans-serif !important;
  color: var(--ink);
}
h1, h2, h3, h4, h5,
[data-testid="stMarkdownContainer"] h1,
[data-testid="stMarkdownContainer"] h2,
[data-testid="stMarkdownContainer"] h3 {
  font-family: 'Inter', system-ui, sans-serif !important;
  color: var(--ink) !important;
  font-weight: 600;
  letter-spacing: -0.02em;
}
h1 { font-size: 2.2rem !important; line-height: 1.1; font-weight: 700 !important; letter-spacing: -0.03em; }
h2 { font-size: 1.5rem !important; font-weight: 600 !important; margin-top: 2rem !important; padding-bottom: 0.5rem; border-bottom: 1px solid var(--rule); }
h3 { font-size: 1.05rem !important; font-weight: 600 !important; letter-spacing: -0.01em; }
.stApp p, .stApp li { line-height: 1.6; }
hr { border: none !important; height: 1px !important; background: var(--rule) !important; margin: 2rem 0 !important; }
.stButton button, .stDownloadButton button, [data-testid="stFormSubmitButton"] button {
  background: var(--paper-deep) !important; color: var(--ink) !important; border: 1px solid var(--rule) !important; border-radius: 6px !important; padding: 0.55rem 1.2rem !important; font-weight: 500 !important; letter-spacing: 0.01em !important; transition: all 0.2s ease !important;
}
.stButton button:hover, .stDownloadButton button:hover, [data-testid="stFormSubmitButton"] button:hover {
  background: var(--accent) !important; color: #0D1117 !important; border-color: var(--accent) !important; transform: translateY(-1px);
}
.stButton button[kind="primary"], [data-testid="stFormSubmitButton"] button {
  background: var(--accent) !important; color: #0D1117 !important; border-color: var(--accent) !important; font-weight: 600 !important;
}
.stButton button[kind="primary"]:hover { background: var(--accent-deep) !important; color: #0D1117 !important; }
[data-testid="stNumberInput"] input, [data-testid="stTextInput"] input, [data-testid="stTextArea"] textarea {
  background: #1E2630 !important;
  border: 1.5px solid rgba(230,237,243,0.22) !important;
  border-radius: 6px !important;
  color: #FFFFFF !important;
  font-weight: 500 !important;
}
[data-testid="stNumberInput"] input:focus, [data-testid="stTextInput"] input:focus, [data-testid="stTextArea"] textarea:focus {
  border-color: var(--accent) !important;
  box-shadow: 0 0 0 3px rgba(0,200,150,0.15) !important;
  color: #FFFFFF !important;
}
[data-testid="stNumberInput"] input::placeholder,
[data-testid="stTextInput"] input::placeholder {
  color: rgba(230,237,243,0.35) !important;
}
[data-baseweb="select"] > div, [data-testid="stSelectbox"] > div { background: var(--paper-deep) !important; border-radius: 6px !important; }
[data-testid="stMetric"] {
  background: var(--paper-deep); padding: 1rem 1.2rem; border-radius: 8px; border: 1px solid var(--rule); border-left: 2px solid var(--accent);
}
[data-testid="stMetricLabel"] { text-transform: uppercase; letter-spacing: 0.1em; font-size: 0.68rem !important; color: var(--muted) !important; }
[data-testid="stMetricValue"] { font-family: 'Inter', sans-serif !important; font-weight: 700 !important; font-size: 1.5rem !important; letter-spacing: -0.02em; color: var(--ink) !important; }
[data-testid="stExpander"] { background: var(--paper-deep) !important; border: 1px solid var(--rule) !important; border-radius: 8px !important; }
[data-testid="stExpander"] summary { font-family: 'Inter', sans-serif !important; font-weight: 500 !important; font-size: 0.95rem !important; }
[data-testid="stAlert"] { border-radius: 6px !important; border-left-width: 3px !important; }
[data-testid="stCaptionContainer"], .stCaption { color: var(--muted) !important; }
[data-baseweb="slider"] [role="slider"] { background: var(--accent) !important; border-color: var(--accent) !important; }
[data-testid="stPlotlyChart"] { background: transparent !important; }
.main > .block-container { animation: fin-fade 0.5s ease; }
@keyframes fin-fade { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: translateY(0); } }
[data-testid="stSidebar"] { background: linear-gradient(180deg, #0D2E6B 0%, #0A2558 55%, #071630 100%) !important; border-right: 1px solid rgba(255,255,255,0.08) !important; }
[data-testid="stSidebar"] h1, [data-testid="stSidebar"] h2, [data-testid="stSidebar"] h3 { color: white !important; border-bottom-color: rgba(255,255,255,0.12) !important; }
[data-testid="stSidebar"] [data-testid="stMarkdownContainer"], [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p { color: rgba(255,255,255,0.88) !important; }
[data-testid="stSidebar"] .stRadio label, [data-testid="stSidebar"] .stCheckbox label, [data-testid="stSidebar"] .stSelectbox label, [data-testid="stSidebar"] .stNumberInput label, [data-testid="stSidebar"] .stTextInput label, [data-testid="stSidebar"] .stToggle label, [data-testid="stSidebar"] .stSlider label, [data-testid="stSidebar"] .stFileUploader label { color: rgba(255,255,255,0.88) !important; }
[data-testid="stSidebar"] [data-testid="stExpander"] { background: rgba(255,255,255,0.06) !important; border: 1px solid rgba(255,255,255,0.1) !important; border-radius: 8px !important; }
[data-testid="stSidebar"] [data-testid="stExpander"] summary { color: rgba(255,255,255,0.92) !important; }
[data-testid="stSidebar"] .stButton button, [data-testid="stSidebar"] .stDownloadButton button { background: rgba(255,255,255,0.1) !important; color: rgba(255,255,255,0.92) !important; border: 1px solid rgba(255,255,255,0.18) !important; }
[data-testid="stSidebar"] .stButton button:hover, [data-testid="stSidebar"] .stDownloadButton button:hover { background: rgba(0,200,150,0.22) !important; border-color: rgba(0,200,150,0.5) !important; color: white !important; transform: none; }
[data-testid="stSidebar"] [data-testid="stNumberInput"] input, [data-testid="stSidebar"] [data-testid="stTextInput"] input { background: rgba(255,255,255,0.08) !important; border-color: rgba(255,255,255,0.15) !important; color: white !important; }
[data-testid="stSidebar"] [data-baseweb="select"] > div { background: rgba(255,255,255,0.08) !important; border-color: rgba(255,255,255,0.15) !important; }
[data-testid="stSidebar"] hr { background: rgba(255,255,255,0.1) !important; }
[data-testid="stSidebar"] [data-testid="stCaptionContainer"], [data-testid="stSidebar"] .stCaption { color: rgba(255,255,255,0.45) !important; }
.stRadio label, .stCheckbox label, .stSelectbox label, .stNumberInput label, .stTextInput label, .stSelectSlider label, .stSlider label, .stDateInput label, .stFileUploader label {
  color: var(--ink) !important; font-weight: 500;
}
[data-testid="stVerticalBlockBorderWrapper"] > div {
  border-color: var(--rule) !important;
  border-radius: 8px !important;
  background: var(--paper-deep) !important;
}

/* ═══ FORMATO MÓVIL ══════════════════════════════════════════════ */
/* Ocultar header visualmente pero NO con display:none para que el hamburger siga vivo */
header[data-testid="stHeader"] {
  background: transparent !important;
  height: 0 !important;
  min-height: 0 !important;
  overflow: visible !important;
  padding: 0 !important;
  pointer-events: none !important;
}
footer, #MainMenu { display: none !important; }
/* ── Hamburger button ─────────────────────────────────────────── */
[data-testid="stSidebarCollapsedControl"] {
  display: flex !important;
  visibility: visible !important;
  opacity: 1 !important;
  pointer-events: all !important;
  position: fixed !important;
  top: 3.2rem !important;
  left: 0.7rem !important;
  z-index: 999999 !important;
  background: #00C896 !important;
  border-radius: 10px !important;
  width: 38px !important;
  height: 38px !important;
  align-items: center !important;
  justify-content: center !important;
  box-shadow: 0 2px 12px rgba(0,200,150,0.5) !important;
}
[data-testid="stSidebarCollapsedControl"] button {
  display: flex !important;
  visibility: visible !important;
  opacity: 1 !important;
  pointer-events: all !important;
  width: 38px !important;
  height: 38px !important;
  align-items: center !important;
  justify-content: center !important;
  background: transparent !important;
  border: none !important;
  color: #0D1117 !important;
  padding: 0 !important;
  cursor: pointer !important;
}
[data-testid="stSidebarCollapsedControl"] button svg {
  fill: #0D1117 !important;
  stroke: #0D1117 !important;
  width: 20px !important;
  height: 20px !important;
  display: block !important;
}

/* ── Quitar línea roja de text inputs ─────────────────────────── */
[data-testid="stTextInput"] input,
[data-testid="stTextInput"] input:focus,
[data-testid="stTextInput"] input:active,
[data-testid="stTextInput"] div[data-baseweb="input"],
[data-testid="stTextInput"] div[data-baseweb="input"]:focus-within {
  border-color: var(--rule) !important;
  box-shadow: none !important;
  outline: none !important;
}
[data-testid="stTextInput"] input:focus {
  border-color: var(--accent) !important;
  box-shadow: 0 0 0 2px rgba(0,200,150,0.15) !important;
}
div[data-baseweb="input"] {
  background: #1E2630 !important;
  border-color: rgba(230,237,243,0.22) !important;
}
div[data-baseweb="input"] input {
  color: #FFFFFF !important;
  font-weight: 500 !important;
}
div[data-baseweb="input"]:focus-within {
  border-color: var(--accent) !important;
  box-shadow: 0 0 0 3px rgba(0,200,150,0.15) !important;
}

.stApp { background: #05070B !important; }

section[data-testid="stMain"] {
  background: var(--paper) !important;
  max-width: 430px !important;
  margin: 0 auto !important;
  min-height: 100dvh !important;
  box-shadow: 0 0 0 1px rgba(230,237,243,0.06), 0 0 80px rgba(0,0,0,0.8) !important;
  border-left: 1px solid rgba(230,237,243,0.07) !important;
  border-right: 1px solid rgba(230,237,243,0.07) !important;
}

.main .block-container {
  max-width: 430px !important;
  padding: 0 0.9rem 2rem !important;
  margin: 0 auto !important;
}

/* ── Main tab bar (inline, between progress and content) ─────── */
[data-testid="stTabs"] [role="tablist"] {
  position: static !important;
  bottom: auto !important; left: auto !important;
  transform: none !important;
  width: calc(100% + 1.8rem) !important;
  margin: 0 -0.9rem 0 !important;
  background: #161B22 !important;
  border-top: none !important;
  border-bottom: 2px solid rgba(230,237,243,0.1) !important;
  border-radius: 0 !important;
  z-index: 100 !important;
  padding: 0 !important;
  justify-content: space-around !important;
  gap: 0 !important;
  box-shadow: none !important;
}

[data-testid="stTabs"] [role="tab"] {
  flex: 1 !important;
  font-size: 0.65rem !important;
  font-weight: 500 !important;
  padding: 0.6rem 0.2rem !important;
  border: none !important;
  border-bottom: 2px solid transparent !important;
  border-top: none !important;
  border-radius: 0 !important;
  letter-spacing: 0 !important;
  line-height: 1.3 !important;
  color: #6E7681 !important;
  background: transparent !important;
  transition: color 0.18s, background 0.18s !important;
  white-space: nowrap !important;
  overflow: hidden !important;
  text-overflow: ellipsis !important;
}

[data-testid="stTabs"] [role="tab"][aria-selected="true"] {
  color: #00C896 !important;
  border-bottom: 2px solid #00C896 !important;
  border-top: none !important;
  background: rgba(0,200,150,0.07) !important;
  font-weight: 700 !important;
}

[data-testid="stTabs"] [role="tab"]:focus-visible { outline: none !important; }
/* Eliminar indicador rojo/default de BaseWeb */
[data-testid="stTabs"] [role="tablist"] > span,
[data-testid="stTabs"] [role="tablist"] > div[role="presentation"],
[data-testid="stTabs"] [role="tablist"] > div:not([role]),
[data-testid="stTabs"] [role="tab"]::after,
[data-testid="stTabs"] [role="tab"]::before { display: none !important; }
[data-testid="stTabs"] [role="tab"] * { text-decoration: none !important; }
/* Forzar que ningún hijo del tab muestre línea roja */
[data-testid="stTabs"] [role="tablist"] > * { background: transparent !important; }
/* Indicador absolutamente posicionado de BaseWeb */
[data-testid="stTabs"] [role="tablist"]::after,
[data-testid="stTabs"] [role="tablist"]::before { display: none !important; }
[data-testid="stTabs"] [role="tablist"] [data-overrides] { display: none !important; }
/* Solo ocultar divs que NO sean tabs (el indicador deslizante) */
[data-testid="stTabs"] [role="tablist"] > div:not([role="tab"]) { display: none !important; }

h2 { font-size: 1.15rem !important; margin-top: 0.8rem !important; padding-bottom: 0.35rem !important; }
h3 { font-size: 0.98rem !important; }
/* ── Radios: base ────────────────────────────────────────────────── */
div[data-testid="stRadio"] > label { display: none !important; }
div[data-testid="stRadio"] { width: 100% !important; }
div[data-testid="element-container"]:has(div[data-testid="stRadio"]) {
  width: 100% !important; margin: 0 !important; padding: 0 !important;
}

/* ── Tab bar: solo cuando hay exactamente 2 opciones (Ingresos/Egresos) */
div[data-testid="stRadio"]:has(> div[role="radiogroup"] > label:first-child:nth-last-child(2)) > div[role="radiogroup"] {
  display: flex !important; flex-direction: row !important; gap: 0 !important;
  border-bottom: 2px solid rgba(230,237,243,0.1) !important;
  margin: 0 0 0.9rem 0 !important; padding: 0 !important; width: 100% !important;
}
div[data-testid="stRadio"]:has(> div[role="radiogroup"] > label:first-child:nth-last-child(2)) > div[role="radiogroup"] > label {
  display: flex !important; flex: 1 1 0 !important; margin: 0 !important;
  justify-content: center !important; align-items: center !important;
  height: 34px !important; padding: 0 !important;
  font-size: 0.62rem !important; font-weight: 600 !important;
  text-transform: uppercase !important; letter-spacing: 0.06em !important;
  color: #6E7681 !important; cursor: pointer !important;
  border-bottom: 2px solid transparent !important; margin-bottom: -2px !important;
  background: transparent !important; white-space: nowrap !important;
  box-sizing: border-box !important; transition: color 0.18s !important;
}
div[data-testid="stRadio"]:has(> div[role="radiogroup"] > label:first-child:nth-last-child(2)) > div[role="radiogroup"] > label:has(input:checked) {
  color: #00C896 !important; border-bottom: 2px solid #00C896 !important;
}
div[data-testid="stRadio"]:has(> div[role="radiogroup"] > label:first-child:nth-last-child(2)) > div[role="radiogroup"] > label > div:first-child { display: none !important; }
div[data-testid="stRadio"]:has(> div[role="radiogroup"] > label:first-child:nth-last-child(2)) > div[role="radiogroup"] > label > div:last-child {
  font-size: 0.62rem !important; color: inherit !important; text-align: center !important;
}

/* ── Cuestionario: 3 o más opciones ─────────────────────────────── */
div[data-testid="stRadio"]:has(> div[role="radiogroup"] > label:nth-child(3)) > div[role="radiogroup"] {
  display: flex !important; flex-direction: column !important;
  gap: 0.45rem !important; margin-bottom: 0.9rem !important;
  padding: 0 !important; width: 100% !important;
}
div[data-testid="stRadio"]:has(> div[role="radiogroup"] > label:nth-child(3)) > div[role="radiogroup"] > label {
  display: flex !important; align-items: flex-start !important;
  padding: 0.65rem 0.75rem !important; width: 100% !important;
  font-size: 0.88rem !important; font-weight: 500 !important; line-height: 1.45 !important;
  color: var(--ink) !important; text-transform: none !important; letter-spacing: 0 !important;
  cursor: pointer !important; box-sizing: border-box !important;
  border: 1.5px solid rgba(230,237,243,0.12) !important; border-radius: 10px !important;
  background: rgba(230,237,243,0.03) !important;
  transition: border-color 0.15s, background 0.15s !important; min-height: 2.8rem !important;
}
div[data-testid="stRadio"]:has(> div[role="radiogroup"] > label:nth-child(3)) > div[role="radiogroup"] > label:has(input:checked) {
  border: 1.5px solid #00C896 !important;
  background: rgba(0,200,150,0.09) !important;
}
div[data-testid="stRadio"]:has(> div[role="radiogroup"] > label:nth-child(3)) [data-testid="stMarkdownContainer"] p {
  font-size: 0.88rem !important; line-height: 1.45 !important;
  color: var(--ink) !important; text-transform: none !important;
}

/* ── Inner tabs (INGRESOS / EGRESOS) — override bottom-nav styles ── */
[data-testid="stTabsContent"] [data-testid="stTabs"] [role="tablist"] {
  position: static !important;
  transform: none !important;
  width: 100% !important;
  left: auto !important; bottom: auto !important;
  background: rgba(255,255,255,0.02) !important;
  border-top: none !important;
  border-bottom: 2px solid rgba(230,237,243,0.1) !important;
  border-radius: 0 !important;
  z-index: auto !important;
  padding: 0 !important;
  box-shadow: none !important;
  justify-content: stretch !important;
  gap: 0 !important;
  margin-bottom: 0.5rem !important;
}
[data-testid="stTabsContent"] [data-testid="stTabs"] [role="tab"] {
  flex: 1 !important;
  font-size: 0.72rem !important;
  font-weight: 700 !important;
  padding: 0.65rem 0.5rem !important;
  border: none !important;
  border-top: none !important;
  border-bottom: 3px solid transparent !important;
  border-radius: 0 !important;
  letter-spacing: 0.08em !important;
  text-transform: uppercase !important;
  color: #6E7681 !important;
  background: transparent !important;
  white-space: nowrap !important;
}
[data-testid="stTabsContent"] [data-testid="stTabs"] [role="tab"][aria-selected="true"] {
  color: #00C896 !important;
  border-bottom: 3px solid #00C896 !important;
  border-top: none !important;
  background: rgba(0,200,150,0.05) !important;
  font-weight: 700 !important;
}
</style>
""")

if st.session_state.get('tema') == 'diurno':
    st.html("""
    <style>
    :root {
      --ink: #0D1117 !important;
      --paper: #FFFFFF !important;
      --paper-deep: #F0F4F8 !important;
      --accent: #00A87E !important;
      --accent-deep: #008B68 !important;
      --rule: rgba(13,17,23,0.12) !important;
      --muted: rgba(13,17,23,0.5) !important;
      --whisper: rgba(13,17,23,0.04) !important;
    }
    .stApp { background: #E8EDF4 !important; }
    section[data-testid="stMain"] { background: #FFFFFF !important; box-shadow: 0 0 0 1px rgba(13,17,23,0.08), 0 0 80px rgba(0,0,0,0.12) !important; }
    [data-testid="stTabs"] [role="tablist"] { background: #F0F4F8 !important; border-bottom: 2px solid rgba(13,17,23,0.1) !important; }
    [data-testid="stTabs"] [role="tab"] { color: rgba(13,17,23,0.45) !important; }
    [data-testid="stTabs"] [role="tab"][aria-selected="true"] { color: #00A87E !important; border-bottom: 2px solid #00A87E !important; background: rgba(0,168,126,0.07) !important; }
    div[data-testid="stRadio"] > div[role="radiogroup"] { border-bottom: 2px solid rgba(13,17,23,0.1) !important; }
    div[data-testid="stRadio"] > div[role="radiogroup"] > label { color: rgba(13,17,23,0.45) !important; }
    div[data-testid="stRadio"] > div[role="radiogroup"] > label:has(input:checked) { color: #00A87E !important; border-bottom: 2px solid #00A87E !important; }
    [data-testid="stNumberInput"] input, [data-testid="stTextInput"] input, [data-testid="stTextArea"] textarea {
      background: #E8EDF4 !important; border: 1.5px solid rgba(13,17,23,0.2) !important; color: #0D1117 !important;
    }
    [data-testid="stNumberInput"] input:focus, [data-testid="stTextInput"] input:focus { border-color: #00A87E !important; }
    div[data-baseweb="input"] { background: #E8EDF4 !important; border-color: rgba(13,17,23,0.2) !important; }
    div[data-baseweb="input"] input { color: #0D1117 !important; }
    div[data-baseweb="input"]:focus-within { border-color: #00A87E !important; }
    [data-baseweb="select"] > div { background: #E8EDF4 !important; border-color: rgba(13,17,23,0.2) !important; color: #0D1117 !important; }
    [data-testid="stExpander"] { background: #F0F4F8 !important; border: 1px solid rgba(13,17,23,0.1) !important; }
    [data-testid="stMetric"] { background: #F0F4F8 !important; border: 1px solid rgba(13,17,23,0.1) !important; border-left: 2px solid #00A87E !important; }
    [data-testid="stMetricValue"] { color: #0D1117 !important; }
    [data-testid="stMetricLabel"] { color: rgba(13,17,23,0.5) !important; }
    .stButton button { background: #F0F4F8 !important; color: #0D1117 !important; border: 1px solid rgba(13,17,23,0.15) !important; }
    .stButton button[kind="primary"], [data-testid="stFormSubmitButton"] button { background: #00A87E !important; color: #FFFFFF !important; border-color: #00A87E !important; }
    h1,h2,h3,h4,h5,h6,p,span,label,div { color: #0D1117; }
    [data-testid="stMarkdownContainer"], [data-testid="stMarkdownContainer"] p { color: #0D1117 !important; }
    [data-baseweb="slider"] [role="slider"] { background: #00A87E !important; border-color: #00A87E !important; }
    /* Ticker */
    .tk-wrap { background: #F0F4F8 !important; border-top: 1px solid rgba(13,17,23,0.08) !important; border-bottom: 1px solid rgba(13,17,23,0.08) !important; }
    .tk-item { color: #0D1117 !important; }
    /* Cards y contenedores genéricos */
    [data-testid="stVerticalBlock"] > div { background: transparent !important; }
    [data-testid="stCaptionContainer"], .stCaption { color: rgba(13,17,23,0.5) !important; }
    [data-testid="stAlert"] { background: #F0F4F8 !important; }
    /* Selectbox dropdown */
    [data-baseweb="popover"] ul, [data-baseweb="menu"] { background: #FFFFFF !important; }
    [data-baseweb="option"] { color: #0D1117 !important; }
    [data-baseweb="option"]:hover { background: #E8EDF4 !important; }
    /* Tabs del sidebar / inner */
    [data-testid="stTabsContent"] [data-testid="stTabs"] [role="tablist"] { background: #F0F4F8 !important; }
    [data-testid="stTabsContent"] [data-testid="stTabs"] [role="tab"] { color: rgba(13,17,23,0.45) !important; }
    [data-testid="stTabsContent"] [data-testid="stTabs"] [role="tab"][aria-selected="true"] { color: #00A87E !important; border-bottom-color: #00A87E !important; }
    /* Iconos de categorías en egresos: texto */
    p, span, div { color: inherit; }
    </style>
    """)


_MESES_ES = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
             "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]

if 'objetivos' not in st.session_state:
    st.session_state.objetivos = []
if 'supuestos' not in st.session_state:
    st.session_state.supuestos = {m: dict(v) for m, v in SUPUESTOS_DEFAULT.items()}
if 'tc_USD' not in st.session_state:
    st.session_state.tc_USD = TIPOS_CAMBIO_DEFAULT["USD"]
if 'tc_EUR' not in st.session_state:
    st.session_state.tc_EUR = TIPOS_CAMBIO_DEFAULT["EUR"]
if 'tc_actualizado' not in st.session_state:
    st.session_state.tc_actualizado = None
if 'fx_msg' not in st.session_state:
    st.session_state.fx_msg = None
if 'config_msg' not in st.session_state:
    st.session_state.config_msg = None
if 'perfil_completo' not in st.session_state:
    st.session_state.perfil_completo = False
if 'risk_score' not in st.session_state:
    st.session_state.risk_score = 50.0
if 'objetivo_financiero' not in st.session_state:
    st.session_state.objetivo_financiero = "Crecimiento patrimonial"
if 'horizonte_perfil' not in st.session_state:
    st.session_state.horizonte_perfil = "3 a 5 años"
if 'conocimiento_score' not in st.session_state:
    st.session_state.conocimiento_score = 50.0
for _k, _v in [('score_tolerancia', 50.0), ('score_capacidad', 50.0),
               ('score_horizonte', 50.0), ('score_conocimiento', 50.0), ('score_objetivo', 50.0)]:
    if _k not in st.session_state:
        st.session_state[_k] = _v

if 'splash_shown' not in st.session_state:
    st.session_state.splash_shown = False
if 'situacion_desbloqueada' not in st.session_state:
    st.session_state.situacion_desbloqueada = False
if '_scroll_resultados' not in st.session_state:
    st.session_state._scroll_resultados = False
if 'tema' not in st.session_state:
    st.session_state.tema = 'nocturno'

# Estado compartido entre tabs
for _k, _v in [
    ("moneda_ingreso", "ARS"),
    ("sueldo_valor", 0.0),
    ("gastos_valor", 0.0),
    ("ahorro_dispuesto_valor", 0.0),
    ("fondo_emerg_valor", 0.0),
    ("moneda_fondo_emerg", "ARS"),
    ("deuda_mensual_valor", 0.0),
    ("objetivos_enriquecidos", []),
]:
    if _k not in st.session_state:
        st.session_state[_k] = _v


def serializar_config():
    payload = {
        "version": 3,
        "objetivos": st.session_state.objetivos,
        "supuestos": st.session_state.supuestos,
        "tc_USD": float(st.session_state.tc_USD),
        "tc_EUR": float(st.session_state.tc_EUR),
        "gastos_por_categoria": {
            c["id"]: float(st.session_state.get(f"gasto_{c['id']}", 0.0))
            for c in CATEGORIAS_GASTOS
        },
        "situacion": {
            "moneda_ingreso": st.session_state.get("moneda_ingreso", "ARS"),
            "sueldo_valor": float(st.session_state.get("sueldo_valor", 0.0)),
            "fondo_emerg_valor": float(st.session_state.get("fondo_emerg_valor", 0.0)),
            "moneda_fondo_emerg": st.session_state.get("moneda_fondo_emerg", "ARS"),
            "ahorro_dispuesto_valor": float(st.session_state.get("ahorro_dispuesto_valor", 0.0)),
        },
    }
    return json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8")


def _aplicar_config(config: dict) -> int:
    if isinstance(config.get("objetivos"), list):
        st.session_state.objetivos = config["objetivos"]
    if isinstance(config.get("supuestos"), dict):
        for m, vals in config["supuestos"].items():
            if m in MONEDAS and isinstance(vals, dict):
                if "inflacion" in vals:
                    val = float(vals["inflacion"])
                    st.session_state.supuestos[m]["inflacion"] = val
                    st.session_state[f"infl_{m}"] = val
                if "rendimiento" in vals:
                    val = float(vals["rendimiento"])
                    st.session_state.supuestos[m]["rendimiento"] = val
                    st.session_state[f"rend_{m}"] = val
    if "tc_USD" in config:
        st.session_state.tc_USD = float(config["tc_USD"])
    if "tc_EUR" in config:
        st.session_state.tc_EUR = float(config["tc_EUR"])
    if isinstance(config.get("gastos_por_categoria"), dict):
        for c in CATEGORIAS_GASTOS:
            if c["id"] in config["gastos_por_categoria"]:
                try:
                    st.session_state[f"gasto_{c['id']}"] = float(config["gastos_por_categoria"][c["id"]])
                except (TypeError, ValueError):
                    pass
    if isinstance(config.get("situacion"), dict):
        sit = config["situacion"]
        if sit.get("moneda_ingreso") in MONEDAS:
            st.session_state.moneda_ingreso = sit["moneda_ingreso"]
        if sit.get("moneda_fondo_emerg") in MONEDAS:
            st.session_state.moneda_fondo_emerg = sit["moneda_fondo_emerg"]
        for k in ("sueldo_valor", "fondo_emerg_valor", "ahorro_dispuesto_valor"):
            if k in sit:
                try:
                    st.session_state[k] = float(sit[k])
                except (TypeError, ValueError):
                    pass
    return len(st.session_state.objetivos)


def cargar_config_callback():
    uploaded = st.session_state.get("config_upload")
    if uploaded is None:
        return
    try:
        config = json.loads(uploaded.getvalue())
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        st.session_state.config_msg = ("error", f"Archivo inválido: {e}")
        return
    if not isinstance(config, dict):
        st.session_state.config_msg = ("error", "Formato JSON inválido (se esperaba un objeto).")
        return
    cnt = _aplicar_config(config)
    st.session_state.config_msg = (
        "success",
        f"Configuración cargada: {cnt} objetivo{'s' if cnt != 1 else ''}.",
    )


def actualizar_cotizaciones_callback():
    data = fetch_cotizaciones()
    if data == "error_ssl":
        st.session_state.fx_msg = ("warning",
            "Error de certificado SSL al contactar dolarapi.com. "
            "Revisá tus certificados del sistema o ingresá los valores manualmente.")
        return
    if data is None:
        st.session_state.fx_msg = ("warning",
            "No se pudo conectar a dolarapi.com. Se mantienen los valores manuales.")
        return
    casa = st.session_state.get("casa_dolar", "bolsa")
    usd = data["USD"].get(casa)
    if usd:
        st.session_state.tc_USD = float(usd)
    if data.get("EUR"):
        st.session_state.tc_EUR = float(data["EUR"])
    st.session_state.tc_actualizado = data.get("actualizado")
    st.session_state.fx_msg = ("success", f"Cotizaciones actualizadas ({casa}).")


def borrar_localstorage_callback():
    _ls.deleteItem(LS_KEY)
    st.session_state._ls_disabled = True
    st.session_state.pop("_ls_last_saved", None)
    st.session_state.pop("_ls_last_loaded", None)
    st.session_state.config_msg = (
        "info",
        "Datos del navegador borrados. El autosave queda pausado en esta sesión.",
    )


_ls = LocalStorage()
_ls_saved = _ls.getItem(LS_KEY)
if _ls_saved and _ls_saved != st.session_state.get("_ls_last_loaded"):
    try:
        _aplicar_config(json.loads(_ls_saved))
        st.session_state._ls_last_loaded = _ls_saved
        st.session_state._ls_last_saved = _ls_saved
    except (json.JSONDecodeError, TypeError, ValueError):
        pass


# ── Splash Screen ──────────────────────────────────────────────────────────
if not st.session_state.get("splash_shown", False) and st.session_state.get("onboarding_step", 0) == 0:
    st.html("""
    <style>
      @keyframes sp-fade { from { opacity:0; transform:translateY(18px); } to { opacity:1; transform:translateY(0); } }
      .sp1 { animation: sp-fade 0.7s ease forwards; }
      .sp2 { animation: sp-fade 0.7s ease 0.18s forwards; opacity:0; }
      .sp3 { animation: sp-fade 0.7s ease 0.36s forwards; opacity:0; }
      .sp4 { animation: sp-fade 0.7s ease 0.54s forwards; opacity:0; }
      .sp5 { animation: sp-fade 0.7s ease 0.72s forwards; opacity:0; }
      [data-testid="stSidebar"]  { display:none !important; }
      [data-testid="stHeader"]   { display:none !important; }
      footer                     { display:none !important; }
      .main .block-container     { padding-top:0 !important; max-width:680px !important; }
      .stApp {
        background: linear-gradient(160deg, #071630 0%, #0D2D6B 45%, #0A3D8F 100%) !important;
      }
    </style>

    <div style="width:100%;padding:4rem 1.5rem 1rem;box-sizing:border-box;text-align:center;font-family:'Inter',sans-serif;position:relative;overflow:hidden;">

      <!-- Círculos decorativos de fondo -->
      <div style="position:absolute;top:-60px;right:-60px;width:300px;height:300px;border-radius:50%;background:rgba(255,255,255,0.04);pointer-events:none;"></div>
      <div style="position:absolute;bottom:-80px;left:-80px;width:380px;height:380px;border-radius:50%;background:rgba(255,255,255,0.03);pointer-events:none;"></div>
      <div style="position:absolute;top:40%;right:-30px;width:160px;height:160px;border-radius:50%;background:rgba(0,200,150,0.06);pointer-events:none;"></div>

      <!-- Logo -->
      <div class="sp1" style="margin-bottom:1.8rem;">
        <svg width="92" height="92" viewBox="0 0 92 92" fill="none" xmlns="http://www.w3.org/2000/svg"
             style="filter:drop-shadow(0 8px 28px rgba(0,200,150,0.35));">
          <circle cx="46" cy="46" r="46" fill="rgba(255,255,255,0.09)"/>
          <circle cx="46" cy="46" r="38" fill="rgba(255,255,255,0.06)"/>
          <!-- Barras del gráfico -->
          <rect x="18" y="57" width="9" height="18" rx="2" fill="#00C896" opacity="0.5"/>
          <rect x="31" y="47" width="9" height="28" rx="2" fill="#00C896" opacity="0.65"/>
          <rect x="44" y="35" width="9" height="40" rx="2" fill="#00C896" opacity="0.82"/>
          <rect x="57" y="22" width="9" height="53" rx="2" fill="#00C896"/>
          <!-- Línea de tendencia -->
          <polyline points="21,55 34,45 48,32 62,19"
                    stroke="white" stroke-width="2.5" fill="none"
                    stroke-linecap="round" stroke-linejoin="round" opacity="0.92"/>
          <circle cx="62" cy="19" r="3.5" fill="white"/>
          <!-- Puntos IA -->
          <circle cx="76" cy="32" r="2.5" fill="#00C896" opacity="0.9"/>
          <circle cx="76" cy="40" r="2"   fill="#00C896" opacity="0.55"/>
          <circle cx="76" cy="47" r="1.5" fill="#00C896" opacity="0.3"/>
        </svg>
      </div>

      <!-- Nombre -->
      <div class="sp2" style="font-size:3.4rem;font-weight:700;color:#FFFFFF;letter-spacing:-0.045em;line-height:1;margin-bottom:0.55rem;">
        FINANC<span style="color:#00C896;">-AI</span>
      </div>

      <!-- Tagline -->
      <div class="sp3" style="font-size:0.95rem;color:rgba(255,255,255,0.55);font-weight:400;margin-bottom:3.2rem;line-height:1.55;max-width:320px;margin-left:auto;margin-right:auto;">
        Tu planificador financiero personal<br>con inteligencia artificial
      </div>

      <!-- Gráfico de crecimiento -->
      <div class="sp3" style="width:100%;max-width:420px;margin:0 auto 2.8rem auto;">
        <svg width="100%" viewBox="0 0 420 100" fill="none" xmlns="http://www.w3.org/2000/svg">
          <!-- Grilla -->
          <line x1="0" y1="85" x2="420" y2="85" stroke="rgba(255,255,255,0.08)" stroke-width="1"/>
          <line x1="0" y1="57" x2="420" y2="57" stroke="rgba(255,255,255,0.08)" stroke-width="1"/>
          <line x1="0" y1="29" x2="420" y2="29" stroke="rgba(255,255,255,0.08)" stroke-width="1"/>
          <!-- Área rellena -->
          <path d="M0,82 C40,78 70,72 110,64 C150,56 175,50 210,40 C245,30 280,20 315,13 L420,7 L420,85 Z"
                fill="rgba(0,200,150,0.13)"/>
          <!-- Línea principal -->
          <path d="M0,82 C40,78 70,72 110,64 C150,56 175,50 210,40 C245,30 280,20 315,13 L420,7"
                stroke="#00C896" stroke-width="2.5" fill="none" stroke-linecap="round"/>
          <!-- Puntos destacados -->
          <circle cx="420" cy="7"   r="4.5" fill="#00C896"/>
          <circle cx="210" cy="40"  r="3"   fill="#00C896" opacity="0.7"/>
          <circle cx="110" cy="64"  r="3"   fill="#00C896" opacity="0.5"/>
          <!-- Etiquetas de meses -->
          <text x="0"   y="98" font-family="Inter,sans-serif" font-size="9" fill="rgba(255,255,255,0.3)">Ene</text>
          <text x="98"  y="98" font-family="Inter,sans-serif" font-size="9" fill="rgba(255,255,255,0.3)">Mar</text>
          <text x="198" y="98" font-family="Inter,sans-serif" font-size="9" fill="rgba(255,255,255,0.3)">Jun</text>
          <text x="300" y="98" font-family="Inter,sans-serif" font-size="9" fill="rgba(255,255,255,0.3)">Sep</text>
          <text x="400" y="98" font-family="Inter,sans-serif" font-size="9" fill="rgba(255,255,255,0.3)">Dic</text>
        </svg>
      </div>

      <!-- Stats pill -->
      <div class="sp4" style="display:inline-flex;gap:2.2rem;padding:1rem 2.2rem;
                               background:rgba(255,255,255,0.07);border-radius:14px;
                               border:1px solid rgba(255,255,255,0.1);margin-bottom:2.8rem;
                               flex-wrap:wrap;justify-content:center;">
        <div style="text-align:center;">
          <div style="font-size:1.35rem;font-weight:700;color:#00C896;">4</div>
          <div style="font-size:0.65rem;color:rgba(255,255,255,0.45);text-transform:uppercase;letter-spacing:0.13em;margin-top:2px;">Módulos</div>
        </div>
        <div style="width:1px;background:rgba(255,255,255,0.12);"></div>
        <div style="text-align:center;">
          <div style="font-size:1.35rem;font-weight:700;color:#00C896;">IA</div>
          <div style="font-size:0.65rem;color:rgba(255,255,255,0.45);text-transform:uppercase;letter-spacing:0.13em;margin-top:2px;">Análisis</div>
        </div>
        <div style="width:1px;background:rgba(255,255,255,0.12);"></div>
        <div style="text-align:center;">
          <div style="font-size:1.35rem;font-weight:700;color:#00C896;">∞</div>
          <div style="font-size:0.65rem;color:rgba(255,255,255,0.45);text-transform:uppercase;letter-spacing:0.13em;margin-top:2px;">Metas</div>
        </div>
        <div style="width:1px;background:rgba(255,255,255,0.12);"></div>
        <div style="text-align:center;">
          <div style="font-size:1.35rem;font-weight:700;color:#00C896;">ARS</div>
          <div style="font-size:0.65rem;color:rgba(255,255,255,0.45);text-transform:uppercase;letter-spacing:0.13em;margin-top:2px;">Multidivisa</div>
        </div>
      </div>

    </div>
    """)

    _sc1, _sc2, _sc3 = st.columns([1, 2, 1])
    with _sc2:
        if st.button("Siguiente →", type="primary", use_container_width=True, key="btn_splash"):
            st.session_state.onboarding_step = 1
            st.rerun()
    st.stop()

elif not st.session_state.get("splash_shown", False):
    _step = st.session_state.get("onboarding_step", 0)

    # CSS compartido para pantallas de onboarding
    st.html("""
    <style>
      @keyframes ob-fade { from { opacity:0; transform:translateY(22px); } to { opacity:1; transform:translateY(0); } }
      .ob1 { animation: ob-fade 0.65s ease forwards; }
      .ob2 { animation: ob-fade 0.65s ease 0.15s forwards; opacity:0; }
      .ob3 { animation: ob-fade 0.65s ease 0.30s forwards; opacity:0; }
      .ob4 { animation: ob-fade 0.65s ease 0.45s forwards; opacity:0; }
      [data-testid="stSidebar"] { display:none !important; }
      [data-testid="stHeader"]  { display:none !important; }
      footer                    { display:none !important; }
      .main .block-container    { padding-top:0 !important; max-width:620px !important; }
      .stApp { background: linear-gradient(160deg, #071630 0%, #0D2D6B 45%, #0A3D8F 100%) !important; }
    </style>
    """)

    # ── Pantalla 1: Metas ──────────────────────────────────────────────────
    if _step == 1:
        st.html("""
        <div style="width:100%;padding:5rem 1.5rem 1.5rem;box-sizing:border-box;
                    text-align:center;font-family:'Inter',sans-serif;">

          <!-- Indicador de progreso -->
          <div class="ob1" style="display:flex;gap:6px;justify-content:center;margin-bottom:4rem;">
            <div style="width:28px;height:4px;border-radius:2px;background:#00C896;"></div>
            <div style="width:10px;height:4px;border-radius:2px;background:rgba(255,255,255,0.22);"></div>
            <div style="width:10px;height:4px;border-radius:2px;background:rgba(255,255,255,0.22);"></div>
          </div>

          <!-- Ícono: objetivo/blanco -->
          <div class="ob1" style="margin-bottom:2.4rem;">
            <svg width="76" height="76" viewBox="0 0 76 76" fill="none"
                 style="filter:drop-shadow(0 6px 20px rgba(0,200,150,0.3));">
              <circle cx="38" cy="38" r="30" stroke="rgba(0,200,150,0.22)" stroke-width="2" stroke-dasharray="5 5"/>
              <circle cx="38" cy="38" r="21" stroke="rgba(0,200,150,0.5)" stroke-width="2"/>
              <circle cx="38" cy="38" r="12" stroke="#00C896" stroke-width="2.5"/>
              <circle cx="38" cy="38" r="5"  fill="#00C896"/>
              <line x1="62" y1="14" x2="44" y2="32"
                    stroke="white" stroke-width="2.5" stroke-linecap="round"/>
              <polyline points="55,14 62,14 62,21"
                        stroke="white" stroke-width="2.5"
                        stroke-linecap="round" stroke-linejoin="round" fill="none"/>
            </svg>
          </div>

          <!-- Título -->
          <div class="ob2" style="font-size:2rem;font-weight:700;color:white;
                                   line-height:1.2;letter-spacing:-0.03em;
                                   max-width:360px;margin:0 auto 1.4rem auto;">
            ¿Tenés metas pero no sabés cómo llegar a ellas?
          </div>

          <!-- Subtítulo -->
          <div class="ob3" style="font-size:0.95rem;color:rgba(255,255,255,0.52);
                                   line-height:1.65;max-width:310px;margin:0 auto;">
            La casa propia, un viaje, el retiro… Sabés a dónde
            querés ir, pero no cuánto ahorrar ni en qué plazo.
          </div>

        </div>
        """)
        _c1, _c2, _c3 = st.columns([1, 2, 1])
        with _c2:
            if st.button("Siguiente →", type="primary", use_container_width=True, key="btn_ob1"):
                st.session_state.onboarding_step = 2
                st.rerun()

    # ── Pantalla 2: Inflación ──────────────────────────────────────────────
    elif _step == 2:
        st.html("""
        <div style="width:100%;padding:5rem 1.5rem 1.5rem;box-sizing:border-box;
                    text-align:center;font-family:'Inter',sans-serif;">

          <!-- Indicador de progreso -->
          <div class="ob1" style="display:flex;gap:6px;justify-content:center;margin-bottom:4rem;">
            <div style="width:10px;height:4px;border-radius:2px;background:#00C896;"></div>
            <div style="width:28px;height:4px;border-radius:2px;background:#00C896;"></div>
            <div style="width:10px;height:4px;border-radius:2px;background:rgba(255,255,255,0.22);"></div>
          </div>

          <!-- Ícono: tendencia bajista -->
          <div class="ob1" style="margin-bottom:2.4rem;">
            <svg width="76" height="76" viewBox="0 0 76 76" fill="none"
                 style="filter:drop-shadow(0 6px 20px rgba(248,81,73,0.25));">
              <circle cx="38" cy="38" r="32" fill="rgba(248,81,73,0.08)"
                      stroke="rgba(248,81,73,0.3)" stroke-width="1.5"/>
              <path d="M14,24 L26,32 L40,27 L62,48"
                    stroke="#F85149" stroke-width="2.5" fill="none"
                    stroke-linecap="round" stroke-linejoin="round"/>
              <circle cx="62" cy="48" r="3.5" fill="#F85149"/>
              <path d="M54,48 L62,48 L62,56"
                    stroke="#F85149" stroke-width="2.5"
                    stroke-linecap="round" stroke-linejoin="round" fill="none"/>
              <text x="24" y="62" font-family="Inter,sans-serif" font-size="13"
                    font-weight="700" fill="rgba(255,255,255,0.4)">$</text>
              <text x="36" y="62" font-family="Inter,sans-serif" font-size="11"
                    fill="rgba(248,81,73,0.65)">→ ∅</text>
            </svg>
          </div>

          <!-- Título -->
          <div class="ob2" style="font-size:2rem;font-weight:700;color:white;
                                   line-height:1.2;letter-spacing:-0.03em;
                                   max-width:360px;margin:0 auto 1.4rem auto;">
            Ahorrar sin estrategia, en Argentina, es perder
          </div>

          <!-- Subtítulo -->
          <div class="ob3" style="font-size:0.95rem;color:rgba(255,255,255,0.52);
                                   line-height:1.65;max-width:320px;margin:0 auto;">
            Dejar tus pesos quietos puede costarte hasta el 90%
            de tu poder de compra. Cada peso importa y el tiempo
            no espera.
          </div>

        </div>
        """)
        _c1, _c2, _c3 = st.columns([1, 2, 1])
        with _c2:
            if st.button("Siguiente →", type="primary", use_container_width=True, key="btn_ob2"):
                st.session_state.onboarding_step = 3
                st.rerun()

    # ── Pantalla 3: Solución ───────────────────────────────────────────────
    elif _step == 3:
        st.html("""
        <div style="width:100%;padding:5rem 1.5rem 1.5rem;box-sizing:border-box;
                    text-align:center;font-family:'Inter',sans-serif;">

          <!-- Indicador de progreso -->
          <div class="ob1" style="display:flex;gap:6px;justify-content:center;margin-bottom:4rem;">
            <div style="width:10px;height:4px;border-radius:2px;background:#00C896;"></div>
            <div style="width:10px;height:4px;border-radius:2px;background:#00C896;"></div>
            <div style="width:28px;height:4px;border-radius:2px;background:#00C896;"></div>
          </div>

          <!-- Ícono: check / solución -->
          <div class="ob1" style="margin-bottom:2.4rem;">
            <svg width="76" height="76" viewBox="0 0 76 76" fill="none"
                 style="filter:drop-shadow(0 6px 24px rgba(0,200,150,0.35));">
              <circle cx="38" cy="38" r="32" fill="rgba(0,200,150,0.12)"
                      stroke="#00C896" stroke-width="2"/>
              <polyline points="20,38 31,49 56,25"
                        stroke="#00C896" stroke-width="3.5" fill="none"
                        stroke-linecap="round" stroke-linejoin="round"/>
            </svg>
          </div>

          <!-- Título -->
          <div class="ob2" style="font-size:2rem;font-weight:700;color:white;
                                   line-height:1.2;letter-spacing:-0.03em;
                                   max-width:360px;margin:0 auto 1.4rem auto;">
            Tu plan financiero, a tu medida y gratis
          </div>

          <!-- Subtítulo -->
          <div class="ob3" style="font-size:0.95rem;color:rgba(255,255,255,0.52);
                                   line-height:1.65;max-width:320px;margin:0 auto 0 auto;">
            Conocé tu perfil, ordená tus metas y recibí instrumentos
            concretos para cada objetivo. Sin costo, sin vueltas.
          </div>

        </div>
        """)
        _c1, _c2, _c3 = st.columns([1, 2, 1])
        with _c2:
            if st.button("Empezar", type="primary", use_container_width=True, key="btn_ob3"):
                st.session_state.splash_shown = True
                st.rerun()

    st.stop()


def cols_or_stack(weights, gap="medium"):
    """Siempre apila verticalmente (formato móvil)."""
    return [st.container() for _ in range(len(weights))]


# ── Sidebar ──────────────────────────────────────────────────────────────
with st.sidebar:
    # Perfil header
    _sb_sueldo = float(st.session_state.get("sueldo_valor", 0.0))
    _sb_moneda = st.session_state.get("moneda_ingreso", "ARS")
    _sb_balance = fmt(_sb_sueldo, _sb_moneda) if _sb_sueldo > 0 else "Sin ingreso cargado"
    st.html(f"""
    <div style="padding:1.4rem 0.4rem 1.2rem 0.4rem; margin-bottom:0.4rem;
                border-bottom:1px solid rgba(255,255,255,0.12);">
      <div style="display:flex; align-items:center; gap:0.85rem;">
        <div style="width:46px; height:46px; border-radius:50%;
                    background:rgba(0,200,150,0.18); border:2px solid #00C896;
                    display:flex; align-items:center; justify-content:center;
                    font-family:'Inter',sans-serif; font-size:1.15rem; font-weight:700;
                    color:#00C896; flex-shrink:0; letter-spacing:-0.02em;">
          F
        </div>
        <div>
          <div style="font-family:'Inter',sans-serif; font-size:0.92rem; font-weight:700;
                      color:white; line-height:1.2; letter-spacing:-0.01em;">
            FINANC<span style="color:#00C896;">-AI</span>
          </div>
          <div style="font-family:'Inter',sans-serif; font-size:0.71rem;
                      color:rgba(255,255,255,0.5); margin-top:3px;">
            Balance: {_sb_balance}
          </div>
        </div>
      </div>
    </div>
    """)

    st.header("⚙️ Configuración")
    _es_nocturno = st.session_state.tema == 'nocturno'
    if st.button(
        "☀️  Cambiar a modo día" if _es_nocturno else "🌙  Cambiar a modo noche",
        key="_toggle_tema", use_container_width=True
    ):
        st.session_state.tema = 'diurno' if _es_nocturno else 'nocturno'
        st.rerun()
    st.divider()
    st.toggle(
        "📱 Modo compacto",
        key="modo_compacto",
        help="Apila las columnas verticalmente. Activalo si estás en mobile.",
    )
    
    with st.expander("Supuestos macro", expanded=False):

        st.markdown("**📉 Inflación anual estimada**")
        st.caption("Cuánto aumentan los precios por año en cada moneda. Se usa para calcular el costo futuro de tus metas.")
        st.session_state.supuestos["ARS"]["inflacion"] = st.number_input(
            "Inflación % (Pesos argentinos)",
            value=float(st.session_state.supuestos["ARS"]["inflacion"]),
            step=0.5, key="infl_ARS",
        )
        st.session_state.supuestos["USD"]["inflacion"] = st.number_input(
            "Inflación % (Dólares)",
            value=float(st.session_state.supuestos["USD"]["inflacion"]),
            step=0.5, key="infl_USD",
        )

        st.divider()
        st.markdown("**📈 Tasas de rendimiento anual por perfil (%)**")
        st.caption("Podés modificarlas para ver cómo cambian los tiempos en cada meta.")

        _tasas_default = {
            "Muy Conservador":   {"default": 80.0},
            "Conservador":       {"default": 90.0},
            "Moderado":          {"default": 110.0},
            "Moderado Agresivo": {"default": 140.0},
            "Agresivo":          {"default": 180.0},
        }
        if "tasas_por_perfil" not in st.session_state:
            st.session_state.tasas_por_perfil = {k: v["default"] for k, v in _tasas_default.items()}

        for perfil_key, info in _tasas_default.items():
            st.session_state.tasas_por_perfil[perfil_key] = st.number_input(
                perfil_key,
                value=float(st.session_state.tasas_por_perfil.get(perfil_key, info["default"])),
                min_value=0.0, max_value=500.0, step=5.0,
                key=f"tasa_perfil_{perfil_key}",
            )

        # Mantener rendimiento en supuestos para compatibilidad con cálculos existentes
        _perfil_actual = clasificar_perfil(st.session_state.risk_score)[0]
        _tasa_actual = st.session_state.tasas_por_perfil.get(_perfil_actual, 90.0)
        st.session_state.supuestos["ARS"]["rendimiento"] = _tasa_actual
        st.session_state.supuestos["EUR"]["inflacion"] = float(st.session_state.supuestos["EUR"]["inflacion"])
        st.session_state.supuestos["EUR"]["rendimiento"] = float(st.session_state.supuestos["EUR"]["rendimiento"])

    with st.expander("Tipos de cambio", expanded=False):
        st.number_input("USD → ARS", min_value=0.01, step=10.0, key="tc_USD")
        st.number_input("EUR → ARS", min_value=0.01, step=10.0, key="tc_EUR")
        st.selectbox(
            "Tipo de cotización USD",
            CASAS_DOLAR,
            index=CASAS_DOLAR.index("blue"),
            key="casa_dolar",
            help="Cuál cotización usar como referencia para el conversor (oficial, blue, MEP, CCL, cripto o tarjeta).",
        )

        st.button("🔄 Actualizar desde dolarapi.com",
                  on_click=actualizar_cotizaciones_callback,
                  use_container_width=True)

        if st.session_state.fx_msg:
            tipo, msg = st.session_state.fx_msg
            getattr(st, tipo)(msg)

        if st.session_state.tc_actualizado:
            st.caption(f"Actualizado: {st.session_state.tc_actualizado}")

    with st.expander("Guardar / Cargar", expanded=False):
        st.download_button(
            label="📥 Descargar configuración",
            data=serializar_config(),
            file_name="configuracion_finanzas.json",
            mime="application/json",
            use_container_width=True,
        )
        st.file_uploader(
            "📂 Cargar configuración",
            type=["json"],
            key="config_upload",
            on_change=cargar_config_callback,
            label_visibility="collapsed",
        )
        st.button(
            "🗑️ Borrar datos guardados",
            on_click=borrar_localstorage_callback,
            help="Solo afecta a este navegador.",
        )
        if st.session_state.config_msg:
            tipo, msg = st.session_state.config_msg
            getattr(st, tipo)(msg)

    # Fecha al pie del sidebar
    _hoy_sb = datetime.now()
    st.html(f"""
    <div style="margin-top:2rem; padding-top:0.9rem;
                border-top:1px solid rgba(255,255,255,0.1);
                font-family:'Inter',sans-serif; font-size:0.68rem;
                color:rgba(255,255,255,0.3);
                display:flex; align-items:center; gap:0.45rem;">
      <svg width="13" height="13" viewBox="0 0 14 14" fill="none">
        <circle cx="7" cy="7" r="5.5" stroke="rgba(255,255,255,0.35)" stroke-width="1.2"/>
        <polyline points="7,3.5 7,7 9.5,9" stroke="rgba(255,255,255,0.35)" stroke-width="1.2"
                  stroke-linecap="round" stroke-linejoin="round"/>
      </svg>
      <span>{_hoy_sb.strftime('%d/%m/%Y %H:%M')}</span>
    </div>
    """)

# ── Hero header ───────────────────────────────────────────────────────
st.html("""
<div style="text-align:center;padding:1.2rem 0.5rem 0.8rem;font-family:'Inter',sans-serif;">
  <div style="font-size:1.7rem;font-weight:800;color:var(--ink);
              letter-spacing:-0.03em;line-height:1.1;">
    FINANC<span style="color:#00C896;">·AI</span>
  </div>
  <div style="font-size:0.8rem;color:var(--muted);
              margin-top:0.35rem;line-height:1.5;max-width:280px;
              margin-left:auto;margin-right:auto;">
    Planificá tu ahorro, ordená tus metas y tomá mejores decisiones financieras.
  </div>
</div>
""")

# ── Cotizaciones ticker ────────────────────────────────────────────────
_cot = fetch_cotizaciones()
_ticker_items = []
if isinstance(_cot, dict):
    _usd = _cot.get("USD") or {}
    _eur = _cot.get("EUR")
    for label, val in [
        ("🟢 Blue",    _usd.get("blue")),
        ("📊 MEP",     _usd.get("bolsa")),
        ("💹 CCL",     _usd.get("contadoconliqui")),
        ("🏦 Oficial", _usd.get("oficial")),
        ("🇪🇺 EUR",    _eur),
    ]:
        if val:
            _ticker_items.append(f'<span class="tk-item"><span class="tk-label">{label}</span><span class="tk-val">${val:,.0f}</span></span>')

if _ticker_items:
    _ticker_content = "".join(_ticker_items * 3)
    st.html(f"""
    <style>
    .tk-wrap {{
      overflow: hidden; white-space: nowrap;
      background: rgba(255,255,255,0.03);
      border-top: 1px solid rgba(230,237,243,0.08);
      border-bottom: 1px solid rgba(230,237,243,0.08);
      padding: 0.45rem 0; margin: 0 -0.9rem 0.5rem;
      cursor: pointer;
    }}
    .tk-track {{
      display: inline-flex; gap: 0; animation: tk-scroll 22s linear infinite;
    }}
    .tk-wrap:hover .tk-track {{ animation-play-state: paused; }}
    @keyframes tk-scroll {{
      0%   {{ transform: translateX(0); }}
      100% {{ transform: translateX(-33.33%); }}
    }}
    .tk-item {{
      display: inline-flex; align-items: baseline; gap: 0.3rem;
      padding: 0 1.1rem; font-family: 'Inter', sans-serif;
      border-right: 1px solid rgba(230,237,243,0.1);
    }}
    .tk-label {{ font-size: 0.62rem; color: rgba(230,237,243,0.45); font-weight: 500; }}
    .tk-val   {{ font-size: 0.72rem; color: #00C896; font-weight: 700;
                 font-variant-numeric: tabular-nums; }}
    </style>
    <div class="tk-wrap" title="Pausá para leer · Tocá para actualizar">
      <div class="tk-track">{_ticker_content}</div>
    </div>
    """)

# ── Indicador de progreso interactivo ─────────────────────────────────
def render_progreso():
    pasos = [
        ("Situación", st.session_state.get("sueldo_valor", 0) > 0),
        ("Metas",     len(st.session_state.objetivos) > 0),
        ("Perfil",    st.session_state.perfil_completo),
    ]
    pasos.append(("Plan", all(v for _, v in pasos)))

    # Tab keywords para que el JS encuentre el botón correcto
    tab_keywords = ["Situaci", "Metas", "Perfil", "Plan"]

    _diurno = st.session_state.get('tema') == 'diurno'
    _fg_inactive  = "rgba(13,17,23,0.45)"   if _diurno else "rgba(230,237,243,0.5)"
    _bg_inactive  = "rgba(13,17,23,0.06)"   if _diurno else "rgba(230,237,243,0.06)"
    _bd_inactive  = "rgba(13,17,23,0.15)"   if _diurno else "rgba(230,237,243,0.15)"
    _accent       = "#00A87E"               if _diurno else "#00C896"
    _connector    = "rgba(13,17,23,0.18)"   if _diurno else "rgba(230,237,243,0.15)"

    chips_html = []
    for i, (label, done) in enumerate(pasos):
        fg    = "#FFFFFF"      if done else _fg_inactive
        bg    = _accent        if done else _bg_inactive
        border= _accent        if done else _bd_inactive
        mark  = "✓" if done else str(i + 1)
        kw    = tab_keywords[i]
        chips_html.append(
            f'<button onclick="goTab(\'{kw}\')" style="'
            f'display:inline-flex;align-items:center;gap:0.3rem;'
            f'padding:0.22rem 0.6rem;border:1px solid {border};'
            f'background:{bg};color:{fg};border-radius:999px;'
            f'font-family:Inter,sans-serif;font-size:0.6rem;font-weight:600;'
            f'white-space:nowrap;cursor:pointer;">'
            f'<span style="font-size:0.55rem;">{mark}</span>{label}</button>'
        )
        if i < len(pasos) - 1:
            chips_html.append(f'<span style="color:{_connector};font-size:0.6rem;'
                              'pointer-events:none;">──</span>')

    html = (
        '<div style="display:flex;gap:0.25rem;align-items:center;justify-content:center;'
        'flex-wrap:nowrap;margin:0.3rem 0 0.8rem;overflow-x:auto;">'
        + "".join(chips_html)
        + '</div>'
        + """
        <script>
        function goTab(keyword) {
          try {
            var tabs = window.parent.document.querySelectorAll(
              '[data-testid="stTabs"] [role="tab"]'
            );
            for (var t of tabs) {
              if (t.textContent.includes(keyword)) { t.click(); break; }
            }
          } catch(e) {}
        }
        </script>
        """
    )
    components.html(html, height=46)

render_progreso()


# ── Declaración de tabs ────────────────────────────────────────────────
tab_situacion, tab_metas, tab_perfil, tab_plan = st.tabs([
    "Mi Situación",
    "Mis Metas",
    "Mi Perfil",
    "Mi Plan",
])


# ── TAB 1: SITUACION ────────────────────────────────────────────────────
with tab_situacion:
    # Pre-read session state (widgets inside tabs will update these)
    total_necesidades = sum(float(st.session_state.get(f"gasto_{c['id']}", 0.0)) for c in CATEGORIAS_GASTOS if c["tipo"] == "Necesidad")
    total_deseos      = sum(float(st.session_state.get(f"gasto_{c['id']}", 0.0)) for c in CATEGORIAS_GASTOS if c["tipo"] == "Deseo")
    total_gastos      = total_necesidades + total_deseos
    ahorro_dispuesto  = 0.0

    _cat_icons = {
        "vivienda":      ("🏠", "#3B82F6"),
        "servicios":     ("⚡", "#F59E0B"),
        "alimentacion":  ("🛒", "#10B981"),
        "transporte":    ("🚌", "#F97316"),
        "salud":         ("❤️", "#EF4444"),
        "deudas":        ("💳", "#6B7280"),
        "suscripciones": ("📱", "#8B5CF6"),
        "salidas":       ("🍽️", "#EC4899"),
        "indumentaria":  ("👗", "#14B8A6"),
        "ocio":          ("🎭", "#6366F1"),
        "otros":         ("📦", "#9CA3AF"),
    }

    # ── Selector de sección (tab bar custom) ──────────────────────────────
    _sit_seccion = st.radio(
        "sección",
        ["Ingresos", "Egresos"],
        horizontal=True,
        label_visibility="collapsed",
        key="_sit_seccion",
    )

    # ── Aviso si no hay sueldo cargado ─────────────────────────────────────
    if float(st.session_state.get("sueldo_valor", 0.0)) == 0:
        if not st.session_state.get("_aviso_sueldo_ok", False):
            st.html("""
            <div style="background:rgba(13,45,107,0.55);border:1px solid rgba(0,200,150,0.3);
                        border-radius:10px;padding:1.1rem 1.4rem 1rem;font-family:'Inter',sans-serif;
                        margin:0.5rem 0 0.8rem;">
              <div style="font-size:0.7rem;text-transform:uppercase;letter-spacing:0.16em;
                          color:#00C896;font-weight:600;margin-bottom:0.4rem;">Aviso</div>
              <div style="font-size:0.88rem;color:#E6EDF3;line-height:1.5;">
                Completá tu sueldo para ver la distribución mensual y el diagnóstico financiero.
              </div>
            </div>
            """)
            if st.button("Aceptar", key="_btn_aviso_sueldo"):
                st.session_state["_aviso_sueldo_ok"] = True
                st.rerun()

    # ── INGRESOS ───────────────────────────────────────────────────────────
    moneda = st.session_state.get("moneda_ingreso", "ARS")  # siempre definida
    if _sit_seccion == "Ingresos":
        col_moneda, col_sueldo = st.columns([1, 2])
        with col_moneda:
            moneda = st.selectbox("Moneda", MONEDAS, index=MONEDAS.index(moneda), key="moneda_ingreso")
        with col_sueldo:
            sueldo = money_input("Sueldo Neto Mensual", key_canonical="sueldo_valor",
                                 help=f"En {moneda}. Se guarda automáticamente.")

        st.html("""
        <div style="display:flex;align-items:center;gap:0.5rem;
                    margin:1.1rem 0 0.5rem;font-family:'Inter',sans-serif;">
          <div style="width:6px;height:6px;border-radius:50%;background:#3B82F6;flex-shrink:0;"></div>
          <span style="font-size:0.62rem;text-transform:uppercase;letter-spacing:0.13em;
                       color:#3B82F6;font-weight:700;">¿Cuánto tenés ahorrado para emergencias?</span>
        </div>
        """)
        moneda_fe_actual = st.session_state.get("moneda_fondo_emerg", "ARS")
        col_moneda_fe, col_monto_fe = st.columns([1, 2])
        with col_moneda_fe:
            moneda_fe_actual = st.selectbox(
                "Moneda", MONEDAS, index=MONEDAS.index(moneda_fe_actual),
                key="moneda_fondo_emerg",
            )
        with col_monto_fe:
            fondo_emerg_monto = money_input(
                "Fondo de emergencia actual", key_canonical="fondo_emerg_valor",
                help=f"En {moneda_fe_actual}. No incluyas inversiones que tardan en rescatarse.",
            )
    else:
        # Widgets ocultos para que las keys sigan registradas en session_state
        moneda = st.session_state.get("moneda_ingreso", "ARS")
        sueldo = float(st.session_state.get("sueldo_valor", 0.0))
        fondo_emerg_monto = float(st.session_state.get("fondo_emerg_valor", 0.0))

    # ── EGRESOS ────────────────────────────────────────────────────────────
    if _sit_seccion == "Egresos":
        _moneda_eg = st.session_state.get("moneda_ingreso", "ARS")
        st.caption(f"Cargá tus gastos mensuales en {_moneda_eg}.")

        def _render_cat_grid(categorias):
            for i in range(0, len(categorias), 2):
                _gc1, _gc2 = st.columns(2)
                for j, _gcol in enumerate([_gc1, _gc2]):
                    if i + j >= len(categorias):
                        break
                    c = categorias[i + j]
                    _ico, _clr = _cat_icons.get(c["id"], ("📌", "#848D97"))
                    _short = c["nombre"].split("(")[0].strip()
                    with _gcol:
                        st.html(f"""
                        <div style="text-align:center;padding:0.6rem 0.3rem 0.2rem;
                                    font-family:'Inter',sans-serif;">
                          <div style="width:46px;height:46px;border-radius:50%;
                                      background:{_clr};margin:0 auto 0.35rem;
                                      display:flex;align-items:center;justify-content:center;
                                      font-size:22px;box-shadow:0 3px 10px {_clr}55;">
                            {_ico}
                          </div>
                          <div style="font-size:0.65rem;color:#E6EDF3;font-weight:600;
                                      white-space:nowrap;overflow:hidden;text-overflow:ellipsis;
                                      max-width:120px;margin:0 auto;">{_short}</div>
                        </div>
                        """)
                        st.number_input("monto", min_value=0.0, step=500.0,
                                        key=f"gasto_{c['id']}", label_visibility="collapsed")

        st.html("""
        <div style="display:flex;align-items:center;gap:0.5rem;margin:0.2rem 0 0.3rem;font-family:'Inter',sans-serif;">
          <div style="width:7px;height:7px;border-radius:50%;background:#3B82F6;flex-shrink:0;"></div>
          <span style="font-size:0.65rem;text-transform:uppercase;letter-spacing:0.12em;
                       color:#3B82F6;font-weight:700;">Necesidades</span>
          <span style="font-size:0.62rem;color:#848D97;">meta ≤ 50%</span>
        </div>
        """)
        _render_cat_grid([c for c in CATEGORIAS_GASTOS if c["tipo"] == "Necesidad"])

        st.html("""
        <div style="display:flex;align-items:center;gap:0.5rem;margin:0.8rem 0 0.3rem;font-family:'Inter',sans-serif;">
          <div style="width:7px;height:7px;border-radius:50%;background:#8B5CF6;flex-shrink:0;"></div>
          <span style="font-size:0.65rem;text-transform:uppercase;letter-spacing:0.12em;
                       color:#8B5CF6;font-weight:700;">Deseos</span>
          <span style="font-size:0.62rem;color:#848D97;">meta ≤ 30%</span>
        </div>
        """)
        _render_cat_grid([c for c in CATEGORIAS_GASTOS if c["tipo"] == "Deseo"])

    # Derivados (ambos tabs ya ejecutaron)
    sueldo           = float(st.session_state.get("sueldo_valor", 0.0))
    moneda           = st.session_state.get("moneda_ingreso", "ARS")
    fondo_emerg_monto= float(st.session_state.get("fondo_emerg_valor", 0.0))
    disponible_bruto = float(sueldo - total_gastos)

    # ── FULL WIDTH: botón o resultados ─────────────────────────────────────
    deuda_mensual_auto = float(st.session_state.get("gasto_deudas", 0.0))

    if sueldo > 0:
        # Botón para desbloquear / actualizar resultados
        st.html("""<div style="margin-top:1.6rem;"></div>""")
        _btn_label = "🔄 Actualizar Situación Financiera" if st.session_state.get("situacion_desbloqueada") else "📊 Ver Situación Financiera"
        _bc1, _bc2, _bc3 = st.columns([1, 2, 1])
        with _bc2:
            st.html(f"""
            <style>
            div[data-testid="stButton"] button[kind="primary"] {{
                background: linear-gradient(135deg, #00C896 0%, #00A87E 100%);
                border: none;
                border-radius: 12px;
                color: #0D1117;
                font-family: 'Inter', sans-serif;
                font-weight: 700;
                font-size: 1rem;
                padding: 0.75rem 2rem;
                width: 100%;
                letter-spacing: 0.02em;
                box-shadow: 0 4px 20px rgba(0,200,150,0.3);
                transition: all 0.2s;
            }}
            div[data-testid="stButton"] button[kind="primary"]:hover {{
                box-shadow: 0 6px 28px rgba(0,200,150,0.45);
                transform: translateY(-1px);
            }}
            </style>
            """)
            if st.button(_btn_label, key="_btn_ver_situacion", type="primary", use_container_width=True):
                st.session_state.situacion_desbloqueada = True
                st.session_state._scroll_resultados = True
                st.rerun()

        if st.session_state.get("situacion_desbloqueada"):
            # anchor para el scroll
            st.html("""<div id="situacion-resultados" style="margin-top:1.8rem;"></div>""")

            # scroll automático cuando se acaba de desbloquear
            if st.session_state.get("_scroll_resultados"):
                st.session_state._scroll_resultados = False
                components.html("""
                <script>
                setTimeout(function() {
                  try {
                    var el = window.parent.document.getElementById('situacion-resultados');
                    if (el) { el.scrollIntoView({ behavior: 'smooth', block: 'start' }); }
                  } catch(e) {}
                }, 150);
                </script>
                """, height=0)

            # ── Regla 50/30/20 ─────────────────────────────────────────────
            pct_n = total_necesidades / sueldo
            pct_d = total_deseos / sueldo
            pct_ahorro_potencial = max(0.0, disponible_bruto) / sueldo

            def _render_indicador(label, actual, meta, mayor_es_mejor=False):
                if mayor_es_mejor:
                    ok, soft = actual >= meta, actual >= meta * 0.7
                else:
                    ok, soft = actual <= meta, actual <= meta * 1.2
                color = "#2ECC71" if ok else ("#F1C40F" if soft else "#E74C3C")
                emoji = "🟢" if ok else ("🟡" if soft else "🔴")
                simbolo = "≥" if mayor_es_mejor else "≤"
                bar = min(100.0, actual * 100)
                return f"""
                <div style='padding:14px 16px;border:1px solid {color}44;border-radius:12px;
                            background:linear-gradient(135deg,{color}12,{color}04);'>
                  <div style='display:flex;justify-content:space-between;font-size:10px;
                              color:#848D97;font-family:Inter,sans-serif;margin-bottom:4px;'>
                    <span>{emoji} {label}</span>
                    <span>meta {simbolo} {meta:.0%}</span>
                  </div>
                  <div style='font-size:26px;font-weight:700;color:{color};
                              line-height:1.1;font-family:Inter,sans-serif;'>{actual:.1%}</div>
                  <div style='background:rgba(230,237,243,0.08);height:5px;border-radius:3px;
                              margin-top:8px;overflow:hidden;'>
                    <div style='background:{color};width:{bar}%;height:100%;border-radius:3px;'></div>
                  </div>
                </div>"""

            st.html("""
            <div style="display:flex;align-items:center;gap:0.75rem;margin-bottom:0.8rem;">
              <div style="flex:1;height:1px;background:rgba(230,237,243,0.1);"></div>
              <div style="font-size:0.62rem;text-transform:uppercase;letter-spacing:0.16em;
                          color:#848D97;font-weight:700;font-family:'Inter',sans-serif;
                          white-space:nowrap;">Regla 50 · 30 · 20</div>
              <div style="flex:1;height:1px;background:rgba(230,237,243,0.1);"></div>
            </div>
            """)
            _i1, _i2, _i3 = st.columns(3)
            _i1.markdown(_render_indicador("Necesidades", pct_n, 0.50), unsafe_allow_html=True)
            _i2.markdown(_render_indicador("Deseos", pct_d, 0.30), unsafe_allow_html=True)
            _i3.markdown(_render_indicador("Ahorro potencial", pct_ahorro_potencial, 0.20, mayor_es_mejor=True), unsafe_allow_html=True)
            st.caption(f"Total gastos: **{fmt(total_gastos, moneda)}** · Disponible bruto: **{fmt(max(0.0, disponible_bruto), moneda)}**")

            # ── Capacidad de ahorro ────────────────────────────────────────
            st.html("""
            <div style="display:flex;align-items:center;gap:0.75rem;margin:1.6rem 0 0.8rem;">
              <div style="flex:1;height:1px;background:rgba(230,237,243,0.1);"></div>
              <div style="font-size:0.62rem;text-transform:uppercase;letter-spacing:0.16em;
                          color:#848D97;font-weight:700;font-family:'Inter',sans-serif;
                          white-space:nowrap;">Capacidad de Ahorro</div>
              <div style="flex:1;height:1px;background:rgba(230,237,243,0.1);"></div>
            </div>
            """)
            if disponible_bruto > 0:
                st.info(f"Excedente disponible: **{fmt(disponible_bruto, moneda)}**")
                _ad_prev = float(st.session_state.get("ahorro_dispuesto_valor", 0.0))
                _ad_max = float(disponible_bruto)
                if _ad_prev <= 0 or _ad_prev > _ad_max:
                    st.session_state["ahorro_dispuesto_valor"] = _ad_max * DEFAULT_AHORRO_RATIO
                ahorro_dispuesto = st.slider(
                    "¿Cuánto vas a destinar al ahorro/inversión?",
                    min_value=0.0, max_value=_ad_max, step=500.0,
                    key="ahorro_dispuesto_valor",
                )
            else:
                st.error("🚨 Sin margen de ahorro.")

            # ── Distribución + Diagnóstico ─────────────────────────────────
            st.html("""
            <div style="display:flex;align-items:center;gap:0.75rem;margin:1.6rem 0 0.8rem;">
              <div style="flex:1;height:1px;background:rgba(230,237,243,0.1);"></div>
              <div style="font-size:0.62rem;text-transform:uppercase;letter-spacing:0.16em;
                          color:#848D97;font-weight:700;font-family:'Inter',sans-serif;
                          white-space:nowrap;">Distribución Mensual</div>
              <div style="flex:1;height:1px;background:rgba(230,237,243,0.1);"></div>
            </div>
            """)
            _pie_col, _diag_col = cols_or_stack([1, 1], gap="large")
            with _pie_col:
                remanente_ocio = max(0.0, disponible_bruto - ahorro_dispuesto)
                fig = go.Figure(data=[go.Pie(
                    labels=['Necesidades', 'Deseos', 'Ahorro Destinado', 'Remanente'],
                    values=[total_necesidades, total_deseos, ahorro_dispuesto, remanente_ocio],
                    hole=.5,
                    marker_colors=['#3B82F6', '#8B5CF6', '#00C896', '#1E2A3A'],
                    textfont=dict(color='#E6EDF3', size=11),
                    hovertemplate='<b>%{label}</b><br>%{value:,.0f}<br>%{percent}<extra></extra>',
                )])
                fig.update_layout(
                    margin=dict(t=10, b=10, l=0, r=0), height=300,
                    plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                    font=dict(color="#E6EDF3", family="Inter"),
                    legend=dict(font=dict(color="#848D97", size=11), orientation="v",
                                yanchor="middle", y=0.5, xanchor="left", x=1.02),
                    showlegend=True,
                )
                st.plotly_chart(fig, use_container_width=True)

            with _diag_col:
                gastos_para_fe = total_gastos if total_gastos > 0 else 1.0
                _moneda_fe_calc = st.session_state.get("moneda_fondo_emerg", moneda)
                _tipos_cambio_fe = {
                    "ARS": 1.0,
                    "USD": float(st.session_state.tc_USD),
                    "EUR": float(st.session_state.tc_EUR),
                }
                fondo_emerg_monto_conv = convertir(
                    fondo_emerg_monto, _moneda_fe_calc, moneda, _tipos_cambio_fe,
                )
                meses_fondo = fondo_emerg_monto_conv / gastos_para_fe if gastos_para_fe > 0 else 0.0
                indicadores = calcular_indicadores_salud(
                    sueldo, total_gastos, ahorro_dispuesto, meses_fondo, deuda_mensual_auto
                )
                if meses_fondo < 1 and ahorro_dispuesto > 0:
                    st.error("🚨 **Prioridad crítica:** No tenés fondo de emergencia. Antes de invertir, acumulá al menos 3 meses de gastos.")

                color_estado = {"ok": "#2ECC71", "warning": "#F1C40F", "error": "#E74C3C"}
                for ind in indicadores:
                    c = color_estado[ind["estado"]]
                    st.markdown(
                        f"""<div style='display:flex;align-items:center;gap:12px;
                                       padding:10px 14px;border-radius:10px;margin-bottom:8px;
                                       border:1px solid {c}33;
                                       background:linear-gradient(135deg,{c}0D,{c}04);'>
                          <div style='font-size:20px;flex-shrink:0;'>{ind['icono']}</div>
                          <div style='flex:1;min-width:0;'>
                            <div style='font-size:10px;color:#848D97;font-family:Inter,sans-serif;'>{ind['nombre']} <span style="color:#6E7681;">· {ind['benchmark']}</span></div>
                            <div style='font-size:17px;font-weight:700;color:{c};font-family:Inter,sans-serif;line-height:1.2;'>{ind['valor']}</div>
                          </div>
                          <div style='font-size:9px;color:#6E7681;font-family:Inter,sans-serif;
                                      text-align:right;max-width:90px;line-height:1.4;'>{ind['descripcion']}</div>
                        </div>""",
                        unsafe_allow_html=True,
                    )

    st.session_state.gastos_valor = total_gastos
    st.session_state.deuda_mensual_valor = deuda_mensual_auto if sueldo > 0 else 0.0


# ── Tablas de puntaje del perfil (fuera del tab para reutilizar) ────────
_T_10   = {"Los saco ya, no quiero perder más": 0, "Me preocupa pero los dejo un tiempo más": 33, "Los dejo, seguro se recupera": 67, "Pongo más plata, está barato": 100}
_T_EMOC = {"Muy mal, necesito recuperar esa plata ya": 0, "Preocupado/a pero puedo esperar": 30, "Incómodo/a pero confío que se recupera": 65, "Tranquilo/a, sabía que podía pasar": 100}
_T_30   = {"Los saco todo ya": 0, "Saco la mitad para no perder más": 20, "Los dejo y espero que suban": 60, "Pongo más, es una oportunidad": 100}
_T_PREF = {"Que no baje nunca, aunque gane poco": 0, "Que crezca un poco sin sobresaltos": 30, "Que crezca bien aunque a veces baje": 60, "Que crezca lo máximo posible": 100}
_T_CRIS = {"La guardé en casa o en el banco": 0, "Me puse nervioso/a pero no hice nada": 25, "Lo tomé con calma y esperé": 60, "Aproveché para moverla a algo mejor": 100, "Todavía no tenía plata ahorrada": 50}
_T_ESTAB = {"No tengo ingresos fijos o estoy sin trabajo": 0, "Trabajo por cuenta propia o mis ingresos varían": 35, "Tengo trabajo en relación de dependencia estable": 70, "Tengo más de una fuente de ingresos": 100}
_T_LIQ  = {"No, esta sería toda mi plata disponible": -15, "Probablemente no me alcanzaría": -5, "Sí, tengo otros ahorros separados": 0, "Sí, mis ingresos me alcanzarían para cubrirlo": 10}
_T_HOR  = {"Menos de 1 año": 5, "1 a 3 años": 25, "3 a 5 años": 55, "5 a 10 años": 80, "Más de 10 años": 100}
_RESP_OK = {
    "r_inflacion_q": "Van a alcanzar para comprar menos cosas que hoy",
    "r_uva_q":       "El monto crece al mismo ritmo que la inflación",
    "r_diversif_q":  "Porque si algo sale mal en un lugar, no perdés todo",
}
_PQ = [
    {"key":"r_10",         "sec":"Tolerancia al riesgo · 35%",    "q":"Guardaste $100.000 en algún lugar y al mes siguiente valen $90.000. ¿Qué hacés?",                                  "tipo":"radio",        "opts":["Los saco ya, no quiero perder más","Me preocupa pero los dejo un tiempo más","Los dejo, seguro se recupera","Pongo más plata, está barato"]},
    {"key":"r_emocional",  "sec":"Tolerancia al riesgo · 35%",    "q":"Pusiste 3 sueldos en un lugar y en 2 semanas perdieron un 25% de su valor. ¿Cómo te sentís?",                     "tipo":"radio",        "opts":["Muy mal, necesito recuperar esa plata ya","Preocupado/a pero puedo esperar","Incómodo/a pero confío que se recupera","Tranquilo/a, sabía que podía pasar"]},
    {"key":"r_30",         "sec":"Tolerancia al riesgo · 35%",    "q":"Esos $100.000 ahora valen $70.000. ¿Qué hacés?",                                                                   "tipo":"radio",        "opts":["Los saco todo ya","Saco la mitad para no perder más","Los dejo y espero que suban","Pongo más, es una oportunidad"]},
    {"key":"r_pref",       "sec":"Tolerancia al riesgo · 35%",    "q":"Cuando ponés plata en algún lado, ¿qué es lo más importante para vos?",                                           "tipo":"radio",        "opts":["Que no baje nunca, aunque gane poco","Que crezca un poco sin sobresaltos","Que crezca bien aunque a veces baje","Que crezca lo máximo posible"]},
    {"key":"r_crisis",     "sec":"Tolerancia al riesgo · 35%",    "q":"En momentos de crisis económica (2001, pandemia, devaluación fuerte), ¿cómo reaccionaste con tu plata?",          "tipo":"radio",        "opts":["La guardé en casa o en el banco","Me puse nervioso/a pero no hice nada","Lo tomé con calma y esperé","Aproveché para moverla a algo mejor","Todavía no tenía plata ahorrada"]},
    {"key":"r_estab",      "sec":"Situación financiera · 25%",    "q":"¿Cómo es tu fuente de ingresos hoy?",                                                                              "tipo":"radio",        "opts":["No tengo ingresos fijos o estoy sin trabajo","Trabajo por cuenta propia o mis ingresos varían","Tengo trabajo en relación de dependencia estable","Tengo más de una fuente de ingresos"]},
    {"key":"r_horizonte",  "sec":"Horizonte temporal · 20%",      "q":"¿Cuándo pensás que vas a necesitar usar la plata que invertís?",                                                   "tipo":"select_slider","opts":["Menos de 1 año","1 a 3 años","3 a 5 años","5 a 10 años","Más de 10 años"]},
    {"key":"r_liquidez",   "sec":"Horizonte temporal · 20%",      "q":"Si en los próximos 2 años tuvieras un gasto inesperado grande, ¿podrías cubrirlo sin tocar esta plata?",          "tipo":"radio",        "opts":["No, esta sería toda mi plata disponible","Probablemente no me alcanzaría","Sí, tengo otros ahorros separados","Sí, mis ingresos me alcanzarían para cubrirlo"]},
    {"key":"r_inflacion_q","sec":"Conocimiento financiero · 10%", "q":"Si guardás $10.000 en efectivo hoy y la inflación es alta, en un año esos $10.000...",                             "tipo":"radio",        "opts":["Siguen valiendo lo mismo, el efectivo es seguro","Van a alcanzar para comprar menos cosas que hoy","No cambia nada, depende del banco","Van a alcanzar para comprar más cosas"]},
    {"key":"r_uva_q",      "sec":"Conocimiento financiero · 10%", "q":"Un plazo fijo UVA es una forma de guardar plata en el banco donde...",                                             "tipo":"radio",        "opts":["El monto crece al mismo ritmo que la inflación","Podés sacar la plata cuando quieras","El Estado te garantiza una ganancia fija en dólares","Solo pueden usarlo las empresas"]},
    {"key":"r_diversif_q", "sec":"Conocimiento financiero · 10%", "q":"¿Por qué conviene no poner todos los ahorros en un solo lugar?",                                                   "tipo":"radio",        "opts":["Porque así garantizás ganar siempre","Porque si algo sale mal en un lugar, no perdés todo","Para pagar menos impuestos","Porque el banco te obliga a distribuirlo"]},
    {"key":"r_objetivo",   "sec":"Objetivo principal · 10%",      "q":"¿Cuál es tu objetivo financiero principal?",                                                                       "tipo":"selectbox",    "opts":OBJETIVOS_FINANCIEROS},
]
_TOTAL_PQ = len(_PQ)

# ── TAB 2: PERFIL ───────────────────────────────────────────────────────
with tab_perfil:
    st.html("""
    <div style="padding:0.6rem 0 0.2rem;font-family:'Inter',sans-serif;">
      <div style="font-size:1.1rem;font-weight:700;color:var(--ink);">Mi Perfil de Inversor</div>
      <div style="font-size:0.78rem;color:var(--muted);margin-top:0.2rem;line-height:1.5;">
        Completá el cuestionario para obtener tu Risk Score personalizado y recomendaciones precisas.
      </div>
    </div>
    """)

    # ── Carrusel de preguntas ────────────────────────────────────────────
    if 'perfil_paso' not in st.session_state:
        st.session_state.perfil_paso = 0
    if 'perfil_dir' not in st.session_state:
        st.session_state.perfil_dir = 'next'

    _mostrar_carrusel = (
        not st.session_state.perfil_completo
        or st.session_state.get('_rehacer_perfil', False)
    )

    if _mostrar_carrusel:
        _paso = min(st.session_state.perfil_paso, _TOTAL_PQ - 1)
        _q    = _PQ[_paso]
        _anim = "slideFromRight" if st.session_state.perfil_dir == 'next' else "slideFromLeft"
        _pct  = int((_paso / _TOTAL_PQ) * 100)

        components.html(f"""
        <style>
          @keyframes slideFromRight {{
            from {{ transform: translateX(55px); opacity:0; }}
            to   {{ transform: translateX(0);    opacity:1; }}
          }}
          @keyframes slideFromLeft {{
            from {{ transform: translateX(-55px); opacity:0; }}
            to   {{ transform: translateX(0);     opacity:1; }}
          }}
          body {{ margin:0; padding:0 0.1rem; background:transparent;
                  overflow:hidden; font-family:'Inter',sans-serif; }}
          .sec  {{ font-size:0.6rem; font-weight:700; text-transform:uppercase;
                   letter-spacing:0.14em; color:#00C896; margin-bottom:0.15rem; }}
          .cnt  {{ font-size:0.58rem; color:rgba(230,237,243,0.38); margin-bottom:0.4rem; }}
          .bar  {{ background:rgba(230,237,243,0.1); border-radius:99px;
                   height:3px; width:100%; margin-bottom:0.7rem; }}
          .fill {{ background:#00C896; height:3px; border-radius:99px; width:{_pct}%; }}
          .card {{ animation:{_anim} 0.26s ease; }}
          .qtxt {{ font-size:0.97rem; font-weight:600; color:#E6EDF3;
                   line-height:1.55; }}
        </style>
        <div class="sec">{_q['sec']}</div>
        <div class="cnt">Pregunta {_paso + 1} de {_TOTAL_PQ}</div>
        <div class="bar"><div class="fill"></div></div>
        <div class="card"><div class="qtxt">{_q['q']}</div></div>
        """, height=120)

        _prev = st.session_state.get(_q['key'])
        if _q['tipo'] == 'radio':
            _idx = _q['opts'].index(_prev) if _prev in _q['opts'] else 0
            st.radio("", _q['opts'], index=_idx, key=_q['key'],
                     label_visibility="collapsed")
        elif _q['tipo'] == 'select_slider':
            _def = _prev if _prev in _q['opts'] else "3 a 5 años"
            st.select_slider("", options=_q['opts'], value=_def,
                             key=_q['key'], label_visibility="collapsed")
        elif _q['tipo'] == 'selectbox':
            _idx = _q['opts'].index(_prev) if _prev in _q['opts'] else 4
            st.selectbox("", _q['opts'], index=_idx, key=_q['key'],
                         label_visibility="collapsed")

        st.html("<div style='height:0.4rem'></div>")
        _nc1, _nc2 = st.columns(2)
        with _nc1:
            if _paso > 0:
                if st.button("← Anterior", use_container_width=True, key="_pp"):
                    st.session_state.perfil_dir  = 'prev'
                    st.session_state.perfil_paso = _paso - 1
                    st.rerun()
        with _nc2:
            _ultimo = _paso == _TOTAL_PQ - 1
            if st.button("Calcular Score →" if _ultimo else "Siguiente →",
                         use_container_width=True, type="primary", key="_pn"):
                if _ultimo:
                    _r10  = st.session_state.get("r_10", "")
                    _remo = st.session_state.get("r_emocional", "")
                    _r30  = st.session_state.get("r_30", "")
                    _rpre = st.session_state.get("r_pref", "")
                    _rcri = st.session_state.get("r_crisis", "")
                    _sc_tol = (
                        _T_10.get(_r10, 50)   * 0.20 +
                        _T_EMOC.get(_remo, 50) * 0.25 +
                        _T_30.get(_r30, 50)   * 0.25 +
                        _T_PREF.get(_rpre, 50) * 0.20 +
                        _T_CRIS.get(_rcri, 50) * 0.10
                    )
                    _sr = float(st.session_state.get("sueldo_valor", 0))
                    _gr = float(st.session_state.get("gastos_valor", 0))
                    _fr = float(st.session_state.get("fondo_emerg_valor", 0))
                    _dr = float(st.session_state.get("deuda_mensual_valor", 0))
                    _ar = float(st.session_state.get("ahorro_dispuesto_valor", 0))
                    _mfe_origen = st.session_state.get("moneda_fondo_emerg", moneda)
                    _tc_fe = {
                        "ARS": 1.0,
                        "USD": float(st.session_state.tc_USD),
                        "EUR": float(st.session_state.tc_EUR),
                    }
                    _fr_conv = convertir(_fr, _mfe_origen, moneda, _tc_fe)
                    _gfe = _gr if _gr > 0 else 1
                    _mfe = _fr_conv / _gfe
                    _sce = 100 if _mfe>=6 else (75 if _mfe>=3 else (40 if _mfe>=1 else (15 if _mfe>0 else 0)))
                    _rd  = _dr / _sr if _sr > 0 else 0
                    _scd = 100 if _rd<=0.10 else (60 if _rd<=0.30 else (25 if _rd<=0.50 else 0))
                    _ra  = _ar / _sr if _sr > 0 else 0
                    _sca = 100 if _ra>=0.30 else (80 if _ra>=0.15 else (50 if _ra>=0.05 else (20 if _ra>0 else 0)))
                    _sc_cap = ((_sce*0.40 + _scd*0.35 + _sca*0.25)*0.75
                               + _T_ESTAB.get(st.session_state.get("r_estab",""), 50)*0.25)
                    _rhor = st.session_state.get("r_horizonte", "3 a 5 años")
                    _sc_hor = float(max(0.0, min(100.0,
                        _T_HOR.get(_rhor, 50) + _T_LIQ.get(st.session_state.get("r_liquidez",""), 0))))
                    _ac = sum([
                        st.session_state.get("r_inflacion_q") == _RESP_OK["r_inflacion_q"],
                        st.session_state.get("r_uva_q")       == _RESP_OK["r_uva_q"],
                        st.session_state.get("r_diversif_q")  == _RESP_OK["r_diversif_q"],
                    ])
                    _sc_con = (_ac / 3) * 100
                    _robj = st.session_state.get("r_objetivo", OBJETIVOS_FINANCIEROS[4])
                    _sc_obj = max(0.0, min(100.0, 50.0 + OBJETIVO_SCORE_AJUSTE.get(_robj, 0)))
                    _raw = (_sc_tol*PESO_TOLERANCIA + _sc_cap*PESO_CAPACIDAD +
                            _sc_hor*PESO_HORIZONTE  + _sc_con*PESO_CONOCIMIENTO +
                            _sc_obj*PESO_OBJETIVO)
                    st.session_state.risk_score         = round(max(0.0, min(100.0, _raw)), 1)
                    st.session_state.objetivo_financiero = _robj
                    st.session_state.horizonte_perfil   = _rhor
                    st.session_state.conocimiento_score = _sc_con
                    st.session_state.perfil_completo    = True
                    st.session_state.score_tolerancia   = round(_sc_tol, 1)
                    st.session_state.score_capacidad    = round(_sc_cap, 1)
                    st.session_state.score_horizonte    = round(_sc_hor, 1)
                    st.session_state.score_conocimiento = round(_sc_con, 1)
                    st.session_state.score_objetivo     = round(_sc_obj, 1)
                    st.session_state['_rehacer_perfil'] = False
                    st.rerun()
                else:
                    st.session_state.perfil_dir  = 'next'
                    st.session_state.perfil_paso = _paso + 1
                    st.rerun()

    if st.session_state.perfil_completo:
        risk_score          = st.session_state.risk_score
        objetivo_financiero = st.session_state.objetivo_financiero
        horizonte_perfil    = st.session_state.horizonte_perfil
        conocimiento_score  = st.session_state.conocimiento_score
        perfil_label_show, perfil_emoji_show = clasificar_perfil(risk_score)

        _score_color = color_perfil(risk_score)
        _bar_pct = int(risk_score)

        st.html(f"""
        <div style="
          background: linear-gradient(135deg, var(--paper-deep) 0%, rgba(0,200,150,0.08) 100%);
          border: 1px solid var(--rule);
          border-left: 3px solid {_score_color};
          border-radius: 8px;
          padding: 1.6rem 1.8rem;
          margin: 0.8rem 0 1.4rem 0;
        ">
          <div style="display:flex; flex-direction:column; gap:1rem;">
            <div style="display:flex; align-items:center; gap:1.2rem;">
              <div>
                <div style="font-family:'Inter',sans-serif; font-size:0.65rem;
                            text-transform:uppercase; letter-spacing:0.18em; color:var(--muted);">Risk Score</div>
                <div style="font-family:'Inter',sans-serif; font-size:3.2rem; font-weight:700; color:{_score_color};
                            line-height:1; letter-spacing:-0.04em; margin-top:0.2rem;">{risk_score}</div>
                <div style="font-family:'Inter',sans-serif; font-weight:600; font-size:1rem;
                            color:var(--ink); margin-top:0.2rem;">{perfil_label_show}</div>
              </div>
            </div>
            <div style="width:100%;">
              <div style="background:var(--whisper); height:4px; border-radius:2px; overflow:hidden; margin-bottom:1rem;">
                <div style="background:{_score_color}; width:{_bar_pct}%; height:100%; transition:width 0.4s;"></div>
              </div>
              <div style="font-family:'Inter',sans-serif; font-size:0.88rem; color:var(--ink);">
                <div style="display:flex; justify-content:space-between; border-bottom:1px solid var(--rule); padding-bottom:0.35rem;">
                  <span style="color:var(--muted); text-transform:uppercase; letter-spacing:0.14em; font-size:0.72rem;">Objetivo</span>
                  <span>{objetivo_financiero}</span>
                </div>
                <div style="display:flex; justify-content:space-between; border-bottom:1px solid var(--rule); padding:0.35rem 0;">
                  <span style="color:var(--muted); text-transform:uppercase; letter-spacing:0.14em; font-size:0.72rem;">Horizonte</span>
                  <span>{horizonte_perfil}</span>
                </div>
                <div style="display:flex; justify-content:space-between; padding-top:0.35rem;">
                  <span style="color:var(--muted); text-transform:uppercase; letter-spacing:0.14em; font-size:0.72rem;">Conocimiento</span>
                  <span>{int(conocimiento_score)} / 100</span>
                </div>
              </div>
            </div>
          </div>
        </div>
        """)

        _horizonte_meses_map = {
            "Menos de 1 año": 6, "1 a 3 años": 24, "3 a 5 años": 48,
            "5 a 10 años": 84, "Más de 10 años": 144,
        }
        horizonte_meses_perfil = _horizonte_meses_map.get(horizonte_perfil, 48)
        rec_general = recomendar_instrumento_avanzado(
            risk_score, horizonte_meses_perfil, objetivo_financiero, conocimiento_score
        )

        with st.container(border=True):
            st.markdown(
                f"### {rec_general['emoji']} Instrumento sugerido para tu perfil: "
                f"**{rec_general['tipo']}**"
            )
            st.markdown(rec_general["descripcion"])
            if rec_general.get("alternativas"):
                st.markdown(f"**Alternativas:** {' · '.join(rec_general['alternativas'])}")
            st.caption(
                "Esta es una sugerencia general basada en tu Risk Score y horizonte. "
                "En el tab **Mi Plan** vas a ver una recomendación específica para cada meta."
            )
        st.html("<div style='height:0.4rem'></div>")
        if st.button("Rehacer cuestionario", use_container_width=True):
            st.session_state['_rehacer_perfil'] = True
            st.session_state.perfil_paso = 0
            st.session_state.perfil_dir  = 'next'
            st.session_state.perfil_completo = False
            st.rerun()


# ── TAB 3: METAS ────────────────────────────────────────────────────────
with tab_metas:
    st.header("🎯 Mis Metas de Ahorro")
    
    moneda = st.session_state.moneda_ingreso
    sueldo = st.session_state.sueldo_valor
    ahorro_dispuesto = st.session_state.ahorro_dispuesto_valor
    supuestos = st.session_state.supuestos
    tipos_cambio = {
        "ARS": 1.0,
        "USD": float(st.session_state.tc_USD),
        "EUR": float(st.session_state.tc_EUR),
    }
    risk_score = st.session_state.risk_score
    objetivo_financiero = st.session_state.objetivo_financiero
    conocimiento_score = st.session_state.conocimiento_score
    perfil = clasificar_perfil(risk_score)[0]

    if sueldo <= 0:
        st.html("""
        <div style="background:rgba(13,45,107,0.55);border:1px solid rgba(0,200,150,0.3);
                    border-radius:10px;padding:1.4rem 1.6rem 1.2rem;font-family:'Inter',sans-serif;
                    max-width:480px;margin:0.5rem auto;">
          <div style="font-size:0.7rem;text-transform:uppercase;letter-spacing:0.16em;
                      color:#00C896;font-weight:600;margin-bottom:0.6rem;">Aviso</div>
          <div style="font-size:0.95rem;color:#E6EDF3;line-height:1.55;">
            Primero completá tu situación financiera en el tab Mi Situación.
          </div>
        </div>
        """)
        st.stop()

    if st.session_state.objetivos:
        tiene_fondo = any(o.get("Categoría") == "Fondo de Emergencia" for o in st.session_state.objetivos)
        if not tiene_fondo:
            st.html("""
            <div style="background:rgba(210,153,34,0.10); border-left:3px solid var(--warning);
                        border-radius:0 8px 8px 0; padding:0.95rem 1.2rem; margin:0.4rem 0 1.2rem 0;
                        font-family:'Inter',sans-serif;">
              <div style="font-family:'Inter',sans-serif; font-weight:600; color:var(--warning);
                          margin-bottom:0.25rem; font-size:1rem;">
                Sin fondo de emergencia en tu ruta
              </div>
              <div style="font-size:0.9rem; color:var(--ink); line-height:1.55;">
                En Argentina, con inflación volátil, el fondo de emergencia es la <em>primera</em> meta.
                Cargá una con categoría <strong>Fondo de Emergencia</strong> y prioridad <strong>Alta</strong>.
              </div>
            </div>
            """)

    col_form, col_lista = cols_or_stack([1, 2.5], gap="large")

    with col_form:
        with st.form("nuevo_objetivo", clear_on_submit=True):
            st.subheader("Añadir Nueva Meta")
            nombre_obj = st.text_input("Nombre de la Meta")
            categoria = st.selectbox("Categoría", CATEGORIAS)
            col_m, col_costo = st.columns([1, 2])
            moneda_meta = col_m.selectbox("Moneda", MONEDAS, index=MONEDAS.index(moneda))
            with col_costo:
                costo_total = money_input(
                    "Costo Total (hoy)",
                    key_canonical="_costo_total_form",
                    help="Valor de hoy en la moneda elegida. La inflación se ajusta automáticamente.",
                )
            ahorro_previo = money_input(
                "Ahorrado hoy (misma moneda)",
                key_canonical="_ahorro_previo_form",
                max_value=costo_total if costo_total > 0 else None,
            )
            cp1, cp2 = st.columns([2, 1])
            plazo_num = cp1.number_input("Plazo deseado", min_value=1, value=12)
            plazo_unit = cp2.selectbox("Unidad", ["Meses", "Años"])
            prioridad = st.select_slider("Prioridad", options=PRIORIDADES, value="Media")

            if st.form_submit_button("Añadir a la Ruta"):
                if not nombre_obj.strip():
                    st.warning("Falta el nombre de la meta.")
                elif costo_total <= 0:
                    st.warning("El costo total debe ser mayor a 0.")
                else:
                    meses = plazo_num if plazo_unit == "Meses" else plazo_num * 12
                    st.session_state.objetivos.append({
                        "Meta": nombre_obj.strip(),
                        "Categoría": categoria,
                        "Prioridad": prioridad,
                        "Moneda": moneda_meta,
                        "Costo Total": float(costo_total),
                        "Ya Ahorrado": float(min(ahorro_previo, costo_total)),
                        "Plazo (Meses)": int(meses),
                    })
                    st.rerun()

    objetivos_enriquecidos = []

    with col_lista:
        if st.session_state.objetivos:
            df_base = _normalizar_df(pd.DataFrame(st.session_state.objetivos), moneda_fallback=moneda)
            records = df_base.to_dict('records')
            cuotas_por_idx = [calcular_cuota_meta(r, supuestos) for r in records]
            df_base['Cuota Requerida'] = [c["cuota_ideal"] for c in cuotas_por_idx]

            st.subheader("Listado Estratégico")
            edited_df = st.data_editor(
                df_base, num_rows="dynamic", use_container_width=True,
                column_config={
                    "Categoría": st.column_config.SelectboxColumn("Categoría", options=CATEGORIAS),
                    "Prioridad": st.column_config.SelectboxColumn("Prioridad", options=PRIORIDADES),
                    "Moneda": st.column_config.SelectboxColumn("Moneda", options=MONEDAS),
                    "Costo Total": st.column_config.NumberColumn("Costo Total", format="%.2f"),
                    "Ya Ahorrado": st.column_config.NumberColumn("Ahorrado Hoy", format="%.2f"),
                    "Cuota Requerida": st.column_config.NumberColumn(
                        "Cuota Requerida", format="%.2f", disabled=True,
                        help="Calculada automáticamente con la fórmula de anualidad (inflación + rendimiento). No editable.",
                    ),
                },
                key="editor_cascada_final",
            )

            cleaned = _normalizar_df(edited_df.drop(columns=["Cuota Requerida"]), moneda_fallback=moneda)
            df_actual = df_base.drop(columns=["Cuota Requerida"])
            cols_comunes = [c for c in cleaned.columns if c in df_actual.columns]
            if not cleaned[cols_comunes].equals(df_actual[cols_comunes]):
                st.session_state.objetivos = cleaned.to_dict("records")
                st.rerun()

            st.caption("Borrar metas individualmente:")
            for i, obj in enumerate(st.session_state.objetivos):
                col_nombre, col_borrar = st.columns([6, 1])
                col_nombre.markdown(
                    f"**{obj['Meta']}** · _{obj['Categoría']}_"
                )
                if col_borrar.button("🗑️", key=f"borrar_meta_{i}", help=f"Borrar {obj['Meta']}"):
                    st.session_state.objetivos.pop(i)
                    st.rerun()

            sorted_indexed = sorted(enumerate(records), key=lambda t: PRIO_ORDER.get(t[1].get("Prioridad"), 3))
            ahorro_restante_ingreso = ahorro_dispuesto

            for orig_idx, obj in sorted_indexed:
                cuota = cuotas_por_idx[orig_idx]
                moneda_m = cuota["moneda_meta"]
                cuota_ideal_meta = cuota["cuota_ideal"]
                cuota_ideal_ingreso = convertir(cuota_ideal_meta, moneda_m, moneda, tipos_cambio)
                cuota_asignada_ingreso = min(ahorro_restante_ingreso, cuota_ideal_ingreso)
                ahorro_restante_ingreso -= cuota_asignada_ingreso
                cuota_asignada_meta = convertir(cuota_asignada_ingreso, moneda, moneda_m, tipos_cambio)

                objetivos_enriquecidos.append({
                    **obj,
                    "moneda_meta": moneda_m,
                    "costo_futuro": cuota["costo_futuro"],
                    "faltante_futuro": cuota["faltante_futuro"],
                    "r_mensual": cuota["r_mensual"],
                    "cuota_ideal_meta": cuota_ideal_meta,
                    "cuota_asignada_meta": cuota_asignada_meta,
                    "cuota_ideal_ingreso": cuota_ideal_ingreso,
                    "cuota_asignada_ingreso": cuota_asignada_ingreso,
                    "estado": estado_meta(cuota_asignada_meta, cuota_ideal_meta),
                    "objetivo_meta": CATEGORIA_A_OBJETIVO.get(obj.get("Categoría", "Otro"), objetivo_financiero),
                    "instrumento": recomendar_instrumento_avanzado(
                        risk_score,
                        obj.get("Plazo (Meses)", 0),
                        CATEGORIA_A_OBJETIVO.get(obj.get("Categoría", "Otro"), objetivo_financiero),
                        conocimiento_score,
                    ),
                })

            st.info(f"💰 Ahorro sobrante tras cubrir prioridades: **{fmt(ahorro_restante_ingreso, moneda)}**")
        else:
            st.info("Cargá una meta para ver la tabla.")

    st.session_state.objetivos_enriquecidos = objetivos_enriquecidos


# ── TAB 4: PLAN ─────────────────────────────────────────────────────────
with tab_plan:
    st.header("📈 Mi Plan Financiero")
    
    objetivos_enriquecidos = st.session_state.objetivos_enriquecidos
    moneda = st.session_state.moneda_ingreso
    ahorro_dispuesto = st.session_state.ahorro_dispuesto_valor
    supuestos = st.session_state.supuestos
    tipos_cambio = {
        "ARS": 1.0,
        "USD": float(st.session_state.tc_USD),
        "EUR": float(st.session_state.tc_EUR),
    }
    risk_score = st.session_state.risk_score
    perfil_label_show = clasificar_perfil(risk_score)[0]
    objetivo_financiero = st.session_state.objetivo_financiero
    horizonte_perfil = st.session_state.horizonte_perfil
    conocimiento_score = st.session_state.conocimiento_score

    if not objetivos_enriquecidos:
        st.info("👈 Cargá al menos una meta en el tab 'Mis Metas' para ver tu plan.")
        st.stop()

    OBJ_POR_FILA_PLAN = 1 if st.session_state.get("modo_compacto", False) else 2
    num_filas = math.ceil(len(objetivos_enriquecidos) / OBJ_POR_FILA_PLAN)

    for f in range(num_filas):
        cols = st.columns(OBJ_POR_FILA_PLAN) if OBJ_POR_FILA_PLAN > 1 else [st.container()]
        for c in range(OBJ_POR_FILA_PLAN):
            idx = f * OBJ_POR_FILA_PLAN + c
            if idx >= len(objetivos_enriquecidos):
                continue
            o = objetivos_enriquecidos[idx]
            categoria_obj = o.get("Categoría", "Otro")
            color = COLOR_PRIORIDAD.get(o['Prioridad'], '#888')
            m_meta = o['moneda_meta']

            with cols[c]:
                with st.container(border=True):
                    st.markdown(
                        f"### {o['Meta']} "
                        f"<span style='float:right; color:{color}; font-size:16px;'>"
                        f"{o['Prioridad']}</span>",
                        unsafe_allow_html=True,
                    )
                    st.markdown(
                        f"<span style='background:rgba(230,237,243,0.1); color:#848D97; padding:3px 10px; "
                        f"border-radius:20px; font-size:11px; font-family:Inter,sans-serif;'>{categoria_obj} · {m_meta}</span>",
                        unsafe_allow_html=True,
                    )

                    _costo_total = float(o["Costo Total"])
                    _ahorrado = float(o["Ya Ahorrado"])
                    _pct = min(100.0, (_ahorrado / _costo_total * 100) if _costo_total > 0 else 0.0)
                    st.html(f"""
                    <div style="margin: 0.6rem 0 0.9rem 0;">
                      <div style="display:flex; justify-content:space-between; align-items:baseline; margin-bottom:0.35rem;
                                  font-family:'Bricolage Grotesque',sans-serif; font-size:0.78rem;">
                        <span style="color:var(--muted); text-transform:uppercase; letter-spacing:0.16em;">Progreso</span>
                        <span style="font-family:'Fraunces',serif; font-weight:600; color:{color}; font-size:1.05rem;
                                     font-variant-numeric: tabular-nums;">{_pct:.0f}%</span>
                      </div>
                      <div style="background:var(--whisper); height:6px; border-radius:3px; overflow:hidden;">
                        <div style="background:{color}; width:{_pct}%; height:100%; transition:width 0.4s;"></div>
                      </div>
                      <div style="display:flex; justify-content:space-between; margin-top:0.3rem;
                                  font-family:'Bricolage Grotesque',sans-serif; font-size:0.78rem; color:var(--muted);
                                  font-variant-numeric: tabular-nums;">
                        <span>{fmt(_ahorrado, m_meta)}</span>
                        <span>{fmt(_costo_total, m_meta)}</span>
                      </div>
                    </div>
                    """)

                    m1, m2 = st.columns(2)
                    m1.metric("Cuota Ideal", fmt(o['cuota_ideal_meta'], m_meta))
                    delta_val = o['cuota_asignada_meta'] - o['cuota_ideal_meta']
                    m2.metric("Asignación Real", fmt(o['cuota_asignada_meta'], m_meta),
                              delta=f"{delta_val:,.2f}",
                              delta_color="normal" if delta_val >= 0 else "inverse")

                    st.caption(
                        f"Costo futuro estimado: **{fmt(o['costo_futuro'], m_meta)}** "
                        f"(hoy {fmt(o['Costo Total'], m_meta)})"
                    )

                    if o['estado'] == "En curso":
                        st.success("🎯 Meta en curso")
                    elif o['estado'] == "Parcial":
                        meses_reales = meses_para_acumular(
                            o['faltante_futuro'], o['cuota_asignada_meta'], o['r_mensual']
                        )
                        if meses_reales:
                            st.warning(f"⚠️ Meta parcial · ~{meses_reales} meses reales a este ritmo")
                        else:
                            st.warning("⚠️ Meta parcial")
                    else:
                        st.error("⏳ En espera (sin asignación)")

                    instrumento = o['instrumento']
                    st.markdown(f"**{instrumento['emoji']} Instrumento sugerido:** {instrumento['tipo']}")
                    st.caption(instrumento['descripcion'])
                    if instrumento.get("alternativas"):
                        st.caption(f"Alternativas: {' · '.join(instrumento['alternativas'])}")

                    terminos_en_tipo = [k for k in TOOLTIPS_INSTRUMENTOS if k.lower() in instrumento['tipo'].lower()]
                    terminos_en_alts = [k for k in TOOLTIPS_INSTRUMENTOS
                                        for alt in instrumento.get("alternativas", [])
                                        if k.lower() in alt.lower()]
                    terminos = list(dict.fromkeys(terminos_en_tipo + terminos_en_alts))[:2]
                    if terminos:
                        with st.expander("📖 ¿Qué significa?", expanded=False):
                            for t in terminos:
                                st.markdown(f"**{t}:** {TOOLTIPS_INSTRUMENTOS[t]}")

                    with st.expander("📈 Ver proyección temporal", expanded=False):
                        fig_proy = grafico_proyeccion(o, supuestos)
                        st.plotly_chart(fig_proy, use_container_width=True, key=f"proy_{idx}")

                    with st.expander("💡 ¿Qué pasaría si invertís esta plata?", expanded=False):
                        _costo_hoy  = float(o["Costo Total"])
                        _m_meta     = o["moneda_meta"]

                        _infl_anual  = supuestos.get(_m_meta, SUPUESTOS_DEFAULT[_m_meta])["inflacion"]
                        _infl_m      = _tasa_mensual(_infl_anual)

                        _tasas_perfil = st.session_state.get("tasas_por_perfil", {})
                        _perfil_inv   = clasificar_perfil(risk_score)[0]
                        _tasa_inv_anual = _tasas_perfil.get(_perfil_inv, 90.0)
                        _tasa_inv_m   = _tasa_mensual(_tasa_inv_anual)

                        _cuota_real = float(o["cuota_asignada_meta"])
                        _ya_ahorrado = float(o["Ya Ahorrado"])

                        def _meses_ahorro_simple(costo_hoy, ya_ahorrado, cuota, infl_m):
                            # Objetivo crece con inflación, plata se suma sin rendir
                            if cuota <= 0: return None
                            acum  = ya_ahorrado
                            costo = costo_hoy
                            meses = 0
                            while acum < costo and meses < 600:
                                acum  += cuota
                                costo *= (1 + infl_m)
                                meses += 1
                            return meses if acum >= costo else None

                        def _meses_con_inversion(costo_hoy, ya_ahorrado, cuota, infl_m, tasa_m):
                            # Objetivo crece con inflación, plata acumula interés compuesto
                            if cuota <= 0: return None
                            acum  = ya_ahorrado
                            costo = costo_hoy
                            meses = 0
                            while acum < costo and meses < 600:
                                acum  = acum * (1 + tasa_m) + cuota
                                costo *= (1 + infl_m)
                                meses += 1
                            return meses if acum >= costo else None

                        _m_aho = _meses_ahorro_simple(_costo_hoy, _ya_ahorrado, _cuota_real, _infl_m)
                        _m_inv = _meses_con_inversion(_costo_hoy, _ya_ahorrado, _cuota_real, _infl_m, _tasa_inv_m)

                        def _fmt_meses(m):
                            if m is None: return "No alcanza"
                            if m >= 600: return "+50 años"
                            if m >= 12:
                                a, mo = divmod(m, 12)
                                return f"{a}a {mo}m" if mo else f"{a} año{'s' if a>1 else ''}"
                            return f"{m} mes{'es' if m>1 else ''}"

                        _instrumentos_por_perfil = {
                            "Muy Conservador":   "Plazo fijo UVA · Cuenta remunerada",
                            "Conservador":       "FCI renta fija · Lecap",
                            "Moderado":          "FCI mixto · Bonos CER",
                            "Moderado Agresivo": "CEDEARs · ETFs · Cartera 60/40",
                            "Agresivo":          "Acciones · Renta variable",
                        }

                        _txt_aho = f"ahorrando una cuota fija de **{fmt(_cuota_real, _m_meta)}** por mes, vas a tardar **{_fmt_meses(_m_aho)}** en llegar al objetivo." if _m_aho else f"ahorrando **{fmt(_cuota_real, _m_meta)}** por mes **no alcanzás** el objetivo (la inflación crece más rápido que tu ahorro)."
                        _txt_inv = f"invirtiendo una cuota fija de **{fmt(_cuota_real, _m_meta)}** por mes a una tasa del **{_tasa_inv_anual:.0f}% anual**, vas a tardar **{_fmt_meses(_m_inv)}** en llegar al objetivo." if _m_inv else f"invirtiendo **{fmt(_cuota_real, _m_meta)}** por mes a esa tasa **no alcanzás** el objetivo en un plazo razonable."

                        st.markdown(f"🏦 {_txt_aho}")
                        st.markdown(f"📈 {_txt_inv}")

                        if _m_aho and _m_inv and _m_inv < _m_aho:
                            _diff = _m_aho - _m_inv
                            st.success(f"Invirtiendo llegás **{_fmt_meses(_diff)} antes** que ahorrando. Instrumentos sugeridos para tu perfil {_perfil_inv}: {_instrumentos_por_perfil.get(_perfil_inv, '-')}.")
                        st.caption("Podés cambiar las tasas en **Configuración → Supuestos macro**.")

    st.divider()

    st.header("🤖 Reporte de tu Asesor de IA")
    st.markdown(
        "Generá un análisis personalizado de la coherencia de tu plan: un asesor "
        "de IA revisa si tu fondo de emergencia es saludable, si tus metas son "
        "matemáticamente viables y si los instrumentos sugeridos están alineados "
        "con tu perfil de riesgo."
    )

    if st.button("✨ Analizar mi Plan Financiero", type="primary", key="btn_ai_report"):
        sueldo_ctx = float(st.session_state.get("sueldo_valor", 0.0))
        gastos_ctx = float(st.session_state.get("gastos_valor", 0.0))
        ahorro_ctx = float(st.session_state.get("ahorro_dispuesto_valor", 0.0))
        fondo_ctx = float(st.session_state.get("fondo_emerg_valor", 0.0))
        moneda_fondo_ctx = st.session_state.get("moneda_fondo_emerg", moneda)
        deuda_ctx = float(st.session_state.get("deuda_mensual_valor", 0.0))

        contexto_usuario = (
            "## Situación financiera\n"
            f"- Ingreso mensual: {fmt(sueldo_ctx, moneda)}\n"
            f"- Gastos totales mensuales: {fmt(gastos_ctx, moneda)}\n"
            f"- Ahorro dispuesto al mes: {fmt(ahorro_ctx, moneda)}\n"
            f"- Fondo de emergencia actual: {fmt(fondo_ctx, moneda_fondo_ctx)}\n"
            f"- Cuotas de deuda mensuales: {fmt(deuda_ctx, moneda)}\n\n"
            "## Perfil de inversor\n"
            f"- Risk Score: {risk_score} ({perfil_label_show})\n"
            f"- Objetivo financiero: {objetivo_financiero}\n"
            f"- Horizonte temporal: {horizonte_perfil}\n"
            f"- Nivel de conocimiento (score): {int(conocimiento_score)}\n\n"
            "## Metas financieras\n"
        )
        for o in objetivos_enriquecidos:
            contexto_usuario += (
                f"- **{o['Meta']}** ({o.get('Categoría', 'Otro')}, prioridad {o['Prioridad']}): "
                f"necesita {fmt(o['costo_futuro'], o['moneda_meta'])} en {int(o['Plazo (Meses)'])} meses · "
                f"estado: {o['estado']} · instrumento sugerido: {o['instrumento']['tipo']}\n"
            )

        system_prompt = (
            "Sos un asesor financiero experto, claro y empático, especializado en "
            "planificación personal. Analizá el plan financiero del usuario y "
            "entregá un reporte ejecutivo breve. Evaluá específicamente: "
            "(1) si el fondo de emergencia es saludable según sus gastos mensuales "
            "(benchmark: 3 a 6 meses de gastos), "
            "(2) si cada meta es matemáticamente viable con el ahorro dispuesto, "
            "los plazos planteados y la inflación esperada, y "
            "(3) si los instrumentos sugeridos para cada meta están alineados con "
            "el perfil de riesgo y horizonte del usuario. "
            "Cerrá con exactamente 2 recomendaciones accionables, priorizadas y "
            "específicas a la situación analizada. Tono profesional pero accesible, "
            "sin jerga innecesaria."
        )

        try:
            with st.spinner("🧠 Tu asesor de IA está analizando tu plan…"):
                texto = _generar_reporte_ia(contexto_usuario, system_prompt)
            st.session_state["ai_report"] = texto
        except RuntimeError:
            st.error(
                "⚠️ Falta configurar `GEMINI_API_KEY` en `.streamlit/secrets.toml`. "
                "Sin esa key no puedo consultar a Gemini."
            )
        except Exception:
            st.error("No pude generar el reporte. Revisá tu conexión o intentá de nuevo en un minuto.")

    if st.session_state.get("ai_report"):
        with st.container(border=True):
            st.caption(
                "✨ *Análisis generado por Gemini 2.5 Flash · respuesta cacheada 10 minutos para los mismos datos.*"
            )
            st.markdown(st.session_state["ai_report"])

    st.divider()

    st.header("4. Exportar Reporte")
    filas = tuple(
        (
            o["Meta"],
            o.get("Categoría", "Otro"),
            o["Prioridad"],
            o["moneda_meta"],
            round(float(o["Costo Total"]), 2),
            round(o["costo_futuro"], 2),
            round(float(o["Ya Ahorrado"]), 2),
            int(o["Plazo (Meses)"]),
            round(o['cuota_ideal_meta'], 2),
            round(o['cuota_asignada_meta'], 2),
            o['estado'],
            o['instrumento']["tipo"],
        )
        for o in objetivos_enriquecidos
    )

    perfil_data_export = (
        risk_score,
        perfil_label_show,
        objetivo_financiero,
        horizonte_perfil,
        int(conocimiento_score),
        st.session_state.score_tolerancia,
        st.session_state.score_capacidad,
        st.session_state.score_horizonte,
        st.session_state.score_conocimiento,
        st.session_state.score_objetivo,
    )

    st.download_button(
        label="📥 Exportar reporte a Excel",
        data=build_excel(filas, perfil_data=perfil_data_export),
        file_name=f"ruta_critica_{datetime.now():%Y-%m-%d}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


if not st.session_state.get("_ls_disabled"):
    _current_json = serializar_config().decode("utf-8")
    if _current_json != st.session_state.get("_ls_last_saved"):
        _ls.setItem(LS_KEY, _current_json, key="ls_autosave")
        st.session_state._ls_last_saved = _current_json
        if not st.session_state.get("_ls_toast_shown"):
            st.toast("✓ Guardado en este navegador", icon="💾")
            st.session_state._ls_toast_shown = True
