# ⚡ JobAutoFill - Extensión de Chrome para Ofertas de Empleo

Extensión para Google Chrome (Manifest V3) diseñada para rellenar de forma inteligente y con un solo clic los formularios de solicitud de empleo más habituales (LinkedIn Easy Apply, InfoJobs, Greenhouse, Lever, Workday, portales de empresa, etc.).

---

## 🚀 Características Principales

- **Frontal de Configuración Moderno:** Panel visual completo organizado por categorías (Datos Personales, Ubicación, Perfil Profesional, Enlaces/Redes, CV y Preguntas Frecuentes).
- **Scraper Inteligente Multilingüe:** Detecta automáticamente los campos del formulario analizando nombres de atributos (`id`, `name`, `placeholder`, `aria-label`, `data-automation-id`), etiquetas `<label>` asociadas y el contexto circundante, tanto en **español** como en **inglés**.
- **Compatibilidad con React, Vue, Angular y Workday:** Utiliza la técnica de *Native Property Descriptor Setter* para que los frameworks reactivos registren los cambios sin borrar los campos al enviar el formulario.
- **Gestión Avanzada del Currículum (CV):**
  - **Inyección directa del archivo:** Sube tu PDF una vez en el panel de configuración; la extensión inyecta el objeto `File` mediante `DataTransfer` directamente en el campo `<input type="file">`.
  - **Copia rápida de ruta en disco:** Guarda la ruta local de tu CV (ej: `/Users/christian.rivero/Documents/CV.pdf`) y cópiala con un solo clic desde el botón flotante si se abre el diálogo nativo del sistema operativo.
- **Múltiples Formas de Disparo:**
  1. **Botón Flotante en la Página:** Aparece discretamente en la esquina inferior derecha con el conteo de campos detectados.
  2. **Popup Rápido:** Desde la barra de extensiones de Chrome.
  3. **Atajo de Teclado:** `Alt + Shift + F` (o `Option + Shift + F` en Mac).
  4. **Menú Contextual:** Clic derecho en cualquier parte del formulario -> *"⚡ Rellenar oferta con JobAutoFill"*.
- **Copia de Seguridad:** Exporta e importa tus datos en formato JSON en cualquier momento.

---

## 📦 Instalación en Google Chrome (Modo Desarrollador)

Sigue estos sencillos pasos para cargar la extensión en Chrome:

1. Abre Google Chrome y escribe en la barra de direcciones:
   ```
   chrome://extensions/
   ```
2. Activa el interruptor **"Modo de desarrollador"** (Developer mode) situado en la esquina superior derecha.
3. Haz clic en el botón **"Cargar descomprimida"** (Load unpacked) en la esquina superior izquierda.
4. Selecciona la carpeta `extension/` que se encuentra dentro de este proyecto:
   ```
   /Users/christian.rivero/Desktop/linkedinTracker/extension
   ```
5. ¡Listo! La extensión quedará instalada y verás el icono de **JobAutoFill** en tu barra de extensiones.

---

## ⚙️ Configuración Inicial

1. Haz clic en el icono de **JobAutoFill** en Chrome y pulsa en el engranaje ⚙️ (o clic derecho en el icono -> *Opciones*).
2. Se abrirá la página de configuración:
   - Puedes pulsar en **"⚡ Cargar Datos Demo"** para rellenar campos de prueba al instante.
   - O bien introduce tus datos reales (Nombre, Email, Teléfono, LinkedIn, etc.).
   - En la pestaña **Currículum (CV)**:
     - Arrastra o sube tu archivo PDF de CV.
     - Opcionalmente escribe la ruta local de tu CV en disco.
3. Haz clic en **"💾 Guardar Cambios"**.

---

## 🧪 Cómo Probar la Extensión

Hemos incluido un formulario de prueba realista que simula las plataformas Greenhouse / Workday / Lever:

1. Abre el archivo de prueba en tu navegador:
   ```
   file:///Users/christian.rivero/Desktop/linkedinTracker/extension/test/job_form_test.html
   ```
   *(O simplemente haz doble clic en `extension/test/job_form_test.html`)*.
2. Observarás el botón flotante morado **"⚡ Rellenar Empleo"** en la esquina inferior derecha indicando los campos detectados.
3. Haz clic en el botón flotante, o presiona `Alt + Shift + F`, o abre el popup de la extensión y pulsa **"Rellenar Formulario Ahora"**.
4. Verás cómo todos los campos (nombre, apellidos, email, teléfono, CV, dirección, ciudad, país, LinkedIn, GitHub, preguntas de visado, etc.) se completan automáticamente con un efecto visual iluminado.

---

## 📂 Estructura de Archivos

```
extension/
├── manifest.json            # Configuración Manifest V3 de Chrome
├── icons/                   # Iconos en resoluciones 16, 32, 48 y 128 px
│   ├── icon16.png
│   ├── icon32.png
│   ├── icon48.png
│   └── icon128.png
├── options/                 # Frontal de configuración completo
│   ├── options.html
│   ├── options.css
│   └── options.js
├── popup/                   # Interfaz emergente rápida de la barra de Chrome
│   ├── popup.html
│   ├── popup.css
│   └── popup.js
├── scripts/                 # Lógica de scraping y fondo
│   ├── content.js          # Scraper DOM, heurísticas y autocompletado
│   ├── content.css         # Estilos del widget flotante y animaciones
│   └── background.js       # Service worker para atajos y menú contextual
├── test/
│   └── job_form_test.html  # Formulario de simulación de oferta de empleo
└── README.md
```
