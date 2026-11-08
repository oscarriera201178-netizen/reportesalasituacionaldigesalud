# DIGESALUD-MPPD — Inventario de Centros de Salud

El portal muestra el título **SALA SITUACIONAL DIGESALUD-MPPD** en el inicio de
sesión, en mayúsculas, centrado y con fuente reducida; encima va el escudo de la
Dirección General de Salud de la F.A.N.B. ([escudo.png](./escudo.png)), centrado
y reducido a la mitad del ancho del formulario de usuario y contraseña, que
ocupa un tercio del ancho, centrado bajo el título. La
cuenta administradora muestra el cintillo institucional y debajo el título
**SALA SITUACIONAL DIGESALUD-MPPD**, con el mismo cuadro verde, texto blanco,
centrado y en negrita que los centros. Este título permanece en una sola línea
con fuente reducida y adaptable al ancho de pantalla. Cada cuenta de centro ve el encabezado
**[NOMBRE DEL CENTRO]**, sin el prefijo «Sala Situacional», centrado, en mayúsculas y letras blancas,
dentro de un cuadro del mismo color verde del botón de categoría seleccionado
(color primario del tema). Esto no cambia el nombre registrado del
centro en los listados ni en los reportes PDF. El nombre entre comillas permanece
en una sola línea; en pantallas estrechas el encabezado permite desplazamiento
horizontal para no dividirlo ni ocultarlo.
Los 35 portales de centros muestran el cintillo institucional encima del cuadro
verde del nombre, ajustado al ancho disponible y sin deformarlo.
Debajo del título del administrador se muestra la semana del período de reporte
(lunes a viernes, hora de Venezuela) y **Centros de Salud que Han Reportado:
enviados/total Faltan: pendientes**. Se cuentan únicamente envíos del período actual y el total
se obtiene de los centros registrados, inicialmente 35.

Aplicación Streamlit independiente de Residencias, adaptable a móvil y computadora.
No consulta ni modifica las bases de datos de Residencias.
Todos los botones muestran sus títulos en mayúsculas y negrita, incluidos
categorías, formularios, carga, envío y descargas PDF.
El botón **CAMAS HOSPITALARIAS** permite varias líneas y ajusta su altura para
mostrar el texto completo.

## Primera versión

- Inventario privado: ninguna cantidad ni centro se muestra sin iniciar sesión.
- Una cuenta administradora y una cuenta por centro, sin límite fijo de centros.
  Cada centro tiene un número permanente, visible en los listados y selectores.
- La administración (DIGESALUD-MPPD) solo consulta y descarga PDF; no realiza
  cargas. Bajo el título verde centrado **RESUMEN DE LOS CENTROS DE SALUD**
  aparecen los mismos siete botones de ítems del portal de centros.
  Cada ítem permite elegir un centro o todos y un tipo o todos los tipos.
  Los estados semanales de los centros permanecen visibles y no cambian al
  filtrar el inventario; el contador semanal aparece bajo el título institucional.
  No muestra el apartado **Administrar centros y cuentas** ni formularios para
  crear, editar o gestionar cuentas. Los centros, usuarios, inventarios y reportes
  existentes se conservan; esta retirada solo afecta la pantalla.
- Las cargas las realiza cada centro de salud, que consulta y actualiza
  únicamente sus registros. Su pantalla muestra el encabezado de sala situacional
  y, a continuación, los botones de categoría para registrar; no hay selector
  de centro. El PDF del centro aparece al final y nada se muestra después. Los permisos de
  acceso por centro se verifican en el almacenamiento, no solo en los controles
  de pantalla.
- Camas hospitalarias, vehículos, bancos de sangre,
  laboratorios y quirófanos aparecen en secciones independientes, accesibles
  con botones. Camas y vehículos muestran cantidades operativas e inoperativas
  que comienzan en `00`; el cero indica que no hay unidades. Los totales suman
  ambas cantidades. Bancos y laboratorios registran presencia y
  estado; los quirófanos registran además sus cantidades. **Cargar datos** guarda cada sección sin enviar el inventario semanal.
  Los
  registros individuales anteriores de bancos, laboratorios y quirófanos se
  convierten a cantidades al actualizar la base, y se conservan como histórico.
  No se registran bolsas ni existencias de sangre.
- En la vista del centro, **CAMAS HOSPITALARIAS** aparece en negrita y
  mayúsculas, dentro de un cuadro con fondo verde del color primario del tema
  y letras blancas. Su cuadro permite cargar Hospitalización, Observación, Trauma
  shock, UTIA, UTIP y UCI, con columnas de **Operativas**, **Inoperativas**
  y **Total**. Los totales por tipo y el total general se actualizan al cambiar
  las cantidades, antes de guardar. **Cargar datos** guarda todas las camas
  sin enviar el inventario semanal; permite seguir editándolas mientras el
  período esté abierto y no se haya enviado el inventario.
- El único botón **VEHÍCULOS** reúne cinco grupos: **Ambulancias** (soporte
  básico, soporte avanzado y tácticas), **Vehículos protocolares**
  (carros/camionetas), **Carga pesada (camiones y gandolas)**,
  **Transporte de personal (autobús, van y minivan)** y **Motos**.
  Carga pesada y transporte registran cada uno una cantidad operativa y otra
  inoperativa por grupo, no por subtipo. Los cinco títulos aparecen en cuadros
  con fondo verde del color primario del tema y letras blancas, también en
  modo de consulta. El cuadro muestra operativas,
  inoperativas y totales automáticos. Debajo de cada grupo aparece su subtotal
  de operativas, inoperativas y la suma de ambas; al final se conserva el total
  general. Los subtotales se actualizan durante la carga y siguen visibles al
  consultar la sección guardada. **Cargar datos** guarda los cinco grupos
  juntos sin enviar el inventario semanal. El registro anterior de «Carga pesada /
  autobús» se conserva como historial sin asignar, fuera de los totales actuales
  y del PDF; no se reparte automáticamente. La sección vuelve a quedar pendiente
  de cargar para que el centro confirme la separación, conservando los otros tipos.
- **BANCO DE SANGRE** aparece dentro de un cuadro con fondo verde y letras
  blancas en negrita. Sin cuadro de cantidades: se indica **Sí / No** y, si
  existe, **Operativo / Fuera de servicio**. **Cargar datos** guarda sin enviar
  el inventario semanal. En almacenamiento y PDF, «No» equivale a cero unidades
  y «Sí» a una unidad en el estado elegido. Las cantidades anteriores no cambian
  hasta guardar; si había más de una unidad, se avisa antes de sustituirlas.
  **Descargar PDF** en bancos de sangre descarga únicamente esta sección, sin
  camas, vehículos, laboratorios ni otros cuadros. Al cambiar de sección se
  retira la descarga anterior para evitar descargar un informe diferente.
- **LABORATORIO** contiene **Laboratorio central** y **Laboratorio de emergencia**,
  con títulos verdes y selección independiente de **Sí / No** y
  **Operativo / Fuera de servicio**. **Cargar datos** exige completar ambos y
  guarda cero o una unidad por tipo, sin enviar el inventario semanal.
  Los registros anteriores de «Laboratorio» corresponden al central; emergencia
  queda pendiente, sin asumir que no existe. Las cantidades anteriores del
  central se sustituyen solo al guardar, con aviso si había más de una unidad.
  **Descargar PDF** en laboratorios muestra los grupos separados: **Central**,
  **Emergencia** y **Laboratorios especiales**, cada uno con operativos e
  inoperativos y un total general sin duplicar unidades. No incluye banco de
  sangre ni otras secciones. El informe completo utiliza la misma separación.
  **LABORATORIOS ESPECIALES** permite elegir **Sí / No**. Al elegir Sí aparecen
  tres espacios con nombre editable y estado **Operativo / Fuera de servicio**;
  los nombres se convierten automáticamente a mayúsculas al ingresarlos o
  editarlos y se guardan en mayúsculas. En el PDF, cada especial aparece con su
  propio nombre como encabezado y sus cantidades, en lugar del título genérico.
  se exige al menos un nombre, hasta tres, sin duplicados. Los espacios vacíos
  no se registran. **Cargar datos** guarda los laboratorios central, de emergencia
  y especiales juntos, sin enviar la semana. Al guardar No se retiran los
  especiales del inventario actual. El resumen y PDF suman sus unidades; el PDF
  también incluye un cuadro con sus nombres y estados.
- **EQUIPOS MÉDICOS ESPECIALES** presenta ocho tipos fijos: Máquina de anestesia,
  Tomógrafo, Resonador, Radiología, Ecógrafo, Arco en C, Silla odontológica y
  Silla para diálisis. Los títulos tienen fondo verde. Se cargan cantidades
  operativas e inoperativas, con totales automáticos; se permiten varias unidades
  por tipo. No se piden código, marca, modelo ni serie. **Cargar datos** guarda
  los ocho tipos juntos sin enviar la semana. Los equipos individuales anteriores
  permanecen en **Historial de equipos anteriores**, sin sumarse al inventario
  actual ni bloquear su envío por campos históricos incompletos. El formulario
  nuevo inicia en 00, pero requiere **CARGAR DATOS** aunque no haya unidades.
  El resumen y los PDF utilizan exclusivamente las nuevas cantidades.
  **Descargar PDF** en equipos médicos especiales incluye solo esta sección.
- **PLANTAS ELÉCTRICAS** tiene un botón y sección propios, fuera de Equipos
  médicos especiales. Registra operativas, inoperativas y total automático.
  **Cargar datos** guarda sin enviar la semana. Tiene resumen y PDF propios;
  sus cantidades no se suman a equipos. Si se habían guardado en equipos, se
  trasladan a la sección independiente al iniciar el almacenamiento.
- No se cargan datos incompletos: cada formulario solo guarda si todos sus
  campos están llenos (también se verifica en el almacenamiento).
- En los siete ítems, el primer clic en **CARGAR DATOS** pregunta
  **¿Ha editado todos los campos?** sin guardar ni bloquear la sección.
  Es necesario un segundo clic en **CONFIRMAR CARGA** para guardar. Si se
  modifica algún campo o se cambia de ítem, la confirmación se reinicia.
- **ENVIAR A DIGESALUD-MPPD** aparece al final de cualquier sección, antes del
  PDF, únicamente cuando se han guardado todos los tipos de camas, vehículos,
  banco de sangre, laboratorios central y de emergencia, quirófanos, equipos
  médicos especiales y plantas eléctricas, y los datos están completos.
  Al abrir el portal del centro, los tipos sin
  registros se guardan automáticamente en **00** (equivalente a **No** en
  instalaciones). Estos valores iniciales no cuentan como una carga confirmada:
  es obligatorio pulsar **CARGAR DATOS** en las siete secciones, incluso si
  permanecen en **00 / No**. El envío queda bloqueado mientras falte alguna,
  también en el almacenamiento. Los valores existentes nunca se reemplazan por
  cero. Cualquier cambio deja la sección pendiente hasta guardar.
  Si se indican laboratorios especiales,
  se exige al menos uno con nombre y estado. **Cargar datos** no envía el reporte.
  El envío vuelve a comprobar todos los ítems en el almacenamiento y notifica
  a DIGESALUD-MPPD.
  Después de **CARGAR DATOS**, la sección completa queda en consulta, sin
  controles de carga. **EDITAR** la desbloquea antes del envío final; mientras
  esté en edición, debe cargarse otra vez para habilitar **ENVIAR A DIGESALUD-MPPD**.
  El bloqueo también se verifica en el almacenamiento. Tras enviar no se permite
  editar. Cada lunes comienza un nuevo período: se conservan las cantidades,
  pero las siete secciones deben cargarse nuevamente para enviar esa semana,
  incluidas las que continúan vacías en 00.
  Cada centro puede enviar una sola vez por semana.
- **QUIRÓFANOS** muestra **Quirófano en piso** y **Quirófano en emergencia**,
  con títulos verdes, selección **Sí / No** y, cuando hay, las **cantidades
  operativas y fuera de servicio** de cada uno. Se exige completar ambos para
  **Cargar datos**, que
  guarda sin enviar la semana. Los registros «En pisos» y «En emergencias» se
  conservan. Su PDF incluye únicamente quirófanos.
- El registro, modificación y envío están habilitados **todos los días** de
  forma temporal, hasta que se implemente el horario definitivo. La zona
  horaria de referencia para los períodos semanales sigue siendo
  **America/Caracas (Venezuela)**, independientemente de la hora del servidor.
- Después del envío se muestra centrado **SU REPORTE SEMANAL FUE ENVIADO A LA SALA
  SITUACIONAL DIGESALUD-MPPD. ESTE REPORTE SERA ENVIADO AL DIRECTOR DEL CENTRO
  DE SALUD POR EL DIRECTOR GENERAL DE DIGESALUD-MPPPD PARA SU CONFIRMACION**
  y se bloquean
  los cambios y nuevos envíos, también en el almacenamiento. El estado se
  conserva hasta el siguiente lunes a las 00:00, cuando se habilita el nuevo
  período sin borrar el inventario existente.
- Si el centro no ha enviado en el período actual, se muestra **Pendiente por
  reportar**, incluso si ya guardó registros o envió la semana anterior.
  El administrador ve estos mismos estados en el resumen de centros.
- Se permite registrar y actualizar; esta versión no elimina centros ni bienes.
  Las cuentas desactivadas conservan su inventario.

## Preparar el entorno

Requiere Python 3.11 o posterior.

```sh
cd /workspaces/inventario-centros-salud
python -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

### Desarrollo del inventario sin usuario ni contraseña

Para probar el inventario y los centros de ejemplo sin iniciar sesión, usa esta
opción explícita:

```sh
SALUD_DEVELOPMENT_MODE=1 .venv/bin/python -m streamlit run app.py --server.address=0.0.0.0 --server.port=8503
```

Este modo usa una base temporal separada: **todos los registros de prueba se
pierden al reiniciar el servidor**. No abre ni modifica la base normal, aunque
ya tenga cuentas. Las cuentas de prueba de los centros del catálogo usan una
contraseña interna aleatoria y aparecen en **Ver portal como**.
No muestra formularios de administración de centros ni cuentas. No uses
información real ni publiques el puerto como servicio de producción. La pantalla
muestra una advertencia permanente.
Los centros pueden registrar y enviar datos cualquier día, tanto en modo
desarrollo como con cuentas, mientras el horario definitivo esté pendiente.
Se mantiene un único envío por
centro y semana y el bloqueo de cambios después de enviar.

En la barra lateral, **Ver portal como** permite alternar entre la vista
**DIGESALUD-MPPD (Administrador)**, que solo consulta y descarga PDF, y la vista
de cualquier centro de salud, donde aparecen los botones de categoría con sus
formularios de carga. Las cuentas de centro de este modo solo existen en la base
temporal.

La caché de desarrollo conserva la ruta temporal, no una instancia del
almacenamiento. Si modificas métodos de `store.py` con el servidor en marcha,
reinicia Streamlit para recargar el módulo Python; actualizar solo el navegador
no garantiza que el servidor importe las nuevas funciones. El reinicio elimina
el inventario temporal y vuelve a cargar la lista de centros.

### Centros del PDF

[centers.json](./centers.json) contiene los 35 centros y usuarios suministrados
en el PDF. Se conservan los nombres y ubicaciones del documento, sin corregir
su ortografía. La ubicación se separa del nombre cuando aparece tras ` - `.
El registro 35 no trae ubicación; se deja en blanco.

Al abrir el modo de desarrollo se cargan automáticamente los 35 centros. El
usuario asignado se muestra al seleccionar cada centro.
El catálogo no contiene contraseñas y no crea cuentas de acceso de los centros.
En modo desarrollo, los usuarios se conservan como
datos de asignación, no como un inicio de sesión activo.

El catálogo permanece en el proyecto y vuelve a cargarse al reiniciar; los
inventarios de prueba siguen siendo temporales. Para la base normal, importa
el catálogo una sola vez desde una terminal privada:

```sh
.venv/bin/python store.py import-catalog
```

El comando registra los 35 centros con sus nombres y ubicaciones, sin crear
cuentas de acceso. Es idempotente: conserva los centros ya registrados y no
sobrescribe sus datos. No se ha importado nada en Residencias.

### Acceso final con cuentas

Para activar el acceso con cuentas,
inicia sin `SALUD_DEVELOPMENT_MODE=1` (está desactivado por defecto).

Antes de exponer el servidor, crea la cuenta administradora en una terminal
privada. No hay contraseñas predeterminadas ni formulario público de registro:

```sh
.venv/bin/python store.py bootstrap
```

El comando solicita usuario y contraseña sin guardarlos en el código. El usuario
admite de 3 a 40 letras sin acentos, números, punto, guion y guion bajo.
Las contraseñas requieren de 12 a 128 caracteres y se almacenan con scrypt y
sal aleatoria. No escribas credenciales en el chat ni en el repositorio.

```sh
.venv/bin/python -m streamlit run app.py --server.address=0.0.0.0 --server.port=8503
```

Abre el puerto 8503 en la vista previa del editor. Se usa un puerto diferente
del portal de Residencias. En modo con cuentas, la barra lateral del administrador
permite elegir **Informes** o **Cuentas de centros**. Esta última sección permite
crear un centro nuevo con su usuario y contraseña, o crear solo la
cuenta de un centro ya registrado en el catálogo seleccionándolo de la lista,
sin volver a escribir su nombre ni su ubicación. El administrador asigna el
usuario y la clave de cada cuenta y es quien puede cambiarlos; los centros no
cambian su propia contraseña. Debajo se muestra la lista
completa de cuentas registradas, cada una con su estado y un panel visible para
cambiar su contraseña, activar o desactivar su cuenta y
editar el nombre del centro, su ubicación y su usuario, sin eliminar el
inventario. Entrega las
credenciales por un canal privado, nunca en GitHub. Todos usan el mismo enlace:
el administrador consulta informes y cada centro accede solo a su inventario.
Para entrar como centro, cierra la sesión administradora e inicia sesión con la
cuenta del centro (o utiliza otro navegador). La gestión de cuentas no aparece
en modo de desarrollo.

Cada centro accede a su inventario con la clave asignada por el administrador;
solo el administrador puede cambiarla desde **Cuentas de centros**.
Las sesiones vencen tras 30 minutos sin actividad o un máximo de ocho horas.
Tras cinco intentos fallidos se bloquea la cuenta durante 15 minutos.
Cerrar sesión, cambiar/restablecer la contraseña o desactivar una cuenta revoca
sus sesiones. Al recargar por completo el navegador puede ser necesario volver
a iniciar sesión.

## Datos y publicación

Por defecto, el almacenamiento independiente es `data/inventario.sqlite3`.
Puedes configurar `SALUD_DATA_DIR` con una ruta absoluta privada y persistente
**antes** de crear la cuenta y ejecutar el servidor. No cambies esa ruta sin
trasladar y respaldar la base existente. No se usa Turso ni otra base externa
en esta primera versión.

### Demostración en Streamlit Community Cloud

Streamlit Community Cloud puede ejecutar esta aplicación directamente desde un
repositorio de GitHub. Es adecuada para demostraciones con datos ficticios,
pero no para conservar inventarios: la base SQLite está en el sistema de
archivos local y puede perderse al reiniciar o volver a desplegar la aplicación.
No cargues información real.

1. Sube la rama `main` a GitHub. No incluyas la base local, contraseñas,
   secretos ni respaldos; `data/` ya está excluido de Git.
2. En [Streamlit Community Cloud](https://share.streamlit.io/), conecta GitHub
   y selecciona **Create app**. Elige el repositorio, la rama `main` y
   `app.py` como archivo principal.
3. En **Advanced settings → Secrets**, configura un usuario administrador y
   una contraseña privada de al menos 12 caracteres:

   ```toml
   [bootstrap_admin]
   username = "admin"
   password = "reemplaza-por-una-clave-privada"
   ```

   No guardes estos valores en el repositorio ni los compartas. La aplicación
   crea la cuenta inicial desde esos secretos solo cuando la base aún no tiene
   una cuenta administradora.
4. Despliega la aplicación e inicia sesión con esas credenciales.

Si Community Cloud reinicia o reconstruye la aplicación, la cuenta se puede
volver a crear desde los secretos, pero los centros y los inventarios guardados
en SQLite pueden desaparecer. Para uso real se requiere una base de datos
externa persistente y copias de seguridad. Consulta la
[guía de despliegue de Streamlit](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app).

Antes de usar información real:

1. Valida formularios y permisos con datos ficticios en móvil y computadora.
2. Usa HTTPS y un servidor compatible con WebSocket.
3. Crea la cuenta administradora antes de compartir el acceso público.
4. Configura copias privadas de la base con la API de backup de SQLite o con
   el servidor detenido. Comprueba su restauración.
5. Mantén fuera de Git las bases, respaldos y secretos.

Este proyecto requiere su propio repositorio y despliegue; no se publica con
los cambios del repositorio Residencias. No introduzcas pacientes, donantes ni
datos personales de salud.

## Cuadros PDF

Los formularios usan los tipos del modelo entregado:

- Camas: hospitalización, observación, trauma shock, UTIA, UTIP y UCI.
- Ambulancias: soporte básico, soporte avanzado y tácticas.
- Vehículos protocolares: carros/camionetas, carga pesada/autobús y motos.
- Quirófanos: cantidades operativas y fuera de servicio en pisos y en emergencias.
- Bancos de sangre y laboratorios: presencia y estado.
- Equipos médicos especiales: cantidades operativas e inoperativas agrupadas por
  los ocho tipos del formulario. Se excluyen los equipos individuales históricos.

En la vista del centro, **GENERAR PDF** descarga únicamente el ítem seleccionado:
camas, vehículos (cinco cuadros separados: ambulancias, protocolares,
carga pesada, transporte de personal y motos), banco de sangre,
laboratorios, quirófanos, equipos o plantas eléctricas. Cambiar de ítem retira
la descarga anterior; hay que generar la del nuevo ítem. Se utilizan los datos
guardados, no cambios pendientes del formulario.

El informe completo de administración produce siete cuadros, incluido Plantas eléctricas, sin duplicar el de bancos de
sangre y laboratorios repetido en el modelo. Incluye OPE, INOP, total, fuente y
la firma `DIRECTOR DEL` seguida del nombre del centro. Se recrea la estructura
del modelo en páginas horizontales; no se modifica el PDF original.

En **RESUMEN DE LOS CENTROS DE SALUD**, la administración elige uno de los
siete botones: camas hospitalarias, vehículos, bancos de sangre, laboratorios,
quirófanos, equipos médicos especiales o plantas eléctricas.
Dentro de cada ítem selecciona un centro o todos y un tipo o todos los tipos.
Vehículos permite además elegir uno de sus cinco grupos o todos, y después
un tipo específico del grupo. Laboratorios ofrece Central, Emergencia,
Laboratorios especiales y los nombres de los especiales registrados.
Los ítems con un único tipo también permiten seleccionarlo individualmente.
La tabla muestra operativas, fuera de servicio y total únicamente de los tipos
seleccionados. **GENERAR REPORTE** descarga directamente el PDF filtrado, sin
otro botón de confirmación, para un centro o el consolidado con totales generales.
El PDF respeta todos los filtros: no incluye otros tipos ni sus cantidades.
Cambiar los filtros actualiza la descarga y su nombre de archivo.
Equipos incluye el detalle por
centro y descripción, las sumas por descripción y el total general.
Los cuadros extensos continúan en otras páginas con encabezados repetidos.

Un cero significa que no hay unidades registradas, no que el centro haya
certificado la ausencia de bienes. Si existen tipos antiguos que no corresponden
al modelo, la exportación solicita corregirlos en vez de omitir cantidades.
Las descargas respetan los permisos del centro; solo administración puede
generar el consolidado. En desarrollo siguen habilitadas sin contraseña.

En administración, **GENERAR REPORTE**, y en la cuenta de cada centro,
**DESCARGAR PDF**, aparecen directamente, sin un paso previo de generación.
El centro descarga únicamente
el ítem seleccionado. El archivo permanece
disponible durante la sesión aunque interactúes con otros controles; si cambian
los registros incluidos, el informe se actualiza automáticamente. Las descargas
no reinician la pantalla.

## Pruebas

Todos los PDF, por ítem, por centro y consolidados del administrador, incluyen
el título **[ÍTEM] DEL [NOMBRE DEL CENTRO]**, en mayúsculas, para los informes de
un centro (también descargados por administración). Los informes individuales
no repiten el nombre ni la ubicación debajo del título. La fecha y hora de
generación y el número de parte aparecen debajo de **FUENTE: Sala Situacional/DIGESALUD**.
La fecha y hora de generación usan **America/Caracas**, identificadas como
«hora de Venezuela», independientemente de la zona horaria del servidor.
Los consolidados usan
**[ÍTEM] DE TODOS LOS CENTROS DE SALUD**. Además, incluyen
el cintillo institucional de `cintillo.pdf` en cada página. Se conserva su
proporción y se reserva espacio sobre el título; los cuadros muestran hasta
cinco filas por página para no superponer tablas, firmas ni pie de página.

Las pruebas utilizan bases temporales, sin tocar datos reales:

```sh
.venv/bin/python -m unittest discover -s tests -v
```

Incluyen aislamiento entre centros, intentos con identificadores ajenos, permisos,
caducidad y revocación de sesiones, creación y edición atómicas, más de 35 centros y flujos
de acceso y registro con `streamlit.testing.v1.AppTest`.
Una prueba recorre individualmente los 35 centros del catálogo y sus siete ítems:
verifica encabezados y configuración comunes, PDF exclusivo del centro e ítem,
bloqueo de envío hasta cargar todas las secciones, confirmación final y
cantidades independientes en el resumen administrativo.
