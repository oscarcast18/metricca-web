# metricca-web

Sitio web de **METRICCA** — Planificación · Diseño · Construcción.

Página estática (un solo `index.html`, sin dependencias ni build) publicada con **GitHub Pages**.

## Editar y publicar

1. Editar `index.html`.
2. Commit y push a `main`:

   ```bash
   git add . && git commit -m "descripción del cambio" && git push
   ```

3. GitHub Pages redeploya automáticamente en 1-2 minutos.

## Estructura

- `index.html` — toda la página: estilos, contenido y marcado en un solo archivo.
- Paleta y tipografía definidas como custom properties CSS en el bloque `:root` (teal METRICCA `#0F5E6B`, acento ámbar). Soporta tema claro y oscuro del sistema.

## Pendientes

- [ ] Reemplazar contenido placeholder: cifras, proyectos (con fotos reales), dirección, teléfono y correo.
- [ ] Incrustar el logo original (PNG transparente o SVG) en lugar de la recreación tipográfica.
- [ ] Conectar el formulario de contacto (Formspree o botón de WhatsApp).
- [ ] Dominio propio (agregar archivo `CNAME` y configurar DNS).
