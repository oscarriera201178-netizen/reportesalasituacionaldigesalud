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
Los 34 portales de centros muestran el cintillo institucional encima del cuadro
verde del nombre, ajustado al ancho disponible y sin deformarlo.
Debajo del título del administrador se muestra la semana del período de reporte
(lunes a viernes, hora de Venezuela) y **Centros de Salud que Han Reportado:
enviados/total Faltan: pendientes**. Se cuentan únicamente envíos del período actual y el total
se obtiene de los centros registrados, inicialmente 34.

Aplicación web HTML adaptable a móvil y computadora, con servidor Flask en
Python y almacenamiento independiente de Residencias. No consulta ni modifica
las bases de datos de Residencias. La interfaz principal se ejecuta desde
`webapp.py`; `app.py` se conserva como versión Streamlit anterior.
Todos los botones muestran sus títulos en mayúsculas y negrita, incluidos
categorías, formularios, carga, envío y descargas PDF.
El botón **CAMAS HOSPITALARIAS** permite varias líneas y ajusta su altura para
mostrar el texto completo.

## Primera versión

- Inventario privado: ninguna cantidad ni centro se muestra sin iniciar sesión.
- Una cuenta administradora y una cuenta por centro, sin límite fijo de centros.
  Cada centro tiene un número permanente, visible en los listados y selectores.
- La administración (DIGESALUD-MPPD) solo consulta y descarga PDF; no realiza
  cargas de inventario. En **Informes**, cada ítem permite elegir un centro o
  todos y un tipo o todos los tipos.
  Los estados semanales de los centros permanecen visibles y no cambian al
  filtrar el inventario; el contador semanal aparece bajo el título institucional.
  La sección separada **Cuentas de centros** permite crear y gestionar accesos.
  Los centros, usuarios, inventarios y reportes existentes se conservan.
- Administración también puede crear cuentas para las cinco instituciones
  militares. Estas cuentas solo ingresan y consultan sus propios registros en
  **Registro de Militares Fallecidos** y **Militares Involucrados en Accidentes
  de Tránsito**; no acceden al inventario ni a los
  informes de centros. Administración consulta el consolidado y genera el PDF.
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
  Los formularios de carga, edición y envío usan una ruta fija sin acentos ni
  espacios; el ítem se envía en el formulario y se valida en el servidor.
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
  SITUACIONAL DIGESALUD-MPPD, validar el mismo con el Director del Centro de
  Salud** y se bloquean
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
.venv/bin/python -m pip install -r requirements-dev.txt
```

### Ejecutar la aplicación HTML

Para iniciar la interfaz HTML desde la raíz del proyecto:

```sh
.venv/bin/python webapp.py
```

La aplicación local escucha en el puerto **8503**. En desarrollo usa una clave de
sesión temporal generada al arrancar; las sesiones del navegador se invalidan
al reiniciar. En producción configura `APP_ENV=production`,
`FLASK_SECRET_KEY` con un valor aleatorio privado y `COOKIE_SECURE=1`, y sirve
la aplicación detrás de HTTPS con un servidor WSGI. No publiques el servidor
de desarrollo de Flask en producción.

La interfaz HTML conserva inicio y cierre de sesión, cambio obligatorio de
contraseña, permisos de administrador y centros, formularios de las siete
secciones, bloqueo y envío semanal, administración de cuentas, informes y
descarga de PDF. Los cambios se guardan mediante el mismo almacenamiento y las
mismas validaciones del servidor que utiliza la versión anterior.

### Centros del PDF

[centers.json](./centers.json) contiene los 34 centros y usuarios suministrados
en el PDF. Se conservan los nombres y ubicaciones del documento, sin corregir
su ortografía. La ubicación se separa del nombre cuando aparece tras ` - `.
El registro 35 del PDF (MISION MILAGRA DIGESALUD) se eliminó del catálogo.

El catálogo no contiene contraseñas y no crea cuentas de acceso de los centros.

El catálogo permanece en el proyecto. Para importar sus centros una vez en la
base configurada, ejecuta desde una terminal privada:

```sh
.venv/bin/python store.py import-catalog
```

El comando registra los 34 centros con sus nombres y ubicaciones, sin crear
cuentas de acceso. Es idempotente: conserva los centros ya registrados y no
sobrescribe sus datos. No se ha importado nada en Residencias.

### Acceso con cuentas

Antes de exponer el servidor, crea la cuenta administradora en una terminal
privada. No hay contraseñas predeterminadas ni formulario público de registro:

```sh
.venv/bin/python store.py bootstrap
```

El comando solicita usuario y contraseña sin guardarlos en el código. El usuario
admite de 3 a 40 letras sin acentos, números, punto, guion y guion bajo.
Las contraseñas requieren de 12 a 128 caracteres y se almacenan con scrypt y
sal aleatoria. No escribas credenciales en el chat ni en el repositorio.

Inicia la interfaz HTML con `python webapp.py` y abre el puerto **8503** en la
vista previa del editor. Se usa un puerto diferente del portal de Residencias.
El administrador dispone de enlaces de navegación a **Informes** y
**Cuentas de centros**. Esta última sección permite
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
cuenta del centro (o utiliza otro navegador).

En **Cuentas de centros**, el administrador puede crear una cuenta para cada
institución militar. Estas cuentas disponen únicamente del formulario de
**Registro de Militares Fallecidos**, basado en el cuadro modelo: GDO/JQUIA,
nombre y apellidos, cédula, fecha de nacimiento, edad calculada a la fecha de
fallecimiento, fecha y causa de muerte, REDI, ZODI y unidad. El componente se
asigna desde la institución de la cuenta. GDO/JQUIA, causa y REDI se eligen de
listas; nombre, ZODI y unidad se guardan en mayúsculas, y las fechas usan el
selector de calendario. Los registros se pueden consultar y descargar en PDF,
pero no editar. Cada institución solo ve sus registros y administración puede
consultar el consolidado.
La búsqueda permite combinar filtros por REDI, causa, mes y año de fallecimiento y, para
administración, por componente o todos los componentes. Los mismos filtros se
aplican al PDF, que incluye cintillo institucional, fuente y fecha de generación
en cada página. Solo se generan cuadros de componentes con registros para esos
filtros; si no hay resultados se muestra un aviso en el portal. Las columnas
se ajustan al contenido y las filas crecen para mostrar el texto completo.
El año se selecciona de una lista con los años de los registros accesibles y el
año actual. Todos los campos de ingreso son obligatorios; el servidor rechaza
registros incompletos sin guardar datos parciales.

Los usuarios de centros de salud disponen además del ítem **Militares Fallecidos
en Centros de Salud**, independiente del inventario y de su envío semanal.
Usa los mismos datos y listas que el registro de componentes, pero el
centro debe seleccionar el componente del militar. El centro de salud se
asigna automáticamente desde la cuenta y no puede modificarse en el formulario.
Cada centro solo ingresa y consulta sus registros, sin editarlos después de
guardar. Administración consulta un consolidado exclusivo de centros, en un
único cuadro con columnas de componente y centro de salud; continúa en otras
páginas si es necesario, sin separar cuadros por institución. No se mezcla
con el consolidado de las cuentas de componentes.

El ítem **Militares atendidos por accidentes de Tránsito** es exclusivo
para centros de salud y también es independiente del envío semanal. Conserva los
datos del militar y su componente, pero usa **fecha de atención**, con edad
calculada en esa fecha. Todos los campos son obligatorios. Incluye estas listas:

- Tipo de accidente: Moto, Carro y Bicicleta.
- Condición: Heridas leves, Heridas graves, Politraumatismo severo,
  Politraumatismo leve, Politraumatismo craneoencefálico y Fallecido.
- Participación: Conductor, Pasajero y Peatón.

Cada centro ingresa y consulta solamente sus pacientes, sin editar después de
guardar. Administración consulta el consolidado en un único cuadro con componente
y centro de salud, y puede filtrar por componente, mes/año de atención, REDI y
tipo de accidente. Los mismos filtros se aplican al PDF con cintillo y pie de
letra institucional. Estos registros no se mezclan con los de fallecidos:
seleccionar **Fallecido** no crea automáticamente un registro de fallecimiento.

Ambos registros se encuentran dentro de **Registros de Pacientes Militares**,
disponible en el menú del centro. Administración dispone de **Registros de
Militares**, que reúne los cuatro reportes: militares fallecidos (componentes),
fallecidos en centros de salud, atendidos en centros por accidentes de tránsito
e involucrados en accidentes de tránsito (componentes). El botón **Regresar**
de cada reporte vuelve al menú correspondiente; el del menú agrupado vuelve al
inventario del centro o a los informes de administración, según la cuenta.
Dentro de los reportes, el único acceso de navegación es **Regresar**; no se
muestran accesos a cuentas, informes ni otros reportes. Los filtros y formularios
propios de cada reporte se conservan. Las cuentas de componentes ingresan a un
menú con sus dos registros y también regresan a ese menú desde cada reporte.

**Militares Involucrados en Accidentes de Tránsito** solo permite ingresar datos
a cuentas de componentes. Conserva los campos y las listas del registro de
accidentes de los centros, pero el **centro de salud de atención** se escribe
manualmente (obligatorio, en mayúsculas), para incluir centros públicos externos.
El componente se asigna desde la cuenta y no puede alterarse en el formulario.
Cada componente consulta únicamente sus registros, sin editarlos; administración
consulta y descarga su consolidado, con filtros por componente, mes/año de
atención, REDI y tipo de accidente. Estos datos se mantienen separados de los
accidentes registrados por centros y de los registros de fallecidos.

Al ingresar a cualquiera de estos dos registros, los centros ven únicamente el
formulario de ingreso y sus registros guardados, sin buscador ni controles de
generación de PDF. Administración conserva los filtros y la descarga de los
consolidados.

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
trasladar y respaldar la base existente. Si configuras `DATABASE_URL`, el portal
utiliza PostgreSQL externo en lugar de SQLite. Una conexión inválida o fallida
se muestra como error: nunca se reemplaza silenciosamente por una base local.
Los datos de este repositorio no son necesariamente los datos de producción.

### PostgreSQL gratuito en Supabase (São Paulo)

PostgreSQL es software libre. Supabase ofrece alojamiento gratuito con límites:
[500 MB de base y pausa tras una semana de inactividad](https://supabase.com/pricing).
Selecciona explícitamente **South America (São Paulo), `sa-east-1`** entre
las [regiones disponibles](https://supabase.com/docs/guides/platform/regions);
la región general «Americas» no significa Brasil. La cercanía geográfica no
garantiza menor latencia: también importa la conexión entre el servicio web y
la base. No hay garantía de disponibilidad continua en el plan gratuito.

#### 1. Proteger los datos existentes antes de publicar cambios

**No reinicies, redespliegues ni cambies secretos de la aplicación actual antes
de obtener un respaldo privado de su SQLite de producción.** Publicar código
para añadir un botón de respaldo también puede reconstruir el contenedor y
perder el archivo que intentas proteger.

Esta versión incluye, solo para el administrador usando SQLite, **Respaldo
privado de datos → Descargar respaldo SQLite** en el panel de informes.
Genera una copia consistente mediante la API de backup de SQLite; incluye
cuentas, hashes de contraseñas, inventarios, sesiones y fechas. El botón
solo estará disponible cuando esta versión esté ejecutándose; no recupera
archivos de una versión anterior ni de otro contenedor.

Si la versión publicada aún no tiene el botón, necesitas obtener el archivo
desde ese entorno o coordinar su recuperación con el soporte del alojamiento.
Si no tienes acceso al archivo, **detén la migración**: no se puede garantizar
la conservación de datos exportando solamente PDF o copiando el repositorio.

Guarda el respaldo fuera de Git, en una ubicación privada, y conserva otra
copia independiente. Para el corte final, coordina que nadie cargue datos
desde el momento del respaldo hasta terminar la migración; lo ingresado después
de esa copia no se trasladará automáticamente.

#### 2. Crear el destino y ensayar la migración

Si decides **comenzar con una base nueva**, sin recuperar los inventarios
anteriores, no ejecutes la migración. Con el proyecto vacío y `DATABASE_URL`
introducida en una terminal privada como se explica abajo, ejecuta:

```bash
python store.py bootstrap
python store.py import-catalog
unset DATABASE_URL
```

El primer comando solicita un usuario administrador y una contraseña de al
menos 12 caracteres, con confirmación. El segundo importa los centros, pero no
crea sus cuentas ni recupera cargas anteriores. Verifica que ambos comandos
terminen correctamente antes de publicar los cambios y configurar las
variables privadas del servicio web según el paso 3. Después, asigna cuentas y contraseñas desde **Cuentas de
centros**. Este procedimiento crea un inventario nuevo, no restaura el anterior.

1. Crea un proyecto Supabase en São Paulo y guarda su contraseña en privado.
2. En **Connect → Session pooler**, copia la cadena PostgreSQL en modo sesión
   (puerto **5432**), compatible con IPv4 y tu servicio de aplicación. No uses la URL de
   la API ni las claves `anon`/`service_role`. Obtén el host y usuario del panel;
   no los deduzcas del nombre de la región.
3. Añade `sslmode=require` a la cadena (con `?` o `&`, según corresponda).
   Codifica los caracteres reservados de la contraseña en formato URL.
   Consulta la [guía de conexión](https://supabase.com/docs/guides/database/connecting-to-postgres).
4. En una terminal privada con las dependencias instaladas, introduce la cadena
   sin dejarla en el historial:

   ```bash
   read -r -s -p "Conexión PostgreSQL privada: " DATABASE_URL
   echo
   export DATABASE_URL
   python migrate_database.py --source /ruta/privada/inventario.sqlite3
   ```

Sin `--apply`, se ensaya la copia y se comparan todos los valores dentro de una
transacción que se revierte; el destino queda sin datos, aunque se crean las
tablas. El origen se abre en modo lectura y sus actualizaciones de esquema se
realizan solo en una copia temporal. Se comprueba su integridad, las referencias
y la presencia de la cuenta administradora. Se rechazan esquemas desconocidos
y destinos con datos; no se borra ni sobrescribe información.

PostgreSQL usa `citext` para las columnas sin distinción de mayúsculas. Según
la configuración regional, puede considerar iguales nombres con letras no ASCII
que SQLite distinguía; cualquier conflicto cancela la copia completa. Resuélvelo
en una copia privada antes de repetir, sin modificar el único respaldo.

#### 3. Copiar y conectar producción

Tras un ensayo satisfactorio y con las cargas detenidas:

```bash
python migrate_database.py --source /ruta/privada/inventario.sqlite3 --apply
unset DATABASE_URL
```

El comando verifica cada fila, confirma la transacción solo si coincide y ajusta
las secuencias para que los nuevos registros no reutilicen números existentes.
Conserva cuentas y contraseñas actuales, permisos, históricos y estados semanales.
No ejecutes dos aplicaciones que acepten cargas en bases diferentes.

Solo después de verificar la migración, publica estos cambios y configura
`DATABASE_URL` como variable privada de entorno en el servicio web:

No guardes la cadena en el repositorio ni la compartas por chat. El portal no
crea automáticamente la cuenta administradora: créala previamente con
`python store.py bootstrap`.
Verifica el acceso con las cuentas originales, los totales y los PDF antes de
reanudar las cargas.

La conexión se usa solo en el servidor. Las tablas tienen Row Level Security
sin políticas públicas; usa la cuenta PostgreSQL propietaria para esta aplicación
y no añadas políticas que expongan usuarios, sesiones o inventarios a la API.
El almacenamiento mantiene transacciones serializadas para conservar los
controles de permisos y carga semanal existentes.
Los informes consultan cada tabla de inventario una sola vez por lectura,
en lugar de repetir siete consultas por centro: para 34 centros pasan de
238 a 7 consultas de inventario, conservando el orden y los permisos.

#### 4. Respaldos independientes y pruebas

El plan gratuito no incluye los respaldos diarios de los planes de pago.
Configura exportaciones privadas regulares y prueba su restauración:
[documentación de respaldos](https://supabase.com/docs/guides/platform/backups).
Desde una terminal privada con herramientas PostgreSQL de versión compatible,
usa una conexión directa o de sesión, nunca el pooler de transacciones:

```bash
umask 077
pg_dump "$DATABASE_URL" --format=custom --no-owner --no-acl --file=/ruta/privada/inventario.dump
```

Vuelve a introducir `DATABASE_URL` en privado para este comando. Guarda copias
fuera del proveedor y restaura primero en un proyecto de prueba vacío con
`pg_restore --no-owner --no-acl --dbname="$DATABASE_URL" /ruta/privada/inventario.dump`.
No restaures sobre producción sin un plan de recuperación.

Las pruebas normales se ejecutan con `python -m unittest discover -s tests`.
Las pruebas de integración PostgreSQL se habilitan con
`SALUD_TEST_DATABASE_URL` apuntando **exclusivamente a un servidor de pruebas**:
crean y eliminan bases temporales y requieren permiso para crear bases y roles.
Nunca uses credenciales ni datos de producción para estas pruebas.

### Despliegue de la aplicación HTML

Esta versión está preparada para Vercel. El archivo `pyproject.toml` define
`webapp:app` como punto de entrada, `.python-version` selecciona Python 3.12
y `public/` contiene los recursos estáticos que Vercel publica por CDN.
Las dependencias de ejecución se declaran tanto en `pyproject.toml` como en
`requirements.txt`; mantén ambas listas sincronizadas para Vercel y desarrollo.

1. Importa el repositorio en Vercel.
2. Desde **Storage/Marketplace**, crea una base PostgreSQL nueva y conecta la
   integración al proyecto. Vercel ya no ofrece su antiguo producto Postgres;
   Marketplace permite proveedores como Neon, Supabase, Prisma Postgres y AWS
   Aurora. Configura la cadena de conexión como `DATABASE_URL` en Production
   y Preview. No uses SQLite: el sistema de archivos de Vercel Functions no es
   persistente.
3. Configura estas variables en Vercel, sin agregarlas al repositorio:
   - `APP_ENV=production`
   - `COOKIE_SECURE=1`
   - `FLASK_SECRET_KEY`: una clave aleatoria privada.
   - `BOOTSTRAP_ADMIN_USERNAME` y `BOOTSTRAP_ADMIN_PASSWORD`: credenciales
     iniciales privadas; la contraseña debe tener entre 12 y 128 caracteres.
4. Despliega. En el primer arranque con una base vacía, la aplicación crea la
   cuenta administradora e importa el catálogo de centros. Después puedes
   retirar las dos variables `BOOTSTRAP_ADMIN_*`; las cuentas ya quedan en
   PostgreSQL. Crea las cuentas de los centros desde **Cuentas de centros**.
5. Inicia sesión y verifica reportes, formularios y permisos antes de usar
   información real. Si reinicias el proyecto, conserva la base Marketplace:
   “empezar de cero” solo requiere una base vacía nueva, no borrar los recursos
   de la aplicación.

Vercel ejecuta Flask como una Function y publica CSS e imágenes desde `public/`.
Consulta la [guía de Flask en Vercel](https://vercel.com/docs/frameworks/backend/flask),
la [documentación de PostgreSQL en Vercel](https://vercel.com/docs/postgres) y
las [limitaciones del sistema de archivos](https://vercel.com/docs/functions/runtimes).

Antes de usar información real:

1. Valida formularios y permisos con datos ficticios en móvil y computadora.
2. Usa HTTPS y un servidor compatible con WebSocket.
3. Crea la cuenta administradora antes de compartir el acceso público.
4. Configura copias privadas de la base con la API de backup de SQLite o con
   el servidor detenido. Comprueba su restauración.
5. Mantén fuera de Git las bases, respaldos y secretos.

El Registro de Militares Fallecidos contiene datos personales y requiere acceso
restringido. Comparte las cuentas y los PDF solo con personal autorizado y
mantén las copias de seguridad privadas.

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
generar el consolidado.

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

Incluyen pruebas del HTML/Flask y compatibilidad de la interfaz anterior,
aislamiento entre centros, intentos con identificadores ajenos, permisos,
caducidad y revocación de sesiones, creación y edición atómicas, más de 35 centros y flujos
de acceso y registro con `streamlit.testing.v1.AppTest`.
Una prueba recorre individualmente los 34 centros del catálogo y sus siete ítems:
verifica encabezados y configuración comunes, PDF exclusivo del centro e ítem,
bloqueo de envío hasta cargar todas las secciones, confirmación final y
cantidades independientes en el resumen administrativo.
