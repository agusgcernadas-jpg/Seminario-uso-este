# Planificador de Finanzas

App de planificación financiera personal hecha en Streamlit: presupuesto, metas
de ahorro, perfil de inversor, recomendación de instrumentos y reporte con IA
(Gemini). Pensada para el contexto argentino (ARS/USD/EUR, dólar vía dolarapi.com).

---

## Requisitos previos

- **Python 3.10 o superior** (el código usa sintaxis como `tuple[str, str]`).
  Verificá con: `python --version`
- **VS Code** con la extensión **Python** de Microsoft instalada.

---

## Puesta en marcha (paso a paso)

### 1. Abrir el proyecto en VS Code
Abrí esta carpeta (`planificador-finanzas`) desde *Archivo → Abrir carpeta*.

### 2. Crear y activar un entorno virtual
Abrí la terminal integrada (`Ctrl+Ñ` o *Terminal → Nueva terminal*) y ejecutá:

**Windows (PowerShell):**
```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

**macOS / Linux:**
```bash
python3 -m venv .venv
source .venv/bin/activate
```

> Si en VS Code aparece abajo a la derecha el aviso para seleccionar el intérprete,
> elegí el que dice `.venv`.

### 3. Instalar las dependencias
```bash
pip install -r requirements.txt
```

### 4. Configurar la API key de Gemini
La app usa Gemini para el "Reporte de tu Asesor de IA". Conseguí una key gratis en
https://aistudio.google.com/apikey y luego:

1. Entrá a la carpeta `.streamlit`.
2. Copiá `secrets.toml.example` y renombrá la copia a `secrets.toml`.
3. Reemplazá el texto de ejemplo por tu key real:

```toml
GEMINI_API_KEY = "tu-key-real"
```

> El resto de la app (presupuesto, metas, gráficos, export a Excel) funciona sin
> la key. Solo el reporte de IA la necesita.

### 5. Ejecutar la app
```bash
streamlit run app.py
```

Se abre sola en el navegador en `http://localhost:8501`. Para frenarla, `Ctrl+C`
en la terminal.

---

## Estructura del proyecto

```
planificador-finanzas/
├── app.py                       # Todo el código de la app
├── requirements.txt             # Dependencias
├── README.md                    # Este archivo
├── .gitignore                   # Evita subir secrets y temporales
└── .streamlit/
    └── secrets.toml.example     # Plantilla de la API key (copiar a secrets.toml)
```

---

## Notas

- Los datos del usuario se guardan en el **localStorage del navegador**
  (`streamlit-local-storage`), no en un archivo ni base de datos.
- Las cotizaciones del dólar/euro se traen de `dolarapi.com`; si no hay conexión,
  la app mantiene los valores manuales.
- El reporte de IA cachea la respuesta unos minutos para los mismos datos, así no
  consume cuota de la API innecesariamente.

---

## Deploy gratis en Render (con dominio propio)

Render corre tu app Python tal cual (sin reescribir nada), tiene plan gratuito,
permite dominio personalizado y no pide tarjeta. Ya viene incluido el archivo
`render.yaml` con la configuración.

### Pasos

1. **Subí el código a GitHub.** En la terminal, dentro de la carpeta:
   ```bash
   git init
   git add .
   git commit -m "Primer commit"
   ```
   Creá un repo en github.com y seguí las instrucciones que te da para
   `git remote add origin ...` y `git push`.

   > El `secrets.toml` real queda fuera del repo gracias al `.gitignore`. Bien.

2. **Creá el servicio en Render.** Entrá a https://render.com, registrate
   (gratis, sin tarjeta), y elegí *New → Web Service → Connect a repository*.
   Seleccioná tu repo. Como hay un `render.yaml`, Render toma solo la config:
   - Build: `pip install -r requirements.txt`
   - Start: `streamlit run app.py --server.port $PORT ...`
   - Plan: Free

3. **Cargá la API key como Secret File** (clave para que el reporte de IA
   funcione sin exponer la key). En el panel del servicio:
   *Environment → Secret Files → Add Secret File*
   - **Filename / Path:** `.streamlit/secrets.toml`
   - **Contents:**
     ```toml
     GEMINI_API_KEY = "tu-key-real"
     ```
   Así tu código sigue leyendo `st.secrets["GEMINI_API_KEY"]` sin cambios.

4. **Deploy.** Render construye y publica. Te queda una URL tipo
   `https://planificador-finanzas.onrender.com`.

5. **Dominio propio (opcional).** En *Settings → Custom Domains → Add Custom
   Domain*, cargás tu dominio y Render te indica el registro DNS (CNAME) a crear
   en tu proveedor. El HTTPS lo gestiona Render solo.

### Sobre el "cold start"

En el plan gratis, si nadie usa la app por 15 minutos, el servidor se duerme y
la siguiente visita tarda ~30-50 s en despertar. Dos soluciones:

- **Gratis:** creá un monitor en https://uptimerobot.com que haga ping a tu URL
  cada 5 minutos. Así el server no se duerme.
- **Pago:** el plan Starter (~US$7/mes) lo mantiene siempre prendido.

> **Nota:** no uses Netlify para esta app. Netlify sirve archivos estáticos y
> funciones serverless cortas; no corre el servidor Python persistente que
> Streamlit necesita. Render, Railway o Hugging Face Spaces sí.
